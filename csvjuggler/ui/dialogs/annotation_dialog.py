"""Annotation edit dialog."""

from __future__ import annotations

import copy

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.annotation import Annotation
from csvjuggler.ui.dialogs.plot_settings_dialog import _spin
from csvjuggler.ui.widgets import ColorButton

KIND_NAMES = {
    "text": Msg.ANN_TEXT,
    "vline": Msg.ANN_VLINE,
    "hline": Msg.ANN_HLINE,
    "region": Msg.ANN_REGION,
}


class AnnotationDialog(QDialog):
    def __init__(self, ann: Annotation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{tr(Msg.ANN_DIALOG_TITLE)} — {tr(KIND_NAMES[ann.kind])}")
        self._ann = copy.deepcopy(ann)
        form = QFormLayout()
        self.text_edit = QLineEdit(ann.text)
        self.color_button = ColorButton(ann.color)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(5, 72)
        self.font_spin.setValue(ann.font_size)
        self.background_button = ColorButton(ann.text_background, allow_none=True)
        no_bg = QPushButton(tr(Msg.ANN_NO_BACKGROUND))
        no_bg.clicked.connect(lambda: self.background_button.set_color(None))
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.background_button)
        bg_row.addWidget(no_bg)
        self.opacity_spin = _spin(0.05, 1.0, ann.opacity, decimals=2)
        self.opacity_spin.setSingleStep(0.05)
        self.locked_check = QCheckBox(tr(Msg.ANN_LBL_LOCKED))
        self.locked_check.setChecked(ann.locked)
        self.arrow_check = QCheckBox(tr(Msg.ANN_LBL_ARROW))
        self.arrow_check.setChecked(ann.arrow)
        self.link_check = QCheckBox(tr(Msg.ANN_LBL_LINK_ALL))
        self.link_check.setChecked(ann.link_all)
        self.x_spin = _spin(-1e300, 1e300, ann.x, decimals=9)
        self.y_spin = _spin(-1e300, 1e300, ann.y, decimals=9)
        self.x2_spin = _spin(-1e300, 1e300, ann.x2, decimals=9)

        form.addRow(tr(Msg.ANN_LBL_TEXT), self.text_edit)
        form.addRow(tr(Msg.LBL_COLOR), self.color_button)
        form.addRow(tr(Msg.ANN_LBL_FONT_SIZE), self.font_spin)
        form.addRow(tr(Msg.ANN_LBL_BACKGROUND), bg_row)
        form.addRow(tr(Msg.ANN_LBL_OPACITY), self.opacity_spin)
        if ann.kind != "hline":
            form.addRow(tr(Msg.ANN_LBL_X), self.x_spin)
        if ann.kind in ("text", "hline"):
            form.addRow(tr(Msg.ANN_LBL_Y), self.y_spin)
        if ann.kind == "region":
            form.addRow(tr(Msg.ANN_LBL_X2), self.x2_spin)
        if ann.kind == "text":
            form.addRow(self.arrow_check)
        if ann.kind == "vline":
            form.addRow(self.link_check)
        form.addRow(self.locked_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def annotation(self) -> Annotation:
        a = copy.deepcopy(self._ann)
        a.text = self.text_edit.text()
        a.color = self.color_button.color or a.color
        a.font_size = self.font_spin.value()
        a.text_background = self.background_button.color
        a.opacity = self.opacity_spin.value()
        a.locked = self.locked_check.isChecked()
        a.arrow = self.arrow_check.isChecked()
        a.link_all = self.link_check.isChecked()
        a.x, a.y, a.x2 = self.x_spin.value(), self.y_spin.value(), self.x2_spin.value()
        if a.kind == "region" and a.x2 < a.x:
            a.x, a.x2 = a.x2, a.x
        return a


def edit_annotation(ann: Annotation, parent: QWidget | None) -> Annotation | None:
    dialog = AnnotationDialog(ann, parent)
    if dialog.exec() == AnnotationDialog.DialogCode.Accepted:
        return dialog.annotation()
    return None
