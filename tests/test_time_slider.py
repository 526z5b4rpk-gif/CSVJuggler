from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session

SPEED = "simple_comma/speed"  # x = 0..0.4, y = 0, 10.2, 20.5, 30.1, 40
TORQUE = "simple_comma/torque"


@pytest.fixture
def window(qtbot, data_dir: Path) -> MainWindow:
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_bar_disabled_without_data_then_range_follows_session(window: MainWindow, data_dir) -> None:
    bar = window.time_bar
    assert not bar.slider.isEnabled()
    window.open_files([data_dir / "simple_comma.csv"], interactive=False)
    assert bar.slider.isEnabled()
    assert (bar.lo, bar.hi) == pytest.approx((0.0, 0.4))


def test_dragging_shows_cursor_on_every_graph(window: MainWindow, data_dir) -> None:
    window.open_files([data_dir / "simple_comma.csv"], interactive=False)
    first = window.plot_docks[0]
    first.plot.add_series([SPEED])
    lonely = window.split_plot(first, Qt.Orientation.Horizontal)
    lonely.plot.add_series([TORQUE])
    lonely.plot.set_sync_group("")  # not synchronised: still gets the cursor
    bar = window.time_bar
    assert not first.playhead.enabled

    bar.slider.setValue(bar.slider.maximum() // 2)  # what dragging does → x = 0.2
    assert bar.show_check.isChecked()
    for dock in (first, lonely):
        assert dock.playhead.enabled
        assert dock.playhead.x == pytest.approx(0.2)
    assert "speed : 20.5" in first.playhead.label_text()
    assert "torque : 1.7" in lonely.playhead.label_text()

    bar.show_check.setChecked(False)
    assert not first.playhead.enabled and first.playhead.label_text() == ""


def test_spin_box_and_new_graph(window: MainWindow, data_dir) -> None:
    window.open_files([data_dir / "simple_comma.csv"], interactive=False)
    window.time_bar.spin.setValue(0.15)
    new = window.new_plot()
    new.plot.add_series([SPEED])
    assert new.playhead.enabled and new.playhead.x == pytest.approx(0.15)
    assert "speed : 15.35" in new.playhead.label_text()


def test_views_follow_the_cursor(window: MainWindow, data_dir) -> None:
    window.open_files([data_dir / "simple_comma.csv"], interactive=False)
    plot = window.plot_docks[0].plot
    plot.add_series([SPEED])
    plot.subplots[0].view_box.setXRange(0.0, 0.1, padding=0)
    window.time_bar.set_position(0.3)
    lo, hi = plot.x_range()
    assert lo <= 0.3 <= hi and hi - lo == pytest.approx(0.1)
    window.time_bar.follow_check.setChecked(False)
    window.time_bar.set_position(0.05)
    assert plot.x_range() == pytest.approx((lo, hi))


def test_playback_advances_and_stops_at_the_end(window: MainWindow, data_dir, qtbot) -> None:
    window.open_files([data_dir / "simple_comma.csv"], interactive=False)
    bar = window.time_bar
    bar.set_position(0.0)
    bar.speed_combo.setCurrentIndex(bar.speed_combo.findData(0.1))
    bar.advance(1.0)  # 1 s of real time at x0.1 → +0.1
    assert bar.position == pytest.approx(0.1)
    bar.set_playing(True)
    assert bar.playing and bar.play_button.text() == "⏸"
    bar.advance(10.0)
    assert bar.position == pytest.approx(0.4)
    assert not bar.playing  # stopped at the end
    bar.set_playing(True)  # restarting at the end rewinds
    assert bar.position == pytest.approx(0.0)
    qtbot.waitUntil(lambda: bar.position > 0.0, timeout=2000)
    bar.set_playing(False)
