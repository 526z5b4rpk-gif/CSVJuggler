"""Secondary Y axes on the left of the graph."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent

from csvjuggler.model.plot_config import PlotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.multi_axis import AXIS_ROW
from csvjuggler.ui.plot_menus import PlotController
from csvjuggler.ui.plot_widget import PlotWidget
from csvjuggler.ui.series_tree import encode_series_ids

SPEED = "simple_comma/speed"
TORQUE = "simple_comma/torque"
STATUS = "simple_comma/status"


@pytest.fixture
def plot(qtbot, data_dir: Path) -> PlotWidget:
    session = Session()
    session.load_csv(data_dir / "simple_comma.csv")
    widget = PlotWidget(session)
    qtbot.addWidget(widget)
    widget.resize(900, 600)
    widget.show()
    qtbot.waitExposed(widget)
    widget.add_series([SPEED, TORQUE])
    return widget


def _cell(plot: PlotWidget, col: int, row: int = AXIS_ROW):
    return plot.subplots[0].plot_item.layout.itemAt(row, col)


def test_left_axis_is_placed_before_the_primary_axis(plot: PlotWidget, qtbot) -> None:
    sub = plot.subplots[0]
    axis_id = plot.move_curve_to_axis(0, TORQUE, None, side="left")
    assert plot.config.subplots[0].axis(axis_id).side == "left"
    axis = sub.axis_item(axis_id)
    assert axis.orientation == "left"
    # Grid: [left secondary][primary axis][view] …
    assert _cell(plot, 0) is axis
    assert _cell(plot, 1) is sub.left_axis
    assert _cell(plot, 2) is sub.view_box
    assert _cell(plot, 2, row=3) is sub.bottom_axis
    qtbot.wait(20)
    # The secondary view covers the main view exactly (same X range, same pixels).
    view = sub.view_for_axis(axis_id)
    assert view.sceneBoundingRect().left() == pytest.approx(sub.view_box.sceneBoundingRect().left())
    assert view.viewRange()[0] == pytest.approx(sub.view_box.viewRange()[0])
    # The axis cell is left of the primary axis cell, inside the widget.
    # (Not sceneBoundingRect: the primary axis also draws the grid over the whole view.)
    assert axis.geometry().right() <= sub.left_axis.geometry().left() + 1
    assert axis.geometry().left() >= 0 and axis.geometry().width() > 10


def test_left_and_right_axes_together_and_side_switch(plot: PlotWidget) -> None:
    sub = plot.subplots[0]
    plot.add_series([STATUS])
    left_id = plot.move_curve_to_axis(0, TORQUE, None, side="left")
    right_id = plot.move_curve_to_axis(0, STATUS, None)
    assert _cell(plot, 0) is sub.axis_item(left_id)
    assert _cell(plot, 1 + 3) is sub.axis_item(right_id)  # shifted by one left axis
    # Moving the left axis to the right: a new right-oriented AxisItem, grid unshifted.
    cfg = plot.config.subplots[0].axis(left_id)
    cfg.side = "right"
    plot.set_axis_config(0, cfg)
    assert sub.axis_item(left_id).orientation == "right"
    assert _cell(plot, 0) is sub.left_axis and _cell(plot, 1) is sub.view_box
    assert {_cell(plot, 3), _cell(plot, 4)} == {sub.axis_item(left_id), sub.axis_item(right_id)}
    assert plot.curve_item(TORQUE).getViewBox() is sub.view_for_axis(left_id)


def test_absolute_x_axis_keeps_the_shift(plot: PlotWidget) -> None:
    sub = plot.subplots[0]
    axis_id = plot.move_curve_to_axis(0, TORQUE, None, side="left")
    x = plot.config.x_axis
    x.x_mode = "absolute"
    plot.set_axis_config(0, x)  # pyqtgraph re-adds the new bottom axis at its default cell
    assert _cell(plot, 0) is sub.axis_item(axis_id)
    assert _cell(plot, 2, row=3) is sub.bottom_axis


def test_axis_with_no_curve_left_is_removed(plot: PlotWidget) -> None:
    sub = plot.subplots[0]
    plot.move_curve_to_axis(0, TORQUE, None, side="left")
    plot.move_curve_to_axis(0, TORQUE, "y0")
    assert len(plot.config.subplots[0].y_axes) == 1
    assert _cell(plot, 0) is sub.left_axis and _cell(plot, 1) is sub.view_box


def test_drop_on_left_margin_creates_left_axis(plot: PlotWidget) -> None:
    rect = plot.subplots[0].view_box.sceneBoundingRect()
    scene_pos = QPointF(rect.left() + 5, rect.center().y())
    mime = encode_series_ids([STATUS])  # keep a reference: QDropEvent does not own it
    event = QDropEvent(
        QPointF(plot.mapFromScene(scene_pos)),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    plot.dropEvent(event)
    cfg = plot.config.subplots[0]
    axis = cfg.axis(cfg.curve(STATUS).axis_id)
    assert axis is not None and axis.axis_id != "y0" and axis.side == "left"


def test_menus_offer_left_side(plot: PlotWidget) -> None:
    controller = PlotController(plot)
    menu = controller.build_plot_menu(0, QPointF(5, 5))
    curves = next(a.menu() for a in menu.actions() if a.text() == "Courbes")
    speed = next(a.menu() for a in curves.actions() if a.text() == "speed")
    move = next(a.menu() for a in speed.actions() if a.text() == "Déplacer vers l'axe")
    next(a for a in move.actions() if a.text() == "Nouvel axe à gauche").trigger()
    axis_id = plot.config.subplots[0].curve(SPEED).axis_id
    assert plot.config.subplots[0].axis(axis_id).side == "left"
    axis_menu = controller.build_axis_menu(0, axis_id)
    next(a for a in axis_menu.actions() if a.text() == "Placer l'axe à droite").trigger()
    assert plot.config.subplots[0].axis(axis_id).side == "right"
    assert "Placer l'axe" not in " ".join(
        a.text() for a in controller.build_axis_menu(0, "y0").actions()
    )


def test_side_survives_json(plot: PlotWidget) -> None:
    plot.move_curve_to_axis(0, TORQUE, None, side="left")
    restored = PlotConfig.from_dict(json.loads(json.dumps(plot.config.to_dict())))
    assert restored.subplots[0].y_axes[1].side == "left"
