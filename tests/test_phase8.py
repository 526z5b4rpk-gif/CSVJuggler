from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from csvjuggler.data.analysis import interval_stats, to_tsv, value_at
from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session
from csvjuggler.ui.cursors import curve_value

SPEED = "simple_comma/speed"  # x = 0..0.4 step 0.1, y = 0, 10.2, 20.5, 30.1, 40
TORQUE = "simple_comma/torque"


@pytest.fixture
def window(qtbot, data_dir: Path, tmp_path: Path) -> MainWindow:
    csv = tmp_path / "simple_comma.csv"  # annotations write a companion file next to it
    shutil.copy(data_dir / "simple_comma.csv", csv)
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    w.open_files([csv], interactive=False)
    w.plot_docks[0].plot.add_series([SPEED, TORQUE])
    return w


def test_value_at_and_stats() -> None:
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 10.0, 0.0])
    assert value_at(x, y, 0.25) == pytest.approx(2.5)
    assert value_at(x, y, 0.25, "nearest") == 0.0
    assert value_at(x, y, 0.75, "nearest") == 10.0
    assert math.isnan(value_at(x, y, 3.0))
    st = interval_stats(x, y, 2.0, 0.5)  # bounds in any order
    assert (st.count, st.min, st.max, st.peak_to_peak) == (2, 0.0, 10.0, 10.0)
    assert st.mean == pytest.approx(5.0)
    assert st.std == pytest.approx(5.0)
    assert st.rms == pytest.approx(math.sqrt(50))
    assert to_tsv(["a", "b"], [["x", 1.5]]) == "a\tb\nx\t1.5\n"


def test_tracker_values_and_sync(window: MainWindow) -> None:
    first = window.plot_docks[0]
    other = window.new_plot()
    other.plot.add_series([SPEED])
    window.set_tracker_enabled(True)
    assert window.tracker_action.isChecked()
    assert window.tracker_action.shortcut().toString() == "T"

    vb = first.plot.subplots[0].view_box
    scene_pos = vb.mapViewToScene(vb.mapSceneToView(vb.sceneBoundingRect().center()))
    x_center = vb.mapSceneToView(scene_pos).x()
    first.tracker._on_mouse_moved(scene_pos)
    assert first.tracker.x == pytest.approx(x_center)
    assert other.tracker.x == pytest.approx(x_center)  # synced graph follows

    first.tracker.set_x(0.15)
    text = first.tracker.label_text()
    assert "speed : 15.35" in text
    window.set_tracker_mode("nearest")
    assert (
        "speed : 10.2" in first.tracker.label_text() or "speed : 20.5" in first.tracker.label_text()
    )

    window.set_tracker_enabled(False)
    assert first.tracker.label_text() == ""


def test_curve_value_applies_gain_offset(window: MainWindow) -> None:
    plot = window.plot_docks[0].plot
    curve = plot.curve_config(0, SPEED)
    curve.gain, curve.offset = 2.0, 1.0
    plot.set_curve_config(0, curve)
    assert curve_value(plot, curve, 0.1, "linear") == pytest.approx(21.4)


def test_ab_cursors_and_measure_panel(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.plot.split()
    window.toggle_current_cursors()
    assert dock.cursors.enabled
    dock.cursors.set_positions(0.1, 0.3)
    # Moving the B line of the second subplot moves the first one too.
    line_b_sub2 = dock.cursors._lines[1]["B"]
    line_b_sub2.setValue(0.4)
    assert dock.cursors.b == pytest.approx(0.4)
    assert dock.cursors._lines[0]["B"].value() == pytest.approx(0.4)
    dock.cursors.set_positions(0.1, 0.3)

    panel = window.measure_panel
    assert "Δt = 0.2" in panel.cursor_label.text()
    assert "1/Δt = 5" in panel.cursor_label.text()
    rows = {r[0]: r for r in panel.rows()}
    speed = rows["speed"]
    assert speed[1:4] == pytest.approx([10.2, 30.1, 19.9])  # Y(A), Y(B), ΔY
    assert speed[4:6] == pytest.approx([10.2, 30.1])  # min, max between A and B
    assert speed[10] == 3
    assert panel.table.rowCount() == 2

    panel.copy_tsv()
    clip = QApplication.clipboard().text()
    assert clip.splitlines()[0].startswith("Courbe\tY(A)")
    assert clip.splitlines()[1].startswith("A\t0.1\tB\t0.3")
    assert "speed\t10.2\t30.1\t19.9" in clip


def test_stats_on_selected_region(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create("region", dock.dock_id, dock.plot, 0, 0.2, 0.0, "palier")
    ann.x, ann.x2 = 0.25, 0.45
    window.session.annotations.update(ann)
    dock.plot.annotation_layer.hub.selected.emit(ann.id)
    panel = window.measure_panel
    assert "palier" in panel.source_label.text()
    rows = {r[0]: r for r in panel.rows()}
    assert rows["speed"][4:6] == pytest.approx([30.1, 40.0])
    assert math.isnan(rows["speed"][1])  # no A/B cursors
