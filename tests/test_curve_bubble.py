"""Bubble annotations attached to a curve."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from csvjuggler.main_window import MainWindow
from csvjuggler.model.annotation import Annotation
from csvjuggler.model.session import Session
from csvjuggler.ui.annotation_items import BubbleAnnotationItem

SPEED = "run/speed"
TORQUE = "run/torque"


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
    w.plot_docks[0].plot.add_series([SPEED, TORQUE])
    w.plot_docks[0].plot.auto_range()
    qtbot.wait(50)  # let the view settle: dragging computes pixels from the current range
    return w


def _item(window: MainWindow, ann_id: str) -> BubbleAnnotationItem:
    items = window.plot_docks[0].plot.annotation_layer.items_for(ann_id)
    assert len(items) == 1 and isinstance(items[0], BubbleAnnotationItem)
    return items[0]


def _drag(window: MainWindow, qtbot, ann_id: str, local: QPointF, delta: QPoint) -> None:
    plot = window.plot_docks[0].plot
    item = _item(window, ann_id)
    start = plot.mapFromScene(item.mapToScene(local))
    del item  # the layer must be the only owner (the item is rebuilt after the drag)
    viewport = plot.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 11):
        QTest.mouseMove(viewport, start + delta * (step / 10))
        qtbot.wait(1)
    QTest.mouseRelease(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + delta
    )
    qtbot.wait(20)


def test_bubble_json_roundtrip() -> None:
    a = Annotation(kind="bubble", x=1.5, series_id="run/speed", offset_x=-40, offset_y=12)
    assert Annotation.from_dict(json.loads(json.dumps(a.to_dict()))) == a


def test_bubble_point_is_on_the_curve(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create_bubble(dock.dock_id, dock.plot, 0, SPEED, 0.25)
    assert ann is not None and ann.text == "speed" and ann.series_id == SPEED
    item = _item(window, ann.id)
    expected = float(np.interp(0.25, [0.2, 0.3], [20.5, 30.1]))
    assert item.point == pytest.approx((0.25, expected))
    assert item.pos().y() == pytest.approx(expected) and item.isVisible()
    assert "y = 25.3" in item.coords_line

    # The point follows the displayed curve (gain/offset).
    curve = copy.deepcopy(dock.plot.config.subplots[0].curve(SPEED))
    curve.gain, curve.offset = 2.0, 1.0
    dock.plot.set_curve_config(0, curve)
    assert _item(window, ann.id).point[1] == pytest.approx(2 * expected + 1)

    # Hidden curve → hidden bubble; removed curve → no bubble.
    dock.plot.set_curve_visible(SPEED, False)
    assert not _item(window, ann.id).isVisible()
    dock.plot.remove_curve(SPEED, 0)
    assert dock.plot.annotation_layer.items_for(ann.id) == []


def test_bubble_on_secondary_axis_is_drawn_above_the_plot(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.plot.move_curve_to_axis(0, TORQUE, None)
    sub = dock.plot.subplots[0]
    curve = dock.plot.config.subplots[0].curve(TORQUE)
    ann = window.annotations.create_bubble(dock.dock_id, dock.plot, 0, TORQUE, 0.15)
    item = _item(window, ann.id)
    assert item.getViewBox() is sub.view_box  # main view: above grid and other curves
    data_view = sub.view_for_axis(curve.axis_id)
    assert data_view is not sub.view_box
    y = float(np.interp(0.15, [0.1, 0.2], [1.6, 1.7]))
    expected = data_view.mapViewToScene(QPointF(0.15, y))
    assert item.mapToScene(QPointF(0, 0)).y() == pytest.approx(expected.y(), abs=0.5)
    # Zooming the secondary axis keeps the point on the curve.
    data_view.setYRange(0, 10, padding=0)
    expected = data_view.mapViewToScene(QPointF(0.15, y))
    assert item.mapToScene(QPointF(0, 0)).y() == pytest.approx(expected.y(), abs=0.5)


def test_drag_bubble_keeps_point_and_drag_point_slides(window: MainWindow, qtbot) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create_bubble(dock.dock_id, dock.plot, 0, SPEED, 0.15)
    center = _item(window, ann.id).box.center()
    _drag(window, qtbot, ann.id, center, QPoint(60, -30))
    moved = window.session.annotations.get(ann.id)
    assert moved.x == pytest.approx(0.15)
    assert (moved.offset_x, moved.offset_y) == pytest.approx((24 + 60, -36 - 30), abs=1.5)

    _drag(window, qtbot, ann.id, QPointF(0, 0), QPoint(150, 0))
    slid = window.session.annotations.get(ann.id)
    assert slid.x > 0.2
    assert slid.y == pytest.approx(
        float(np.interp(slid.x, [0.0, 0.1, 0.2, 0.3, 0.4], [0.0, 10.2, 20.5, 30.1, 40.0]))
    )
    assert (slid.offset_x, slid.offset_y) == (moved.offset_x, moved.offset_y)


def test_context_menu_offers_a_bubble_on_the_curve(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    view = dock.plot.subplots[0].view_box
    on_curve = view.mapViewToScene(QPointF(0.2, 20.5))
    menu = dock.controller.build_plot_menu(0, on_curve)
    add_menu = next(a.menu() for a in menu.actions() if a.text() == "Ajouter une annotation")
    labels = [a.text() for a in add_menu.actions()]
    assert "Bulle sur « speed »" in labels
    away = view.mapViewToScene(QPointF(0.2, 1000.0))
    menu = dock.controller.build_plot_menu(0, away)
    add_menu = next(a.menu() for a in menu.actions() if a.text() == "Ajouter une annotation")
    bubble = next(a for a in add_menu.actions() if a.text() == "Bulle sur une courbe")
    assert [a.text() for a in bubble.menu().actions()] == ["speed", "torque"]
