"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QPushButton, QWidget


class ColorButton(QPushButton):
    """Shows a colour; clicking opens a colour dialog. ``color`` may be ``None`` (default)."""

    color_changed = Signal(object)

    def __init__(
        self, color: str | None = None, allow_none: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._allow_none = allow_none
        self._color: str | None = None
        self.setMinimumWidth(80)
        self.clicked.connect(self._pick)
        self.set_color(color)

    @property
    def color(self) -> str | None:
        return self._color

    def set_color(self, color: str | None) -> None:
        self._color = color
        if color:
            text = "#000000" if QColor(color).lightness() > 128 else "#ffffff"
            self.setStyleSheet(f"background-color: {color}; color: {text};")
            self.setText(color)
        else:
            self.setStyleSheet("")
            self.setText("auto")
        self.color_changed.emit(color)

    def _pick(self) -> None:
        initial = QColor(self._color) if self._color else QColor("#000000")
        color = QColorDialog.getColor(initial, self)
        if color.isValid():
            self.set_color(color.name())


class DisposableDialog(QDialog):
    """Modal dialog destroyed once :meth:`exec` returns.

    Dialogs are created with the main window as parent; without this they would pile up
    under it until the application quits. The deletion is deferred, so the caller can still
    read the dialog's values right after ``exec()``.
    """

    def exec(self) -> int:
        result = super().exec()
        self.deleteLater()
        return result
