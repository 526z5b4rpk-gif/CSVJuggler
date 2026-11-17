"""CSV export dialog: range and series to export, separators."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.data.export import CsvExportOptions
from csvjuggler.i18n import Msg, tr

SERIES_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class ExportCsvDialog(QDialog):
    """``ranges``: available ``(label, x0, x1)``; ``series``: ``(label, id, checked)``."""

    def __init__(
        self,
        ranges: list[tuple[str, float, float]],
        series: list[tuple[str, str, bool]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(Msg.EXPORT_CSV_TITLE))
        self._ranges = ranges
        self.range_combo = QComboBox()
        for label, x0, x1 in ranges:
            self.range_combo.addItem(f"{label}  [{x0:.6g} ; {x1:.6g}]")
        self.range_combo.setCurrentIndex(len(ranges) - 1)  # the most specific one
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
        self.series_list = QListWidget()
        for label, series_id, checked in series:
            item = QListWidgetItem(label)
            item.setData(SERIES_ID_ROLE, series_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.series_list.addItem(item)

        form = QFormLayout()
        form.addRow(tr(Msg.EXPORT_RANGE), self.range_combo)
        form.addRow(tr(Msg.IMPORT_DELIMITER), self.delimiter_combo)
        form.addRow(tr(Msg.IMPORT_DECIMAL), self.decimal_combo)
        box = QGroupBox(tr(Msg.EXPORT_SERIES))
        QVBoxLayout(box).addWidget(self.series_list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(box)
        layout.addWidget(buttons)

    def interval(self) -> tuple[float, float]:
        _label, x0, x1 = self._ranges[self.range_combo.currentIndex()]
        return x0, x1

    def series_ids(self) -> list[str]:
        out = []
        for row in range(self.series_list.count()):
            item = self.series_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(SERIES_ID_ROLE))
        return out

    def options(self) -> CsvExportOptions:
        return CsvExportOptions(
            delimiter=self.delimiter_combo.currentData(), decimal=self.decimal_combo.currentData()
        )
