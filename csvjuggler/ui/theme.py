"""Look of the application: Fusion style with a light palette, a light style sheet, an icon.

The native Windows style looks dated and, with Windows' dark mode, would give dark panels
around white graphs. Windows and Linux therefore use Fusion with a fixed light palette; macOS
keeps its native style (only the small graph toolbars get the style sheet).
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

ACCENT = "#1f77b4"
WINDOWS_APP_ID = "CsvJuggler.CsvJuggler"

STYLE_SHEET = """
QMainWindow::separator { background: #dde2e8; width: 4px; height: 4px; }
QMainWindow::separator:hover { background: #9fb8d6; }
QDockWidget::title {
    background: #eceff3; padding: 4px 6px; border-bottom: 1px solid #d5dae1;
}
QToolBar { background: transparent; border: none; spacing: 2px; padding: 1px 2px; }
QToolBar QToolButton { padding: 3px 7px; border: 1px solid transparent; border-radius: 4px; }
QToolBar QToolButton:hover { background: #e4ecf6; border-color: #c6d6ea; }
QToolBar QToolButton:pressed, QToolBar QToolButton:checked {
    background: #d3e2f4; border-color: #9fb8d6;
}
QToolBar QToolButton::menu-indicator { subcontrol-position: right center; width: 0; }
QPushButton {
    padding: 4px 10px; border: 1px solid #c4cad3; border-radius: 4px; background: #fbfcfd;
}
QPushButton:hover { background: #eef3f9; border-color: #9fb8d6; }
QPushButton:pressed { background: #dfe8f3; }
QPushButton:disabled { color: #9aa3ad; background: #f3f4f6; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    padding: 2px 4px; border: 1px solid #c4cad3; border-radius: 3px; background: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #1f77b4;
}
QToolBox::tab {
    background: #eceff3; border: 1px solid #d5dae1; border-radius: 4px; padding: 4px 8px;
    font-weight: 600;
}
QToolBox::tab:selected { background: #dbe6f3; border-color: #9fb8d6; }
QHeaderView::section {
    background: #eceff3; border: none; border-right: 1px solid #d5dae1;
    border-bottom: 1px solid #d5dae1; padding: 3px 6px;
}
QTreeView, QListWidget, QTableWidget { border: 1px solid #d5dae1; }
QTreeView::item, QListWidget::item { padding: 2px 0; }
QStatusBar { background: #f3f5f8; border-top: 1px solid #d5dae1; }
"""

MAC_STYLE_SHEET = """
QToolBar { border: none; spacing: 2px; padding: 1px 2px; }
QToolBar QToolButton { padding: 2px 6px; border-radius: 4px; }
QToolBar QToolButton:hover { background: #e4ecf6; }
QToolBar QToolButton:checked { background: #d3e2f4; }
"""


def light_palette() -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f5f6f8",
        QPalette.ColorRole.WindowText: "#1d232b",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#eef1f5",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#1d232b",
        QPalette.ColorRole.Text: "#1d232b",
        QPalette.ColorRole.Button: "#f5f6f8",
        QPalette.ColorRole.ButtonText: "#1d232b",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: ACCENT,
        QPalette.ColorRole.PlaceholderText: "#8a929c",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):  # fmt: skip
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#9aa3ad"))
    return palette


def app_icon() -> QIcon:
    """A small chart drawn at run time (no image file to ship)."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 32
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(QRectF(1 * s, 1 * s, 30 * s, 30 * s), 6 * s, 6 * s)
        path = QPainterPath(QPointF(5 * s, 22 * s))
        for x, y in ((10, 14), (15, 18), (21, 8), (27, 12)):
            path.lineTo(QPointF(x * s, y * s))
        painter.setPen(QPen(QColor("#ffffff"), max(1.0, 2.6 * s)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#ffd27f"), max(1.0, 1.6 * s)))
        painter.drawLine(QPointF(5 * s, 26 * s), QPointF(27 * s, 26 * s))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def apply_theme(app: QApplication) -> None:
    app.setWindowIcon(app_icon())
    if sys.platform == "darwin":
        app.setStyleSheet(MAC_STYLE_SHEET)
        return
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))
        _set_windows_app_id()
    app.setStyleSheet(STYLE_SHEET)


def _set_windows_app_id() -> None:
    """Own taskbar entry and icon (instead of Python's) on Windows."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        log.debug("Cannot set the Windows AppUserModelID: %s", exc)
