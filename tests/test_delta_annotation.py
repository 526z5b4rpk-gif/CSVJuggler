"""Δ annotations between two curve points."""

from __future__ import annotations

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
from csvjuggler.ui.annotation_items import DeltaAnnotationItem

SPEED = "run/speed"
TORQUE = "run/torque"
TIME = [0.0, 0.1, 0.2, 0.3, 0.4]
SPEED_Y = [0.0, 10.2, 20.5, 30.1, 40.0]
TORQUE_Y = [1.5, 1.6, 1.7, 1.65, 1.8]


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
    qtbot.wait(50)
    return w


def _item(window: MainWindow, ann_id: str) -> DeltaAnnotationItem:
    items = window.plot_docks[0].plot.annotation_layer.items_for(ann_id)
    assert len(items) == 1 and isinstance(items[0], DeltaAnnotationItem)
    return items[0]


def test_delta_json_roundtrip() -> None:
    a = Annotation(kind="delta", x=0.1, x2=0.3, series_id=SPEED, series_id_b=TORQUE)
    assert Annotation.from_dict(json.loads(json.dumps(a.to_dict()))) == a
    assert a.center_x == pytest.approx(0.2)


def test_delta_on_one_curve(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    lo, hi = dock.plot.x_range()
    ann = window.annotations.create_delta(dock.dock_id, dock.plot, 0, SPEED, 0.1)
    assert ann is not None and ann.series_id == ann.series_id_b == SPEED
    assert ann.x2 == pytest.approx(min(0.1 + 0.15 * (hi - lo), 0.4))
    item = _item(window, ann.id)
    dy = np.interp(ann.x2, TIME, SPEED_Y) - 10.2
    assert item.values["ya"] == pytest.approx(10.2)
    assert item.label_lines[0] == f"Δx = {ann.x2 - 0.1:.6g} s"
    assert item.label_lines[1].startswith("1/Δx = ")
    assert item.label_lines[2] == f"Δy = {dy:.6g}"  # the sample CSV has no units
    # The points are drawn where the curve is.
    view = dock.plot.subplots[0].view_box
    expected = view.mapViewToScene(QPointF(0.1, 10.2))
    actual = item.mapToScene(item._a)
    assert (actual.x(), actual.y()) == pytest.approx((expected.x(), expected.y()), abs=0.5)


def test_delta_between_curves_on_two_axes(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.plot.move_curve_to_axis(0, TORQUE, None)
    ann = window.annotations.create_delta(dock.dock_id, dock.plot, 0, SPEED, 0.1)
    window.annotations.set_delta_points(ann.id, SPEED, 0.1, TORQUE, 0.3)
    item = _item(window, ann.id)
    curve = dock.plot.config.subplots[0].curve(TORQUE)
    torque_view = dock.plot.subplots[0].view_for_axis(curve.axis_id)
    expected = torque_view.mapViewToScene(QPointF(0.3, 1.65))
    actual = item.mapToScene(item._b)
    assert actual.y() == pytest.approx(expected.y(), abs=0.5)
    # Zooming the secondary axis moves B with its curve.
    torque_view.setYRange(0, 5, padding=0)
    expected = torque_view.mapViewToScene(QPointF(0.3, 1.65))
    assert item.mapToScene(item._b).y() == pytest.approx(expected.y(), abs=0.5)


def test_drag_point_slides_and_snaps_to_another_curve(window: MainWindow, qtbot) -> None:
    dock = window.plot_docks[0]
    plot = dock.plot
    ann = window.annotations.create_delta(dock.dock_id, plot, 0, SPEED, 0.1)
    window.annotations.set_delta_points(ann.id, SPEED, 0.1, SPEED, 0.2)
    item = _item(window, ann.id)
    start = plot.mapFromScene(item.mapToScene(item._b))
    view = plot.subplots[0].view_box
    target = plot.mapFromScene(view.mapViewToScene(QPointF(0.3, 1.65)))  # on the torque curve
    del item
    viewport = plot.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 11):
        QTest.mouseMove(viewport, start + (target - start) * (step / 10))
        qtbot.wait(1)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    qtbot.waitUntil(lambda: window.session.annotations.get(ann.id).series_id_b == TORQUE)
    moved = window.session.annotations.get(ann.id)
    assert moved.x2 == pytest.approx(0.3, abs=0.01)
    assert (moved.series_id, moved.x) == (SPEED, pytest.approx(0.1))


def _drag_from(window: MainWindow, qtbot, start: QPoint, delta: QPoint) -> None:
    viewport = window.plot_docks[0].plot.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 6):
        QTest.mouseMove(viewport, start + delta * (step / 5))
        qtbot.wait(1)
    QTest.mouseRelease(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + delta
    )
    qtbot.wait(20)


def test_drag_label_moves_it_and_drag_line_pans(window: MainWindow, qtbot) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create_delta(dock.dock_id, dock.plot, 0, SPEED, 0.1)
    item = _item(window, ann.id)
    box_center = dock.plot.mapFromScene(item.mapToScene(item._box.center()))
    del item
    before = dock.plot.x_range()
    _drag_from(window, qtbot, box_center, QPoint(40, -60))
    qtbot.waitUntil(lambda: window.session.annotations.get(ann.id).label_dy != 0)
    moved = window.session.annotations.get(ann.id)
    assert (moved.label_dx, moved.label_dy) == pytest.approx((40, -60), abs=1.5)
    assert dock.plot.x_range() == pytest.approx(before)  # the view did not move
    item = _item(window, ann.id)
    assert item._leader is not None  # a leader line joins the moved label

    # Dragging a dimension line (not a point, not the label) still pans the view.
    middle = (item._a + QPointF(item._b.x(), item._a.y())) / 2
    start = dock.plot.mapFromScene(item.mapToScene(middle))
    del item
    _drag_from(window, qtbot, start, QPoint(50, 0))
    assert dock.plot.x_range() != pytest.approx(before)
    assert window.session.annotations.get(ann.id).x == pytest.approx(0.1)

    # « Replacer l'étiquette » puts it back.
    menu = window.annotations.build_annotation_menu(ann.id)
    next(a for a in menu.actions() if a.text() == "Replacer l'étiquette").trigger()
    assert _item(window, ann.id).label_offset.isNull()


def test_line_style(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create_delta(dock.dock_id, dock.plot, 0, SPEED, 0.1)
    assert ann.line_style == "solid"
    menu = window.annotations.build_annotation_menu(ann.id)
    style_menu = next(a.menu() for a in menu.actions() if a.text() == "Style des traits")
    assert [a.text() for a in style_menu.actions()] == ["Plein", "Tirets", "Pointillés"]
    next(a for a in style_menu.actions() if a.text() == "Pointillés").trigger()
    stored = window.session.annotations.get(ann.id)
    assert stored.line_style == "dot"
    assert Annotation.from_dict(json.loads(json.dumps(stored.to_dict()))) == stored


def test_delta_hidden_or_removed_with_its_curves(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create_delta(dock.dock_id, dock.plot, 0, SPEED, 0.1)
    window.annotations.set_delta_points(ann.id, SPEED, 0.1, TORQUE, 0.3)
    dock.plot.set_curve_visible(TORQUE, False)
    assert not _item(window, ann.id).isVisible()
    dock.plot.set_curve_visible(TORQUE, True)
    assert _item(window, ann.id).isVisible()
    dock.plot.remove_curve(TORQUE, 0)
    assert dock.plot.annotation_layer.items_for(ann.id) == []
    assert window.session.annotations.get(ann.id) is not None  # kept, shown again if re-added


def test_context_menu_offers_a_delta(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    on_curve = dock.plot.subplots[0].view_box.mapViewToScene(QPointF(0.2, 20.5))
    menu = dock.controller.build_plot_menu(0, on_curve)
    add_menu = next(a.menu() for a in menu.actions() if a.text() == "Ajouter une annotation")
    assert "Écart Δ sur « speed »" in [a.text() for a in add_menu.actions()]


def test_label_shows_the_chosen_values(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    m = window.annotations
    ann = m.create_delta(dock.dock_id, dock.plot, 0, SPEED, 0.1)
    window.annotations.set_delta_points(ann.id, SPEED, 0.1, SPEED, 0.3)
    assert [line.split(" =")[0] for line in _item(window, ann.id).label_lines] == [
        "Δx",
        "1/Δx",
        "Δy",
    ]
    m.toggle_flag(ann.id, "show_inv_dx")
    assert [line.split(" =")[0] for line in _item(window, ann.id).label_lines] == ["Δx", "Δy"]
    m.toggle_flag(ann.id, "show_dx")
    assert _item(window, ann.id).label_lines == ["Δy = 19.9"]
    stored = window.session.annotations.get(ann.id)
    assert (stored.show_dx, stored.show_inv_dx, stored.show_dy) == (False, False, True)
    assert Annotation.from_dict(json.loads(json.dumps(stored.to_dict()))) == stored

    # Nothing to show and no text: no label box, the dimension lines stay.
    m.toggle_flag(ann.id, "show_dy")
    item = _item(window, ann.id)
    assert item.label_lines == [] and item._box.isEmpty() and item.isVisible()
    # The text is still shown on its own.
    stored = window.session.annotations.get(ann.id)
    stored.text = "montée"
    window.session.annotations.update(stored)
    assert _item(window, ann.id).label_lines == ["montée"]


def test_context_menu_toggles_the_values(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create_delta(dock.dock_id, dock.plot, 0, SPEED, 0.1)
    menu = window.annotations.build_annotation_menu(ann.id)
    actions = {a.text(): a for a in menu.actions()}
    assert all(actions[t].isChecked() for t in ("Afficher Δx", "Afficher 1/Δx (fréquence)"))
    actions["Afficher Δy"].trigger()
    assert not window.session.annotations.get(ann.id).show_dy


def test_dialog_edits_the_values(qtbot) -> None:
    from csvjuggler.ui.dialogs.annotation_dialog import AnnotationDialog

    dialog = AnnotationDialog(Annotation(kind="delta", series_id=SPEED))
    qtbot.addWidget(dialog)
    assert dialog.dx_check.isVisibleTo(dialog) and dialog.dy_check.isVisibleTo(dialog)
    dialog.inv_dx_check.setChecked(False)
    dialog.line_style_combo.setCurrentIndex(dialog.line_style_combo.findData("dash"))
    result = dialog.annotation()
    assert (result.show_dx, result.show_inv_dx, result.show_dy) == (True, False, True)
    assert result.line_style == "dash"
    text_dialog = AnnotationDialog(Annotation(kind="text"))
    qtbot.addWidget(text_dialog)
    assert not text_dialog.dx_check.isVisibleTo(text_dialog)
    assert not text_dialog.line_style_combo.isVisibleTo(text_dialog)
