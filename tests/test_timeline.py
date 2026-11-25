"""Timeline of the « Lecture X » bar: one lane per CSV file on a common clock."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session
from csvjuggler.ui.timeline import _ticks, format_x

T0 = datetime(2026, 11, 25, 8, 0, tzinfo=UTC).timestamp()


def _write(path: Path, start_s: int, end_s: int) -> Path:
    lines = ["Horodatage;courant [A]"]
    for k in range(start_s, end_s + 1, 10):
        stamp = datetime.fromtimestamp(T0 + k, tz=UTC).strftime("%Y-%m-%d %H:%M:%S.000")
        lines.append(f"{stamp};{k % 7}")
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    qtbot.waitExposed(w)
    files = [
        _write(tmp_path / "moteur.csv", 0, 600),
        _write(tmp_path / "pompe.csv", 240, 900),
        _write(tmp_path / "ventilation.csv", 1200, 1500),
    ]
    w.open_files(files, interactive=False)
    return w


def test_one_lane_per_file_on_the_common_clock(window: MainWindow) -> None:
    timeline = window.time_bar.timeline
    assert window.session.absolute_time() and timeline.absolute
    assert [(lane.alias, lane.lo - T0, lane.hi - T0) for lane in timeline.lanes] == [
        ("moteur", 0, 600),
        ("pompe", 240, 900),
        ("ventilation", 1200, 1500),
    ]
    assert (timeline.lo - T0, timeline.hi - T0) == (0, 1500)
    assert len({lane.color for lane in timeline.lanes}) == 3
    # Lanes are drawn where the files are in time.
    pompe = timeline.lane_rect(1)
    assert pompe.left() == pytest.approx(timeline.x_to_px(T0 + 240))
    assert pompe.right() == pytest.approx(timeline.x_to_px(T0 + 900))
    assert window.time_bar.time_label.isVisibleTo(window.time_bar)


def test_click_and_drag_move_the_playhead(window: MainWindow, qtbot) -> None:
    timeline = window.time_bar.timeline
    px = round(timeline.x_to_px(T0 + 300))
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(px, 5))
    assert window.time_bar.position == pytest.approx(T0 + 300, abs=1500 / timeline.width() * 2)
    assert window.time_bar.cursor_visible
    assert window.plot_docks[0].playhead.x == pytest.approx(window.time_bar.position)
    assert window.time_bar.time_label.text().startswith("2026-11-25 08:0")


def test_double_click_on_a_lane_frames_that_file(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.plot.add_series(["moteur/courant", "pompe/courant", "ventilation/courant"])
    timeline = window.time_bar.timeline
    rect = timeline.lane_rect(2)
    QTest.mouseDClick(timeline, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    lo, hi = dock.plot.x_range()
    assert lo <= T0 + 1200 and hi >= T0 + 1500
    assert hi - lo == pytest.approx(300 * 1.04, rel=0.01)
    # The visible range of the current graph is highlighted.
    assert timeline.view_range == pytest.approx((lo, hi))


def test_relative_time_files_and_formatting(qtbot, data_dir: Path) -> None:
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.open_files([data_dir / "simple_comma.csv"], interactive=False)
    assert not w.session.absolute_time() and not w.time_bar.timeline.absolute
    assert not w.time_bar.time_label.isVisibleTo(w.time_bar)
    assert format_x(0.25, False) == "0.25"
    assert format_x(T0 + 75.5, True, 5) == "08:01:15.500"
    assert format_x(T0 + 75.5, True, 600) == "08:01:15"
    assert format_x(T0, True, 10 * 86400) == "2026-11-25 08:00:00"
    assert format_x(T0 + 0.25, True, full=True) == "2026-11-25 08:00:00.250"


def test_ticks() -> None:
    assert _ticks(0.0, 1.0, 5, absolute=False) == pytest.approx([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ticks = _ticks(T0 + 3, T0 + 1500, 6, absolute=True)
    assert ticks[0] == T0 + 300 and all(b - a == 300 for a, b in itertools.pairwise(ticks))


def test_cursor_label_shows_time_of_day_when_x_is_absolute(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.plot.add_series(["moteur/courant"])
    config = dock.plot.config
    config.x_axis.x_mode = "absolute"
    dock.plot.update_config(config)
    window.time_bar.set_position(T0 + 75.5)
    assert dock.playhead.label_text().startswith("x = 08:01:15.500")
