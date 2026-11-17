from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6.QtCore import Qt

from csvjuggler.model.plot_config import AxisConfig, CurveConfig, PlotConfig, SubplotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.dialogs.curve_settings_dialog import CurveSettingsDialog
from csvjuggler.ui.dialogs.plot_settings_dialog import AxisSettingsDialog, PlotSettingsDialog
from csvjuggler.ui.plot_items import DateAxis, FormattedAxis, format_ticks
from csvjuggler.ui.plot_menus import PlotController
from csvjuggler.ui.plot_widget import PlotWidget

SPEED = "simple_comma/speed"
TORQUE = "simple_comma/torque"


@pytest.fixture
def plot(qtbot, data_dir: Path) -> PlotWidget:
    session = Session()
    session.load_csv(data_dir / "simple_comma.csv")
    widget = PlotWidget(session)
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.waitExposed(widget)
    widget.add_series([SPEED, TORQUE])
    return widget


def test_full_config_json_roundtrip() -> None:
    cfg = PlotConfig(
        title="T",
        title_size=16,
        show_title=False,
        background="#000000",
        legend_position="bottom-right",
        x_axis=AxisConfig(axis_id="x", x_mode="series", x_series_id="a/b", log=True),
        subplots=[
            SubplotConfig(
                ratio=2,
                y_axes=[AxisConfig(label="V", unit="m/s", auto_range=False, min=-1, max=5)],
                curves=[
                    CurveConfig(
                        "a/c", "#123456", style="dash", marker="s", mode="step", gain=2, offset=1
                    )
                ],
            )
        ],
    )
    assert PlotConfig.from_dict(json.loads(json.dumps(cfg.to_dict()))) == cfg
    assert AxisConfig(label="Vitesse", unit="m/s").title == "Vitesse [m/s]"


def test_curve_styles_are_applied_in_place(plot: PlotWidget) -> None:
    item = plot.curve_item(SPEED)
    curve = plot.curve_config(0, SPEED)
    curve.style, curve.width, curve.marker, curve.mode = "dash", 3, "x", "step"
    curve.gain, curve.offset = 2.0, 1.0
    plot.set_curve_config(0, curve)
    assert plot.curve_item(SPEED) is item
    assert item.opts["pen"].style() == Qt.PenStyle.DashLine
    assert item.opts["pen"].widthF() == 3
    assert item.opts["symbol"] == "x"
    assert item.opts["stepMode"] == "left"
    np.testing.assert_allclose(item.getData()[1], 2 * np.array([0, 10.2, 20.5, 30.1, 40]) + 1)

    curve.mode = "points"
    curve.marker = "none"
    plot.set_curve_config(0, curve)
    assert item.opts["pen"] is None or item.opts["pen"].style() == Qt.PenStyle.NoPen
    assert item.opts["symbol"] == "o"


def test_axis_settings_applied(plot: PlotWidget) -> None:
    axis = plot.axis_config(0, "y0")
    axis.label, axis.unit = "Vitesse", "rpm"
    axis.auto_range, axis.min, axis.max = False, -5.0, 50.0
    axis.inverted, axis.color, axis.decimals = True, "#ff0000", 2
    plot.set_axis_config(0, axis)
    sub = plot.subplots[0]
    assert sub.view_box.viewRange()[1] == pytest.approx([-5, 50])
    assert sub.view_box.yInverted()
    assert "Vitesse [rpm]" in sub.left_axis.labelText
    assert sub.left_axis.tickStrings([1.0, 2.5], 1.0, 1.0) == ["1.00", "2.50"]

    # A style change elsewhere keeps the user's zoom.
    sub.view_box.setYRange(0, 10, padding=0)
    curve = plot.curve_config(0, SPEED)
    curve.color = "#00ff00"
    plot.set_curve_config(0, curve)
    assert sub.view_box.viewRange()[1] == pytest.approx([0, 10])


def test_log_axis_and_auto_once(plot: PlotWidget) -> None:
    plot.auto_range_once(0, "y0")
    axis = plot.axis_config(0, "y0")
    assert not axis.auto_range
    assert axis.min <= 0 and axis.max >= 40
    lo, hi = plot.data_range(0, "x")
    assert (lo, hi) == pytest.approx((0, 0.4), abs=1e-3)  # bounds include pen width
    axis.log, axis.auto_range = True, True
    plot.set_axis_config(0, axis)
    assert plot.curve_item(SPEED).opts["logMode"] == [False, True]


def test_x_modes_absolute_and_xy(plot: PlotWidget) -> None:
    x = plot.config.x_axis
    x.x_mode = "absolute"
    plot.set_axis_config(0, x)
    assert isinstance(plot.subplots[0].bottom_axis, DateAxis)
    x.x_mode, x.x_series_id = "series", TORQUE
    plot.set_axis_config(0, x)
    assert isinstance(plot.subplots[0].bottom_axis, FormattedAxis)
    np.testing.assert_allclose(plot.curve_item(SPEED).getData()[0], [1.5, 1.6, 1.7, 1.65, 1.8])


def test_plot_level_settings(plot: PlotWidget) -> None:
    cfg = plot.config_copy()
    cfg.title, cfg.legend_position, cfg.background = "Essai", "hidden", "#202020"
    plot.update_config(cfg)
    assert plot.subplots[0].plot_item.titleLabel.text == "Essai"
    assert not plot.subplots[0].legend.isVisible()


def test_format_ticks() -> None:
    assert format_ticks([1500.0], 1.0, AxisConfig(scientific=True)) == ["1.50e+03"]
    assert format_ticks([1500.0], 1.0, AxisConfig(si_prefix=True)) == ["1.5 k"]
    assert format_ticks([1.0], 1.0, AxisConfig()) is None


def test_plot_settings_dialog_roundtrip(plot: PlotWidget, qtbot) -> None:
    plot.split()
    dialog = PlotSettingsDialog(plot.config, [("speed", SPEED)])
    qtbot.addWidget(dialog)
    dialog.title_edit.setText("Banc 1")
    dialog.legend_combo.setCurrentIndex(dialog.legend_combo.findData("top-right"))
    dialog.sync_edit.setText("")
    dialog.ratios_edit.setText("3, 1")
    dialog.x_editor.label_edit.setText("Temps")
    dialog.x_editor.unit_edit.setText("s")
    dialog.y_combo.setCurrentIndex(1)
    dialog.y_editors[1][1].log_check.setChecked(True)
    cfg = dialog.config()
    assert cfg.title == "Banc 1" and cfg.legend_position == "top-right"
    assert cfg.sync_group == ""
    assert [s.ratio for s in cfg.subplots] == [3, 1]
    assert cfg.x_axis.title == "Temps [s]"
    assert cfg.subplots[1].y_axes[0].log and not cfg.subplots[0].y_axes[0].log
    assert plot.config.title == ""  # the dialog edits a copy


def test_axis_and_curve_dialogs(qtbot) -> None:
    dialog = AxisSettingsDialog(AxisConfig(), "Y", auto_once=lambda: (1.0, 2.0))
    qtbot.addWidget(dialog)
    dialog.editor._on_auto_once()
    axis = dialog.axis()
    assert (axis.auto_range, axis.min, axis.max) == (False, 1.0, 2.0)

    curve_dialog = CurveSettingsDialog(CurveConfig("a/b", "#000000"), "b")
    qtbot.addWidget(curve_dialog)
    curve_dialog.alias_edit.setText("B")
    curve_dialog.gain_spin.setValue(10)
    curve_dialog.mode_combo.setCurrentIndex(curve_dialog.mode_combo.findData("step"))
    curve = curve_dialog.curve()
    assert (curve.alias, curve.gain, curve.mode) == ("B", 10, "step")


def test_context_menu_actions(plot: PlotWidget) -> None:
    controller = PlotController(plot)
    vb = plot.subplots[0].view_box
    # Right on the speed curve at t = 0.2 s.
    scene_pos = vb.mapViewToScene(pg.Point(0.2, 20.5))
    assert plot.subplots[0].curve_near(scene_pos) == SPEED
    menu = controller.build_plot_menu(0, scene_pos)
    texts = [a.text() for a in menu.actions()]
    assert "Paramètres du graphe…" in texts
    remove = next(a for a in menu.actions() if a.text() == "Retirer du graphe")
    remove.trigger()
    assert [c.series_id for c in plot.config.all_curves()] == [TORQUE]

    axis_menu = controller.build_axis_menu(0, "y0")
    next(a for a in axis_menu.actions() if a.text() == "Ajuster une fois").trigger()
    assert not plot.axis_config(0, "y0").auto_range
