"""Detached graphs: own window, full screen, half screen, back into the main window."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session


@pytest.fixture
def window(qtbot, tmp_path: Path, data_dir: Path) -> MainWindow:
    csv = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", csv)
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    w.open_files([csv], interactive=False)
    w.plot_docks[0].plot.add_series(["run/speed"])
    return w


def test_detach_makes_a_real_window_and_attach_puts_it_back(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.detach()
    assert dock.detached and dock.isWindow() and dock.isVisible()
    flags = dock.windowFlags()
    assert flags & Qt.WindowType.WindowMaximizeButtonHint  # maximise / Windows snap
    assert flags & Qt.WindowType.WindowMinimizeButtonHint
    assert dock.plot.config.subplots[0].curves  # same graph, nothing rebuilt
    dock.attach()
    assert not dock.detached and not dock.isFloating() and not dock.isWindow()
    assert window.plot_area.dockWidgetArea(dock) != Qt.DockWidgetArea.NoDockWidgetArea


def test_full_screen_and_escape(window: MainWindow, qtbot) -> None:
    dock = window.plot_docks[0]
    dock.toggle_full_screen()  # detaches first
    assert dock.detached and dock.isFullScreen()
    dock._on_escape()
    assert not dock.isFullScreen() and dock.detached
    window.full_screen_current_plot()
    assert dock.isFullScreen()
    dock.toggle_full_screen()
    assert not dock.isFullScreen()


def test_half_screen(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.place_on_screen("left")
    area = (dock.screen() or QGuiApplication.primaryScreen()).availableGeometry()
    frame = dock.frameGeometry()
    assert frame.left() == area.left() and abs(frame.width() - area.width() // 2) <= 2
    dock.place_on_screen("right")
    frame = dock.frameGeometry()
    assert (
        abs(frame.right() - area.right()) <= 2
        and frame.left() >= area.left() + area.width() // 2 - 2
    )


def test_window_close_button_reattaches_and_menu_closes(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.detach()
    dock.close()  # the close button of the detached window
    assert window.plot_docks == [dock] and not dock.detached
    dock.detach()
    dock.close_plot()  # « Graphe ▾ → Fermer le graphe »
    assert window.plot_docks == []


def test_window_menu_entries(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock._fill_window_menu()
    texts = [a.text() for a in dock.window_menu.actions()]
    assert texts[0] == "Détacher dans une fenêtre"
    assert "Moitié gauche de l'écran" in texts and "Moitié droite de l'écran" in texts
    dock.detach()
    dock._fill_window_menu()
    assert dock.window_menu.actions()[0].text() == "Rattacher à la fenêtre principale"


def test_detached_graph_survives_a_project_round_trip(window: MainWindow, tmp_path: Path) -> None:
    dock = window.plot_docks[0]
    dock.detach()
    path = window.save_layout(tmp_path / "p")
    window.load_layout(path, interactive=False)
    restored = window.plot_docks[0]
    assert restored.dock_id == dock.dock_id
    assert restored.detached  # in its own window again
    assert not window.is_modified()


def test_closing_the_main_window_hides_detached_graphs(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.detach()
    assert window.close()
    assert not dock.isVisible()
