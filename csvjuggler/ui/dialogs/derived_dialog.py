"""Dialog defining a derived series (name, formula, variables)."""

from __future__ import annotations

import copy
import string

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.data.derived import DerivedSeriesConfig, FormulaError
from csvjuggler.i18n import Msg, tr
from csvjuggler.model.session import Session
from csvjuggler.ui.widgets import DisposableDialog


class DerivedDialog(DisposableDialog):
    def __init__(
        self,
        session: Session,
        config: DerivedSeriesConfig | None = None,
        preselected: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(tr(Msg.DERIVED_TITLE))
        self.resize(640, 480)
        if config is None:
            ids = preselected or []
            letters = list(string.ascii_lowercase)
            variables = dict(zip(letters, ids, strict=False))
            default = " / ".join(list(variables)[:2]) if len(variables) >= 2 else "a"
            config = DerivedSeriesConfig(name="", formula=default, variables=variables)
        self._config = copy.deepcopy(config)

        self.name_edit = QLineEdit(config.name)
        self.formula_edit = QLineEdit(config.formula)
        self.unit_edit = QLineEdit(config.unit)
        help_label = QLabel(tr(Msg.DERIVED_HELP))
        help_label.setWordWrap(True)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr(Msg.DERIVED_VAR), tr(Msg.DERIVED_SERIES)])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for var, series_id in config.variables.items():
            self.add_variable(var, series_id)
        add_button = QPushButton(tr(Msg.DERIVED_ADD_VAR), self)
        add_button.clicked.connect(lambda: self.add_variable())
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #c62828")
        self.error_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow(tr(Msg.DERIVED_NAME), self.name_edit)
        form.addRow(tr(Msg.DERIVED_FORMULA), self.formula_edit)
        form.addRow(tr(Msg.DERIVED_UNIT), self.unit_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(help_label)
        layout.addWidget(QLabel(tr(Msg.DERIVED_VARIABLES)))
        layout.addWidget(self.table)
        layout.addWidget(add_button)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

    def _series_combo(self, series_id: str | None) -> QComboBox:
        combo = QComboBox()
        for ds in self.session.datasets:
            for s in ds.series.values():
                if s.id == f"calc/{self._config.name}" and self._config.name:
                    continue  # a series cannot use itself
                combo.addItem(f"{ds.alias} / {s.label}", s.id)
        if series_id:
            combo.setCurrentIndex(max(0, combo.findData(series_id)))
        return combo

    def add_variable(self, var: str | None = None, series_id: str | None = None) -> None:
        used = {self._var_name(r) for r in range(self.table.rowCount())}
        if var is None:
            var = next((c for c in string.ascii_lowercase if c not in used), f"v{len(used)}")
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(var))
        self.table.setCellWidget(row, 1, self._series_combo(series_id))

    def _var_name(self, row: int) -> str:
        item = self.table.item(row, 0)
        return item.text().strip() if item is not None else ""

    def config(self) -> DerivedSeriesConfig:
        variables: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            var = self._var_name(row)
            combo = self.table.cellWidget(row, 1)
            if var and isinstance(combo, QComboBox) and combo.currentData():
                variables[var] = combo.currentData()
        return DerivedSeriesConfig(
            name=self.name_edit.text().strip().replace("/", "_"),
            formula=self.formula_edit.text().strip(),
            variables=variables,
            unit=self.unit_edit.text().strip(),
        )

    def accept(self) -> None:
        config = self.config()
        try:
            if not config.name:
                raise FormulaError("Nom de série invalide.")
            self.session.check_derived(config)
        except FormulaError as exc:
            self.error_label.setText(tr(Msg.DERIVED_ERROR).format(error=exc))
            return
        super().accept()
