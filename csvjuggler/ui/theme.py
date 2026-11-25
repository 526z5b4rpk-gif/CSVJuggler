"""Look of the application: Fusion style, light palette, modern style sheet, icon.

The same look on every platform: Fusion with a fixed light palette (Windows' dark mode would
otherwise give dark panels around white graphs) and a flat style sheet: toggle switches
instead of check boxes, rounded fields and buttons, thin scroll bars. The switch and chevron
drawings are SVG files of ``ui/assets`` (package data).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

ACCENT = "#2f6fde"
WINDOWS_APP_ID = "CsvJuggler.CsvJuggler"
ASSETS = Path(__file__).parent / "assets"

STYLE_SHEET_TEMPLATE = """
* { outline: none; }
QMainWindow, QDialog { background: #f4f5f7; }
QMainWindow::separator { background: #f4f5f7; width: 5px; height: 5px; }
QMainWindow::separator:hover { background: #c9d6ec; }

QDockWidget { font-weight: 600; color: #3b4450; }
QDockWidget::title { background: #f4f5f7; padding: 6px 8px 4px 8px; text-align: left; }
QDockWidget > QWidget { font-weight: normal; color: #1d232b; }

QToolBar { background: transparent; border: none; spacing: 4px; padding: 3px 4px; }
QToolBar QToolButton {
    padding: 4px 10px; border: none; border-radius: 6px; color: #2b333d; background: transparent;
}
QToolBar QToolButton:hover { background: #e6ebf3; }
QToolBar QToolButton:pressed, QToolBar QToolButton:checked {
    background: #dce7fb; color: #1f4fae;
}
QToolBar QToolButton::menu-indicator { width: 0; }

QPushButton {
    padding: 5px 14px; border: 1px solid #d3d8df; border-radius: 6px; background: #ffffff;
    color: #1d232b;
}
QPushButton:hover { background: #f2f5fa; border-color: #b9c4d3; }
QPushButton:pressed { background: #e5ebf5; }
QPushButton:default { border-color: @ACCENT; }
QPushButton:disabled { color: #a3abb5; background: #f4f5f7; border-color: #e1e4e8; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    padding: 3px 8px; border: 1px solid #d3d8df; border-radius: 6px; background: #ffffff;
    selection-background-color: @ACCENT; min-height: 18px;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
    border-color: #b9c4d3;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid @ACCENT;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: #a3abb5; background: #f4f5f7; border-color: #e1e4e8;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(@ASSETS/chevron_down.svg); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: url(@ASSETS/chevron_down_disabled.svg); }
QComboBox QAbstractItemView {
    border: 1px solid #d3d8df; border-radius: 6px; background: #ffffff; padding: 4px;
    selection-background-color: #e6eefc; selection-color: #1d232b;
}
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 20px; border: none; background: transparent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: #eef2f8; border-radius: 4px;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(@ASSETS/chevron_up.svg); width: 10px; height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(@ASSETS/chevron_down.svg); width: 10px; height: 10px;
}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {
    image: url(@ASSETS/chevron_up_disabled.svg);
}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {
    image: url(@ASSETS/chevron_down_disabled.svg);
}

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 34px; height: 20px; }
QCheckBox::indicator:unchecked { image: url(@ASSETS/switch_off.svg); }
QCheckBox::indicator:unchecked:hover { image: url(@ASSETS/switch_off_hover.svg); }
QCheckBox::indicator:unchecked:disabled { image: url(@ASSETS/switch_off_disabled.svg); }
QCheckBox::indicator:checked { image: url(@ASSETS/switch_on.svg); }
QCheckBox::indicator:checked:hover { image: url(@ASSETS/switch_on_hover.svg); }
QCheckBox::indicator:checked:disabled { image: url(@ASSETS/switch_on_disabled.svg); }

QGroupBox {
    border: 1px solid #e1e4e8; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #3b4450; font-weight: 600;
}

QToolBox::tab {
    background: transparent; border: none; border-radius: 6px; padding: 2px 8px;
    min-height: 26px; font-weight: 600; color: #3b4450;
}
QToolBox::tab:hover { background: #e9edf3; }
QToolBox::tab:selected { background: #e6eefc; color: #1f4fae; }

QTabWidget::pane { border: 1px solid #e1e4e8; border-radius: 8px; background: #ffffff; top: -1px; }
QTabBar::tab {
    padding: 6px 14px; border: none; border-bottom: 2px solid transparent; color: #5b6573;
    background: transparent;
}
QTabBar::tab:selected { color: #1f4fae; border-bottom-color: @ACCENT; }
QTabBar::tab:hover { color: #1d232b; }

QTreeView, QListView, QListWidget, QTableView, QTableWidget {
    border: 1px solid #e1e4e8; border-radius: 8px; background: #ffffff;
    selection-background-color: #e6eefc; selection-color: #1d232b; gridline-color: #eef0f3;
}
QTreeView::item, QListWidget::item { padding: 3px 2px; border-radius: 4px; }
QTreeView::item:hover, QListWidget::item:hover { background: #f2f5fa; }
QTreeView::item:selected, QListWidget::item:selected { background: #e6eefc; color: #1d232b; }
QHeaderView::section {
    background: #ffffff; border: none; border-bottom: 1px solid #e1e4e8; padding: 5px 8px;
    color: #5b6573; font-weight: 600;
}
QTableCornerButton::section { background: #ffffff; border: none; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #c9cfd8; border-radius: 3px; min-height: 24px; min-width: 24px;
}
QScrollBar::handle:hover { background: #a9b2bf; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMenu {
    background: #ffffff; border: 1px solid #d3d8df; border-radius: 8px; padding: 4px;
}
QMenu::item { padding: 5px 22px 5px 22px; border-radius: 5px; }
QMenu::item:selected { background: #e6eefc; color: #1d232b; }
QMenu::item:disabled { color: #a3abb5; }
QMenu::separator { height: 1px; background: #e8ebef; margin: 4px 8px; }

QToolTip {
    background: #2b333d; color: #ffffff; border: none; border-radius: 6px; padding: 5px 8px;
}
QStatusBar { background: #f4f5f7; color: #5b6573; }
QStatusBar::item { border: none; }
"""


def style_sheet() -> str:
    """The style sheet with the asset paths and accent colour filled in."""
    return STYLE_SHEET_TEMPLATE.replace("@ASSETS", ASSETS.as_posix()).replace("@ACCENT", ACCENT)


def light_palette() -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f4f5f7",
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


def _icon_image(size: int) -> QImage:
    """The icon at ``size`` pixels, drawn on a 64-unit grid (simplified below 32 px)."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64
    small = size < 32

    def pt(x: float, y: float) -> QPointF:
        return QPointF(x * s, y * s)

    # Tile: rounded square, blue gradient, soft highlight at the top.
    tile = QRectF(2 * s, 2 * s, 60 * s, 60 * s)
    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0, QColor("#3a8ee6"))
    gradient.setColorAt(1, QColor("#16467f"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(tile, 14 * s, 14 * s)
    highlight = QLinearGradient(0, 2 * s, 0, 30 * s)
    highlight.setColorAt(0, QColor(255, 255, 255, 46))
    highlight.setColorAt(1, QColor(255, 255, 255, 0))
    painter.setBrush(highlight)
    painter.drawRoundedRect(tile, 14 * s, 14 * s)

    round_pen = (Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if not small:
        # Grid lines.
        painter.setPen(QPen(QColor(255, 255, 255, 38), max(1.0, 1.2 * s)))
        for y in (20, 32, 44):
            painter.drawLine(pt(10, y), pt(54, y))
        # Second curve (orange), behind the main one.
        second = QPainterPath(pt(10, 40))
        second.cubicTo(pt(20, 40), pt(22, 30), pt(31, 33))
        second.cubicTo(pt(40, 36), pt(44, 26), pt(54, 24))
        painter.setPen(QPen(QColor("#ffb347"), 2.8 * s, *round_pen))
        painter.drawPath(second)
    # Main curve (white).
    main = QPainterPath(pt(10, 46))
    main.cubicTo(pt(17, 46), pt(19, 18), pt(28, 18))
    main.cubicTo(pt(37, 18), pt(36, 38), pt(44, 38))
    main.cubicTo(pt(49, 38), pt(51, 30), pt(54, 28))
    painter.setPen(QPen(QColor("#ffffff"), (6.5 if small else 3.8) * s, *round_pen))
    painter.drawPath(main)
    if not small:
        # Playhead: dashed vertical line, a dot where it crosses the main curve.
        x = 40 * s
        painter.setPen(QPen(QColor(255, 255, 255, 170), 1.6 * s, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x, 12 * s), QPointF(x, 52 * s))
        t = next((k / 400 for k in range(401) if main.pointAtPercent(k / 400).x() >= x), 1.0)
        painter.setPen(QPen(QColor("#16467f"), 2 * s))
        painter.setBrush(QColor("#ffd166"))
        painter.drawEllipse(QPointF(x, main.pointAtPercent(t).y()), 4.2 * s, 4.2 * s)
    painter.end()
    return image


def app_icon() -> QIcon:
    """Curves on a blue tile with a playhead; drawn at run time (no image file to ship)."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256, 512):
        icon.addPixmap(QPixmap.fromImage(_icon_image(size)))
    return icon


def apply_theme(app: QApplication) -> None:
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))
        _set_windows_app_id()
    missing = [
        name for name in ("switch_on.svg", "chevron_down.svg") if not (ASSETS / name).is_file()
    ]
    if missing:
        log.warning("Theme assets missing in %s: %s", ASSETS, ", ".join(missing))
    app.setStyleSheet(style_sheet())


def _set_windows_app_id() -> None:
    """Own taskbar entry and icon (instead of Python's) on Windows."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        log.debug("Cannot set the Windows AppUserModelID: %s", exc)
