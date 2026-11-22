"""Import dialog: shows the detected settings and lets the user change them."""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.data.importer import CsvImportError, ImportPreview, ImportSettings, analyze
from csvjuggler.i18n import Msg, tr
from csvjuggler.ui.widgets import DisposableDialog

log = logging.getLogger(__name__)

PREVIEW_LINES = 40
ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


class ImportDialog(DisposableDialog):
    def __init__(
        self, path: str | Path, alias: str, preview: ImportPreview, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.preview = preview
        self._settings = copy.deepcopy(preview.settings)
        self._updating = False
        self.setWindowTitle(tr(Msg.IMPORT_TITLE).format(name=self.path.name))
        self.resize(1000, 650)

        self.alias_edit = QLineEdit(alias)
        self.encoding_combo = QComboBox()
        self.encoding_combo.setEditable(True)
        self.encoding_combo.addItems(ENCODINGS)
        self.delimiter_combo = QComboBox()
        for text, value in (
            (Msg.DELIM_COMMA, ","),
            (Msg.DELIM_SEMICOLON, ";"),
            (Msg.DELIM_TAB, "\t"),
        ):
            self.delimiter_combo.addItem(tr(text), value)
        self.decimal_combo = QComboBox()
        self.decimal_combo.addItem(tr(Msg.DECIMAL_DOT), ".")
        self.decimal_combo.addItem(tr(Msg.DECIMAL_COMMA), ",")
        self.header_spin = self._row_spin(allow_none=True)
        self.unit_spin = self._row_spin(allow_none=True)
        self.data_start_spin = self._row_spin(allow_none=False)
        self.time_mode_combo = QComboBox()
        for text, value in (
            (Msg.TIME_MODE_COLUMN, "column"),
            (Msg.TIME_MODE_PAIRS, "pairs"),
            (Msg.TIME_MODE_INDEX, "index"),
        ):
            self.time_mode_combo.addItem(tr(text), value)
        self.time_column_combo = QComboBox()
        self.time_unit_combo = QComboBox()
        for text, value in (
            (Msg.TIME_UNIT_S, "s"),
            (Msg.TIME_UNIT_MS, "ms"),
            (Msg.TIME_UNIT_US, "us"),
            (Msg.TIME_UNIT_DATETIME, "datetime"),
        ):
            self.time_unit_combo.addItem(tr(text), value)
        self.datetime_edit = QLineEdit()
        self.datetime_edit.setPlaceholderText(tr(Msg.IMPORT_DATETIME_HINT))

        form = QFormLayout()
        form.addRow(tr(Msg.IMPORT_ALIAS), self.alias_edit)
        form.addRow(tr(Msg.IMPORT_ENCODING), self.encoding_combo)
        form.addRow(tr(Msg.IMPORT_DELIMITER), self.delimiter_combo)
        form.addRow(tr(Msg.IMPORT_DECIMAL), self.decimal_combo)
        form.addRow(tr(Msg.IMPORT_HEADER_ROW), self.header_spin)
        form.addRow(tr(Msg.IMPORT_UNIT_ROW), self.unit_spin)
        form.addRow(tr(Msg.IMPORT_DATA_START), self.data_start_spin)
        form.addRow(tr(Msg.IMPORT_TIME_MODE), self.time_mode_combo)
        form.addRow(tr(Msg.IMPORT_TIME_COLUMN), self.time_column_combo)
        form.addRow(tr(Msg.IMPORT_TIME_UNIT), self.time_unit_combo)
        form.addRow(tr(Msg.IMPORT_DATETIME_FORMAT), self.datetime_edit)
        self.scope_label = QLabel(f"<b>{tr(Msg.IMPORT_SCOPE_DETECTED)}</b>")
        form.addRow(self.scope_label)

        self.raw_view = QPlainTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        raw_box = QGroupBox(tr(Msg.IMPORT_FILE_PREVIEW))
        QVBoxLayout(raw_box).addWidget(self.raw_view)

        self.series_table = QTableWidget(0, 3)
        self.series_table.setHorizontalHeaderLabels(
            [tr(Msg.IMPORT_COL_NAME), tr(Msg.IMPORT_COL_UNIT), tr(Msg.IMPORT_COL_ALIAS)]
        )
        self.series_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        series_box = QGroupBox(tr(Msg.IMPORT_SERIES))
        QVBoxLayout(series_box).addWidget(self.series_table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addLayout(form)
        left_layout.addWidget(series_box, 1)
        top = QHBoxLayout()
        top.addWidget(left, 1)
        top.addWidget(raw_box, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top, 1)
        layout.addWidget(buttons)

        self._load_widgets(self.preview)
        for combo in (
            self.encoding_combo,
            self.delimiter_combo,
            self.decimal_combo,
            self.time_mode_combo,
            self.time_column_combo,
            self.time_unit_combo,
        ):
            combo.currentIndexChanged.connect(self._on_changed)
        self.encoding_combo.editTextChanged.connect(self._on_changed)
        for spin in (self.header_spin, self.unit_spin, self.data_start_spin):
            spin.valueChanged.connect(self._on_changed)
        self.datetime_edit.editingFinished.connect(self._on_changed)

    # -- widgets <-> settings -------------------------------------------------------------

    @staticmethod
    def _row_spin(allow_none: bool) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0 if allow_none else 1, 1_000_000)
        if allow_none:
            spin.setSpecialValueText(tr(Msg.IMPORT_NONE))  # 0 = none; lines are 1-based
        return spin

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _load_widgets(self, preview: ImportPreview) -> None:
        s = preview.settings
        self._updating = True
        try:
            self.encoding_combo.setCurrentText(s.encoding)
            self._set_combo_data(self.delimiter_combo, s.delimiter)
            self._set_combo_data(self.decimal_combo, s.decimal)
            self.header_spin.setValue(0 if s.header_row is None else s.header_row + 1)
            self.unit_spin.setValue(0 if s.unit_row is None else s.unit_row + 1)
            self.data_start_spin.setValue(s.data_start + 1)
            self._set_combo_data(self.time_mode_combo, s.time_mode)
            self.time_column_combo.clear()
            for col in preview.columns:
                self.time_column_combo.addItem(col, col)
            if s.time_column:
                self._set_combo_data(self.time_column_combo, s.time_column)
            self._set_combo_data(self.time_unit_combo, s.time_unit)
            self.datetime_edit.setText(s.datetime_format)
            self.time_column_combo.setEnabled(s.time_mode == "column")
            self.scope_label.setVisible(preview.is_scope)
            self._fill_raw(preview.lines)
            self._fill_series(preview)
        finally:
            self._updating = False

    def _fill_raw(self, lines: list[str]) -> None:
        numbered = [f"{i + 1:>4} │ {ln}" for i, ln in enumerate(lines[:PREVIEW_LINES])]
        self.raw_view.setPlainText("\n".join(numbered))

    def _fill_series(self, preview: ImportPreview) -> None:
        renames = dict(self._settings.renames)
        renames.update(self._current_renames())
        self.series_table.setRowCount(len(preview.series_names))
        for row, name in enumerate(preview.series_names):
            for col, text in enumerate((name, preview.units.get(name, ""))):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.series_table.setItem(row, col, item)
            self.series_table.setItem(row, 2, QTableWidgetItem(renames.get(name, "")))

    def _current_renames(self) -> dict[str, str]:
        renames: dict[str, str] = {}
        for row in range(self.series_table.rowCount()):
            name_item, alias_item = self.series_table.item(row, 0), self.series_table.item(row, 2)
            if name_item and alias_item and alias_item.text().strip():
                renames[name_item.text()] = alias_item.text().strip()
        return renames

    def _read_widgets(self) -> ImportSettings:
        s = copy.deepcopy(self._settings)
        s.encoding = self.encoding_combo.currentText().strip() or "utf-8"
        s.delimiter = self.delimiter_combo.currentData()
        s.decimal = self.decimal_combo.currentData()
        s.header_row = self.header_spin.value() - 1 if self.header_spin.value() else None
        s.unit_row = self.unit_spin.value() - 1 if self.unit_spin.value() else None
        s.data_start = self.data_start_spin.value() - 1
        s.time_mode = self.time_mode_combo.currentData()
        s.time_column = self.time_column_combo.currentData() if s.time_mode == "column" else None
        s.time_unit = self.time_unit_combo.currentData()
        s.datetime_format = self.datetime_edit.text().strip()
        s.renames = self._current_renames()
        return s

    def _on_changed(self, *_args: object) -> None:
        if self._updating:
            return
        settings = self._read_widgets()
        try:
            preview = analyze(self.path, settings)
        except (CsvImportError, LookupError) as exc:  # LookupError: unknown encoding
            log.debug("Preview failed: %s", exc)
            self.ok_button.setEnabled(False)
            return
        self.ok_button.setEnabled(True)
        self.preview = preview
        self._settings = settings
        self._load_widgets(preview)

    # -- results --------------------------------------------------------------------------

    def settings(self) -> ImportSettings:
        return self._read_widgets()

    def alias(self) -> str:
        return self.alias_edit.text().strip().replace("/", "_")
