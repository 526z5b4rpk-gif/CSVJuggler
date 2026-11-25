"""Curve settings dialog."""

from __future__ import annotations

import copy

from PySide6.QtCore import QSignalBlocker, Signal
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


class CurveSettingsWidget(QWidget):
    """Form editing a :class:`CurveConfig` (used by the dialog and by the toolbox).

    :attr:`changed` is emitted on every user edit; :meth:`set_curve` does not emit it.
    """

    changed = Signal()

    def __init__(
        self, curve: CurveConfig, series_label: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._curve = copy.deepcopy(curve)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.alias_edit = QLineEdit(self)
        self.color_button = ColorButton(parent=self)
        self.width_spin = _spin(0.1, 20.0, 1.0, decimals=1)
        self.style_combo = _combo(STYLE_CHOICES, "solid")
        self.marker_combo = _combo(MARKER_CHOICES, "none")
        self.marker_size_spin = _spin(1.0, 50.0, 6.0, decimals=1)
        self.mode_combo = _combo(MODE_CHOICES, "line")
        self.gain_spin = _spin(-1e12, 1e12, 1.0)
        self.offset_spin = _spin(-1e12, 1e12, 0.0)
        self.visible_check = QCheckBox(tr(Msg.LBL_VISIBLE), self)
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
        self.set_curve(curve, series_label)
        self.alias_edit.editingFinished.connect(self.changed)
        self.color_button.color_changed.connect(self.changed)
        for spin in (self.width_spin, self.marker_size_spin, self.gain_spin, self.offset_spin):
            spin.valueChanged.connect(self.changed)
        for combo in (self.style_combo, self.marker_combo, self.mode_combo):
            combo.currentIndexChanged.connect(self.changed)
        self.visible_check.toggled.connect(self.changed)

    def set_curve(self, curve: CurveConfig, series_label: str) -> None:
        widgets = (
            self.alias_edit,
            self.color_button,
            self.width_spin,
            self.style_combo,
            self.marker_combo,
            self.marker_size_spin,
            self.mode_combo,
            self.gain_spin,
            self.offset_spin,
            self.visible_check,
        )
        blockers = [QSignalBlocker(w) for w in widgets]
        self._curve = copy.deepcopy(curve)
        self.alias_edit.setText(curve.alias or "")
        self.alias_edit.setPlaceholderText(series_label)
        self.color_button.set_color(curve.color)
        self.width_spin.setValue(curve.width)
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(curve.style)))
        self.marker_combo.setCurrentIndex(max(0, self.marker_combo.findData(curve.marker)))
        self.marker_size_spin.setValue(curve.marker_size)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(curve.mode)))
        self.gain_spin.setValue(curve.gain)
        self.offset_spin.setValue(curve.offset)
        self.visible_check.setChecked(curve.visible)
        del blockers

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


class CurveSettingsDialog(DisposableDialog):
    def __init__(
        self, curve: CurveConfig, series_label: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(Msg.CURVE_SETTINGS_TITLE).format(name=series_label))
        self.editor = CurveSettingsWidget(curve, series_label, self)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.editor)
        layout.addWidget(buttons)

    def curve(self) -> CurveConfig:
        return self.editor.curve()
