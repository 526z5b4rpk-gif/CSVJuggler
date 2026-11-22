"""Curve settings dialog."""

from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.plot_config import CurveConfig
from csvjuggler.ui.dialogs.plot_settings_dialog import _combo, _spin
from csvjuggler.ui.widgets import ColorButton, DisposableDialog

STYLE_CHOICES = ((Msg.STYLE_SOLID, "solid"), (Msg.STYLE_DASH, "dash"), (Msg.STYLE_DOT, "dot"))
MARKER_CHOICES = (
    (Msg.MARKER_NONE, "none"),
    (Msg.MARKER_CIRCLE, "o"),
    (Msg.MARKER_SQUARE, "s"),
    (Msg.MARKER_CROSS, "x"),
)
MODE_CHOICES = ((Msg.MODE_LINE, "line"), (Msg.MODE_STEP, "step"), (Msg.MODE_POINTS, "points"))


class CurveSettingsDialog(DisposableDialog):
    def __init__(
        self, curve: CurveConfig, series_label: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(Msg.CURVE_SETTINGS_TITLE).format(name=series_label))
        self._curve = copy.deepcopy(curve)
        form = QFormLayout()
        self.alias_edit = QLineEdit(curve.alias or "")
        self.alias_edit.setPlaceholderText(series_label)
        self.color_button = ColorButton(curve.color)
        self.width_spin = _spin(0.1, 20.0, curve.width, decimals=1)
        self.style_combo = _combo(STYLE_CHOICES, curve.style)
        self.marker_combo = _combo(MARKER_CHOICES, curve.marker)
        self.marker_size_spin = _spin(1.0, 50.0, curve.marker_size, decimals=1)
        self.mode_combo = _combo(MODE_CHOICES, curve.mode)
        self.gain_spin = _spin(-1e12, 1e12, curve.gain)
        self.offset_spin = _spin(-1e12, 1e12, curve.offset)
        self.visible_check = QCheckBox(tr(Msg.LBL_VISIBLE))
        self.visible_check.setChecked(curve.visible)
        form.addRow(tr(Msg.LBL_ALIAS), self.alias_edit)
        form.addRow(tr(Msg.LBL_COLOR), self.color_button)
        form.addRow(tr(Msg.LBL_WIDTH), self.width_spin)
        form.addRow(tr(Msg.LBL_STYLE), self.style_combo)
        form.addRow(tr(Msg.LBL_MARKER), self.marker_combo)
        form.addRow(tr(Msg.LBL_MARKER_SIZE), self.marker_size_spin)
        form.addRow(tr(Msg.LBL_MODE), self.mode_combo)
        form.addRow(tr(Msg.LBL_GAIN), self.gain_spin)
        form.addRow(tr(Msg.LBL_OFFSET), self.offset_spin)
        form.addRow(self.visible_check)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def curve(self) -> CurveConfig:
        c = copy.deepcopy(self._curve)
        c.alias = self.alias_edit.text().strip() or None
        c.color = self.color_button.color or c.color
        c.width = self.width_spin.value()
        c.style = self.style_combo.currentData()
        c.marker = self.marker_combo.currentData()
        c.marker_size = self.marker_size_spin.value()
        c.mode = self.mode_combo.currentData()
        c.gain = self.gain_spin.value()
        c.offset = self.offset_spin.value()
        c.visible = self.visible_check.isChecked()
        return c
