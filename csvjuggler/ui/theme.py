"""Look of the application: Fusion style, light or dark palette, flat style sheet, icon.

The same look on every platform: Fusion with our own light or dark palette (« Système »
follows the OS colour scheme; with Fusion alone, Windows' dark mode would give dark panels
around white graphs) and a flat style sheet built from colour tokens (``UI_COLORS``):
toggle switches instead of check boxes, rounded fields and buttons, thin scroll bars. The
switch and chevron drawings are SVG files of ``ui/assets`` (package data), with ``_dark``
variants. Graphs follow the theme through pyqtgraph's default colours (``plot_colors``).
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
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

WINDOWS_APP_ID = "CsvJuggler.CsvJuggler"
ASSETS = Path(__file__).parent / "assets"

STYLE_SHEET_TEMPLATE = """
* { outline: none; }
QMainWindow, QDialog { background: @BG; }
QMainWindow::separator { background: @BG; width: 5px; height: 5px; }
QMainWindow::separator:hover { background: @SEPARATOR_HOVER; }

QDockWidget { font-weight: 600; color: @HEADING; }
QDockWidget::title { background: @BG; padding: 6px 8px 4px 8px; text-align: left; }
QDockWidget > QWidget { font-weight: normal; color: @TEXT; }

QToolBar { background: transparent; border: none; spacing: 4px; padding: 3px 4px; }
QToolBar QToolButton {
    padding: 4px 10px; border: none; border-radius: 6px; color: @TEXT; background: transparent;
}
QToolBar QToolButton:hover { background: @HOVER; }
QToolBar QToolButton:pressed, QToolBar QToolButton:checked {
    background: @SELECTED; color: @ACCENT_TEXT;
}
QToolBar QToolButton::menu-indicator { width: 0; }

QPushButton {
    padding: 5px 14px; border: 1px solid @BORDER; border-radius: 6px; background: @SURFACE;
    color: @TEXT;
}
QPushButton:hover { background: @HOVER_SURFACE; border-color: @BORDER_HOVER; }
QPushButton:pressed { background: @PRESSED; }
QPushButton:default { border-color: @ACCENT; }
QPushButton:disabled { color: @DISABLED_TEXT; background: @BG; border-color: @BORDER_LIGHT; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    padding: 3px 8px; border: 1px solid @BORDER; border-radius: 6px; background: @SURFACE;
    selection-background-color: @ACCENT; min-height: 18px;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
    border-color: @BORDER_HOVER;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid @ACCENT;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: @DISABLED_TEXT; background: @BG; border-color: @BORDER_LIGHT;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(@ASSETS/chevron_down@SUFFIX.svg); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: url(@ASSETS/chevron_down_disabled@SUFFIX.svg); }
QComboBox QAbstractItemView {
    border: 1px solid @BORDER; border-radius: 6px; background: @SURFACE; padding: 4px;
    selection-background-color: @SELECTED; selection-color: @TEXT;
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
    background: @HOVER; border-radius: 4px;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(@ASSETS/chevron_up@SUFFIX.svg); width: 10px; height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(@ASSETS/chevron_down@SUFFIX.svg); width: 10px; height: 10px;
}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {
    image: url(@ASSETS/chevron_up_disabled@SUFFIX.svg);
}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {
    image: url(@ASSETS/chevron_down_disabled@SUFFIX.svg);
}

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 34px; height: 20px; }
QCheckBox::indicator:unchecked { image: url(@ASSETS/switch_off@SUFFIX.svg); }
QCheckBox::indicator:unchecked:hover { image: url(@ASSETS/switch_off_hover@SUFFIX.svg); }
QCheckBox::indicator:unchecked:disabled { image: url(@ASSETS/switch_off_disabled@SUFFIX.svg); }
QCheckBox::indicator:checked { image: url(@ASSETS/switch_on@SUFFIX.svg); }
QCheckBox::indicator:checked:hover { image: url(@ASSETS/switch_on_hover@SUFFIX.svg); }
QCheckBox::indicator:checked:disabled { image: url(@ASSETS/switch_on_disabled@SUFFIX.svg); }

QGroupBox {
    border: 1px solid @BORDER_LIGHT; border-radius: 8px; margin-top: 14px;
    padding: 10px 8px 8px 8px;
    background: @SURFACE;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: @HEADING; font-weight: 600;
}

QToolBox::tab {
    background: transparent; border: none; border-radius: 6px; padding: 2px 8px;
    min-height: 26px; font-weight: 600; color: @HEADING;
}
QToolBox::tab:hover { background: @HOVER; }
QToolBox::tab:selected { background: @SELECTED; color: @ACCENT_TEXT; }

QTabWidget::pane {
    border: 1px solid @BORDER_LIGHT; border-radius: 8px; background: @SURFACE; top: -1px;
}
QTabBar::tab {
    padding: 6px 14px; border: none; border-bottom: 2px solid transparent; color: @MUTED;
    background: transparent;
}
QTabBar::tab:selected { color: @ACCENT_TEXT; border-bottom-color: @ACCENT; }
QTabBar::tab:hover { color: @TEXT; }

QTreeView, QListView, QListWidget, QTableView, QTableWidget {
    border: 1px solid @BORDER_LIGHT; border-radius: 8px; background: @SURFACE;
    selection-background-color: @SELECTED; selection-color: @TEXT; gridline-color: @BORDER_LIGHT;
}
QTreeView::item, QListWidget::item { padding: 3px 2px; border-radius: 4px; }
QTreeView::item:hover, QListWidget::item:hover { background: @HOVER_SURFACE; }
QTreeView::item:selected, QListWidget::item:selected { background: @SELECTED; color: @TEXT; }
QHeaderView::section {
    background: @SURFACE; border: none; border-bottom: 1px solid @BORDER_LIGHT; padding: 5px 8px;
    color: @MUTED; font-weight: 600;
}
QTableCornerButton::section { background: @SURFACE; border: none; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: @SCROLL; border-radius: 3px; min-height: 24px; min-width: 24px;
}
QScrollBar::handle:hover { background: @SCROLL_HOVER; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMenu {
    background: @SURFACE; border: 1px solid @BORDER; border-radius: 8px; padding: 4px;
}
QMenu::item { padding: 5px 22px 5px 22px; border-radius: 5px; }
QMenu::item:selected { background: @SELECTED; color: @TEXT; }
QMenu::item:disabled { color: @DISABLED_TEXT; }
QMenu::separator { height: 1px; background: @BORDER_LIGHT; margin: 4px 8px; }

QToolTip {
    background: @TOOLTIP_BG; color: @TOOLTIP_TEXT; border: none; border-radius: 6px;
    padding: 5px 8px;
}
QStatusBar { background: @BG; color: @MUTED; }
QStatusBar::item { border: none; }
"""


UI_COLORS: dict[str, dict[str, str]] = {
    "light": {
        "BG": "#f4f5f7", "SURFACE": "#ffffff", "TEXT": "#1d232b", "HEADING": "#3b4450",
        "MUTED": "#5b6573", "BORDER": "#d3d8df", "BORDER_LIGHT": "#e1e4e8",
        "BORDER_HOVER": "#b9c4d3", "HOVER": "#e6ebf3", "HOVER_SURFACE": "#f2f5fa",
        "PRESSED": "#e5ebf5", "SELECTED": "#e6eefc", "ACCENT_TEXT": "#1f4fae",
        "DISABLED_TEXT": "#a3abb5", "SEPARATOR_HOVER": "#c9d6ec", "SCROLL": "#c9cfd8",
        "SCROLL_HOVER": "#a9b2bf", "TOOLTIP_BG": "#2b333d", "TOOLTIP_TEXT": "#ffffff",
        "ACCENT": "#2f6fde", "SUFFIX": "",
    },
    "dark": {
        "BG": "#1b1e23", "SURFACE": "#23272e", "TEXT": "#e3e6ea", "HEADING": "#b8c0ca",
        "MUTED": "#8f99a5", "BORDER": "#3a4049", "BORDER_LIGHT": "#30353d",
        "BORDER_HOVER": "#4b535e", "HOVER": "#2c323a", "HOVER_SURFACE": "#2a2f37",
        "PRESSED": "#333a44", "SELECTED": "#24395c", "ACCENT_TEXT": "#8fb4ff",
        "DISABLED_TEXT": "#6b737d", "SEPARATOR_HOVER": "#3b5a8c", "SCROLL": "#454c56",
        "SCROLL_HOVER": "#5a626d", "TOOLTIP_BG": "#e3e6ea", "TOOLTIP_TEXT": "#1b1e23",
        "ACCENT": "#3b7cf0", "SUFFIX": "_dark",
    },
}  # fmt: skip


@dataclass(frozen=True)
class PlotColors:
    background: str
    foreground: str
    """Axes, grid, tick labels, legend and title text."""
    label_fill: tuple[int, int, int, int]
    label_text: str
    """Value labels of the cursors (tracker, playhead)."""


PLOT_COLORS = {
    "light": PlotColors("#ffffff", "#000000", (255, 255, 255, 220), "#000000"),
    "dark": PlotColors("#1e2228", "#c9ced6", (35, 39, 46, 225), "#e3e6ea"),
}
DEFAULT_PLOT_BACKGROUNDS = {"#ffffff", "white", "w", ""}
"""A graph background left at one of these follows the theme (custom colours are kept)."""

ThemeMode = Literal["light", "dark", "system"]
_current = "light"
"""Resolved theme in use: ``light`` or ``dark``."""


def current_theme() -> str:
    return _current


def plot_colors() -> PlotColors:
    return PLOT_COLORS[_current]


def effective_background(background: str) -> str:
    """Background actually drawn for a graph whose configured background is ``background``."""
    if background.strip().lower() in DEFAULT_PLOT_BACKGROUNDS:
        return plot_colors().background
    return background


def resolve(mode: str) -> str:
    """``light`` / ``dark`` for a mode; ``system`` follows the OS colour scheme."""
    if mode in ("light", "dark"):
        return mode
    hints = QGuiApplication.styleHints() if QGuiApplication.instance() else None
    if hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark:
        return "dark"
    return "light"


def style_sheet(theme: str = "light") -> str:
    """The style sheet for ``theme`` with colours and asset paths filled in."""
    sheet = STYLE_SHEET_TEMPLATE.replace("@ASSETS", ASSETS.as_posix())
    for name, value in sorted(UI_COLORS[theme].items(), key=lambda kv: -len(kv[0])):
        sheet = sheet.replace(f"@{name}", value)
    return sheet


def palette(theme: str = "light") -> QPalette:
    c = UI_COLORS[theme]
    result = QPalette()
    colors = {
        QPalette.ColorRole.Window: c["BG"],
        QPalette.ColorRole.WindowText: c["TEXT"],
        QPalette.ColorRole.Base: c["SURFACE"],
        QPalette.ColorRole.AlternateBase: c["HOVER_SURFACE"],
        QPalette.ColorRole.ToolTipBase: c["TOOLTIP_BG"],
        QPalette.ColorRole.ToolTipText: c["TOOLTIP_TEXT"],
        QPalette.ColorRole.Text: c["TEXT"],
        QPalette.ColorRole.Button: c["SURFACE"],
        QPalette.ColorRole.ButtonText: c["TEXT"],
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: c["ACCENT"],
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: c["ACCENT"],
        QPalette.ColorRole.PlaceholderText: c["MUTED"],
        QPalette.ColorRole.Mid: c["BORDER"],
        QPalette.ColorRole.Midlight: c["BORDER_LIGHT"],
    }
    for role, color in colors.items():
        result.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):  # fmt: skip
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["DISABLED_TEXT"]))
    return result


def light_palette() -> QPalette:
    return palette("light")


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


def apply_theme(app: QApplication, mode: str = "light") -> str:
    """Apply ``mode`` (``light``, ``dark`` or ``system``); returns the resolved theme.

    Also sets pyqtgraph's default colours (used by axes, grid, legends, titles). Graphs
    already shown must re-apply their config to pick the new colours.
    """
    global _current
    _current = resolve(mode)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setPalette(palette(_current))
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))
        _set_windows_app_id()
    missing = [n for n in ("switch_on.svg", "switch_on_dark.svg") if not (ASSETS / n).is_file()]
    if missing:
        log.warning("Theme assets missing in %s: %s", ASSETS, ", ".join(missing))
    app.setStyleSheet(style_sheet(_current))
    colors = plot_colors()
    pg.setConfigOptions(background=colors.background, foreground=colors.foreground)
    return _current


def _set_windows_app_id() -> None:
    """Own taskbar entry and icon (instead of Python's) on Windows."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        log.debug("Cannot set the Windows AppUserModelID: %s", exc)
