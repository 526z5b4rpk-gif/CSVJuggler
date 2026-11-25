"""Dark theme: style sheet, palette, graphs and the Fenêtre → Thème menu."""

from __future__ import annotations

import shutil
from pathlib import Path

import pyqtgraph as pg
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from csvjuggler.main_window import KEY_THEME, MainWindow
from csvjuggler.model.session import Session
from csvjuggler.ui import theme


@pytest.fixture
def restore_look(qapp: QApplication):
    """The theme is application-wide: give the other tests their usual look back."""
    style, sheet, palette = qapp.style().name(), qapp.styleSheet(), qapp.palette()
    background, foreground = pg.getConfigOption("background"), pg.getConfigOption("foreground")
    yield
    qapp.setStyle(style)
    qapp.setStyleSheet(sheet)
    qapp.setPalette(palette)
    pg.setConfigOptions(background=background, foreground=foreground)
    theme._current = "light"


def test_dark_style_sheet_uses_dark_assets_and_colours() -> None:
    sheet = theme.style_sheet("dark")
    assert "switch_on_dark.svg" in sheet and "@" not in sheet.replace("@media", "")
    assert theme.UI_COLORS["dark"]["SURFACE"] in sheet
    assert "switch_on.svg)" in theme.style_sheet("light")
    for name in ("switch_on", "switch_off", "chevron_down", "chevron_up"):
        assert (theme.ASSETS / f"{name}_dark.svg").is_file()


def test_default_graph_background_follows_the_theme(restore_look, qapp) -> None:
    theme.apply_theme(qapp, "dark")
    assert theme.effective_background("#ffffff") == theme.PLOT_COLORS["dark"].background
    assert theme.effective_background("#ffeedd") == "#ffeedd"  # custom colour kept
    assert pg.getConfigOption("foreground") == theme.PLOT_COLORS["dark"].foreground
    theme.apply_theme(qapp, "light")
    assert theme.effective_background("#ffffff") == "#ffffff"


def test_theme_menu_switches_and_remembers(
    restore_look, qtbot, tmp_path: Path, data_dir: Path
) -> None:
    csv = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", csv)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(Session(), settings)
    qtbot.addWidget(w)
    w.open_files([csv], interactive=False)
    plot = w.plot_docks[0].plot
    plot.add_series(["run/speed"])
    w.time_bar.set_position(0.2)
    dark = next(a for a in w.theme_actions.actions() if a.data() == "dark")
    dark.trigger()
    assert settings.value(KEY_THEME) == "dark" and dark.isChecked()
    assert theme.current_theme() == "dark"
    assert plot.backgroundBrush().color().name() == theme.PLOT_COLORS["dark"].background
    assert plot.config.background == "#ffffff"  # the saved config is unchanged
    label = w.plot_docks[0].playhead._items[0][1]
    assert label.color.name() == theme.PLOT_COLORS["dark"].label_text
    w.set_theme("light")
    assert plot.backgroundBrush().color().name() == "#ffffff"
    assert w.theme_mode() == "light"
