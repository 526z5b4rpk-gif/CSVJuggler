from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt

from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session


@pytest.fixture
def window(qtbot, data_dir: Path) -> MainWindow:
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    qtbot.waitExposed(w)
    w.open_files([data_dir / "simple_comma.csv"], interactive=False)
    w.plot_docks[0].plot.add_series(["simple_comma/speed"])
    return w


def test_split_right_and_down_positions(window: MainWindow, qtbot) -> None:
    first = window.plot_docks[0]
    right = window.split_plot(first, Qt.Orientation.Horizontal)
    below = window.split_plot(right, Qt.Orientation.Vertical)
    qtbot.wait(50)
    g0, g1, g2 = (d.geometry() for d in (first, right, below))
    assert g1.left() >= g0.right()  # right of the first one
    assert abs(g1.top() - g0.top()) < 5
    assert g2.top() >= g1.bottom()  # below the right one
    assert abs(g2.left() - g1.left()) < 5
    assert window.current_dock is below


def test_split_keeps_x_sync(window: MainWindow) -> None:
    first = window.plot_docks[0]
    first.plot.subplots[0].view_box.setXRange(0.1, 0.2, padding=0)
    right = window.split_plot(first, Qt.Orientation.Horizontal)
    assert right.plot.x_range() == pytest.approx((0.1, 0.2))  # starts on the same range
    right.plot.add_series(["simple_comma/torque"])
    right.plot.subplots[0].view_box.setXRange(0.05, 0.3, padding=0)
    assert first.plot.x_range() == pytest.approx((0.05, 0.3))


def test_split_of_unsynced_graph_creates_a_group(window: MainWindow) -> None:
    first = window.plot_docks[0]
    other = window.new_plot()  # global group, must stay independent
    first.plot.set_sync_group("")
    right = window.split_plot(first, Qt.Orientation.Horizontal)
    assert first.plot.config.sync_group == right.plot.config.sync_group == "groupe 1"
    first.plot.subplots[0].view_box.setXRange(0.1, 0.15, padding=0)
    assert right.plot.x_range() == pytest.approx((0.1, 0.15))
    assert other.plot.x_range() != pytest.approx((0.1, 0.15))


def test_split_from_toolbar_and_context_menu(window: MainWindow) -> None:
    first = window.plot_docks[0]
    texts = [a.text() for a in first.toolbar.actions()]
    assert "Diviser ↔" in texts and "Diviser ↕" in texts and "+ Sous-graphe" in texts
    next(a for a in first.toolbar.actions() if a.text() == "Diviser ↕").trigger()
    assert len(window.plot_docks) == 2
    menu = first.controller.build_plot_menu(0, QPointF(10, 10))
    next(a for a in menu.actions() if a.text().startswith("Diviser la zone à droite")).trigger()
    assert len(window.plot_docks) == 3


def test_measure_panel_follows_synced_range(window: MainWindow, qtbot) -> None:
    first = window.plot_docks[0]
    right = window.split_plot(first, Qt.Orientation.Horizontal)
    right.plot.add_series(["simple_comma/torque"])
    assert window.measure_panel.dock is right
    first.plot.subplots[0].view_box.setXRange(0.15, 0.35, padding=0)  # right follows by sync
    qtbot.waitUntil(lambda: window.measure_panel.table.item(0, 10).text() == "2", timeout=2000)
