from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent

from csvjuggler.model.session import Session
from csvjuggler.ui.multi_axis import FIRST_RIGHT_COLUMN, SecondaryViewBox
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


class _Wheel:
    """Minimal stand-in for pyqtgraph's wheel event."""

    def __init__(self, delta: int) -> None:
        self._delta = delta
        self.accepted = None

    def delta(self) -> int:
        return self._delta

    def pos(self) -> QPointF:
        return QPointF(10, 10)

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


def test_move_curve_to_new_axis(plot: PlotWidget, qtbot) -> None:
    axis_id = plot.move_curve_to_axis(0, TORQUE, None)
    assert axis_id == "y1"
    sub = plot.subplots[0]
    cfg = plot.config.subplots[0]
    assert [a.axis_id for a in cfg.y_axes] == ["y0", "y1"]
    view = sub.view_for_axis("y1")
    assert isinstance(view, SecondaryViewBox)
    assert plot.curve_item(TORQUE).getViewBox() is view
    axis = sub.axis_item("y1")
    assert sub.plot_item.layout.itemAt(2, FIRST_RIGHT_COLUMN) is axis
    # Default colour of a secondary axis = its first curve's colour.
    assert axis.pen().color().name() == cfg.curve(TORQUE).color
    qtbot.wait(20)
    assert view.sceneBoundingRect() == sub.view_box.sceneBoundingRect()


def test_secondary_axis_x_linked_y_independent(plot: PlotWidget) -> None:
    plot.move_curve_to_axis(0, TORQUE, None)
    sub = plot.subplots[0]
    secondary = sub.view_for_axis("y1")
    y_before = secondary.viewRange()[1]
    sub.view_box.setXRange(0.1, 0.2, padding=0)
    sub.view_box.setYRange(-100, 100, padding=0)
    assert secondary.viewRange()[0] == pytest.approx([0.1, 0.2])
    assert secondary.viewRange()[1] == pytest.approx(y_before)
    assert y_before[0] >= 1.3 and y_before[1] <= 2.0  # own auto range (torque only, padded)


def test_wheel_only_on_its_axis(plot: PlotWidget) -> None:
    plot.move_curve_to_axis(0, TORQUE, None)
    sub = plot.subplots[0]
    secondary = sub.view_for_axis("y1")
    main_y = list(sub.view_box.viewRange()[1])
    sec_y = list(secondary.viewRange()[1])

    area_event = _Wheel(120)
    secondary.wheelEvent(area_event)  # event in the plot area (no axis)
    assert area_event.accepted is False

    secondary.wheelEvent(_Wheel(120), axis=1)  # forwarded by its axis
    assert secondary.viewRange()[1] != pytest.approx(sec_y)
    assert sub.view_box.viewRange()[1] == pytest.approx(main_y)


def test_drop_on_right_margin_creates_axis(plot: PlotWidget) -> None:
    rect = plot.subplots[0].view_box.sceneBoundingRect()
    scene_pos = QPointF(rect.right() - 5, rect.center().y())
    view_pos = plot.mapFromScene(scene_pos)
    mime = encode_series_ids([STATUS])  # keep a reference: QDropEvent does not own it
    event = QDropEvent(
        QPointF(view_pos),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    plot.dropEvent(event)
    cfg = plot.config.subplots[0]
    assert cfg.curve(STATUS).axis_id == "y1"
    assert len(cfg.y_axes) == 2


def test_axis_without_curve_is_removed(plot: PlotWidget) -> None:
    plot.move_curve_to_axis(0, TORQUE, None)
    plot.move_curve_to_axis(0, SPEED, "y1")
    plot.move_curve_to_axis(0, TORQUE, "y0")
    assert [a.axis_id for a in plot.config.subplots[0].y_axes] == ["y0", "y1"]
    plot.remove_curve(SPEED, 0)
    assert [a.axis_id for a in plot.config.subplots[0].y_axes] == ["y0"]
    assert "y1" not in plot.subplots[0].multi_axis
    assert plot.subplots[0].plot_item.layout.itemAt(2, FIRST_RIGHT_COLUMN) is None


def test_x_auto_range_includes_secondary_curves(plot: PlotWidget) -> None:
    plot.remove_curve(SPEED, 0)
    plot.move_curve_to_axis(0, TORQUE, None)  # main view now has no curve
    plot.auto_range()
    lo, hi = plot.x_range()
    assert lo <= 0.0 and hi >= 0.4


def test_curve_menu_move_to_new_axis(plot: PlotWidget) -> None:
    controller = PlotController(plot)
    menu = controller.build_plot_menu(0, QPointF(0, 0))
    curves = next(a.menu() for a in menu.actions() if a.text() == "Courbes")
    torque_menu = next(a.menu() for a in curves.actions() if a.text() == "torque")
    move = next(a.menu() for a in torque_menu.actions() if a.text() == "Déplacer vers l'axe")
    next(a for a in move.actions() if a.text() == "Nouvel axe à droite").trigger()
    assert plot.config.subplots[0].curve(TORQUE).axis_id == "y1"
