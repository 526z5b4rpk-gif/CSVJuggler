from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent

from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session
from csvjuggler.ui.series_tree import encode_series_ids


@pytest.fixture
def window(qtbot, data_dir: Path) -> MainWindow:
    session = Session()
    session.load_csv(data_dir / "simple_comma.csv")
    w = MainWindow(session)
    qtbot.addWidget(w)
    w.resize(1000, 800)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_new_plot_close_and_close_all(window: MainWindow) -> None:
    window.new_plot()
    window.new_plot()
    assert len(window.plot_docks) == 3
    assert len({d.dock_id for d in window.plot_docks}) == 3
    window.plot_docks[1].close()
    assert len(window.plot_docks) == 2
    window.tile_plots()
    window.close_all_plots()
    assert window.plot_docks == []
    assert window.current_dock is None


def test_x_sync_global_and_disabled(window: MainWindow) -> None:
    a = window.plot_docks[0].plot
    b = window.new_plot().plot
    c = window.new_plot().plot
    for p in (a, b, c):
        p.add_series(["simple_comma/speed"])
    c.config.sync_group = ""
    a.subplots[0].view_box.setXRange(0.1, 0.2, padding=0)
    assert b.x_range() == pytest.approx((0.1, 0.2))
    assert c.x_range() != pytest.approx((0.1, 0.2))


def test_split_drop_into_second_subplot(window: MainWindow, qtbot) -> None:
    plot = window.plot_docks[0].plot
    plot.split()
    assert len(plot.subplots) == 2
    qtbot.wait(50)
    rect = plot.subplots[1].plot_item.sceneBoundingRect()
    view_pos = plot.mapFromScene(rect.center())
    mime: QMimeData = encode_series_ids(["simple_comma/torque"])
    event = QDropEvent(
        QPointF(view_pos),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    plot.dropEvent(event)
    assert [c.series_id for c in plot.config.subplots[1].curves] == ["simple_comma/torque"]
    assert plot.config.subplots[0].curves == []
    # X axes of subplots are linked.
    plot.subplots[1].view_box.setXRange(1, 2, padding=0)
    assert plot.x_range() == pytest.approx((1, 2))
    plot.remove_subplot(1)
    assert len(plot.subplots) == 1


def test_legend_click_visibility_updates_config(window: MainWindow) -> None:
    plot = window.plot_docks[0].plot
    plot.add_series(["simple_comma/speed"])
    events: list[int] = []
    plot.config_changed.connect(lambda: events.append(1))
    plot.curve_item("simple_comma/speed").setVisible(False)  # what a legend click does
    assert plot.config.all_curves()[0].visible is False
    assert events


def test_rename_dock(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.rename("Vitesse")
    assert dock.windowTitle() == "Vitesse"
