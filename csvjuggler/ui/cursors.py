"""Measurement cursors of a graph: the mouse tracker and the A/B cursors."""

from __future__ import annotations

import html
import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QPen

from csvjuggler.data.analysis import (
    Interpolation,
    Stats,
    format_number,
    interval_stats,
    nearest_value,
    value_at,
)
from csvjuggler.model.plot_config import CurveConfig
from csvjuggler.ui.plot_widget import PlotWidget, display_data
from csvjuggler.ui.timeline import format_x

CURSOR_Z = 60
TRACKER_PEN = pg.mkPen("#555555", width=1, style=Qt.PenStyle.DashLine)
PLAYHEAD_PEN = pg.mkPen("#ef6c00", width=2)
CURSOR_COLORS = {"A": "#1565c0", "B": "#c62828"}


def _x_series(plot: PlotWidget):
    x_cfg = plot.config.x_axis
    if x_cfg.x_mode == "series" and x_cfg.x_series_id:
        return plot.session.get_series(x_cfg.x_series_id)
    return None


def curve_value(plot: PlotWidget, curve: CurveConfig, x0: float, mode: Interpolation) -> float:
    """Displayed y of ``curve`` at ``x0`` (gain/offset applied; XY mode → nearest point)."""
    series = plot.session.get_series(curve.series_id)
    if series is None:
        return math.nan
    x_series = _x_series(plot)
    if x_series is None:
        return curve.gain * value_at(series.x, series.y, x0, mode) + curve.offset
    x, y = display_data(series, curve, x_series)
    return nearest_value(x, y, x0)


def curve_stats(plot: PlotWidget, curve: CurveConfig, x0: float, x1: float) -> Stats:
    series = plot.session.get_series(curve.series_id)
    if series is None:
        return interval_stats(np.empty(0), np.empty(0), x0, x1)
    x, y = display_data(series, curve, _x_series(plot))
    return interval_stats(x, y, x0, x1)


class ValueCursor(QObject):
    """Vertical line at ``x`` in every subplot, with the value of each visible curve."""

    def __init__(
        self, plot: PlotWidget, pen: QPen, label_at_bottom: bool = False, z: float = CURSOR_Z
    ) -> None:
        super().__init__(plot)
        self.plot = plot
        self.pen = pen
        self.label_at_bottom = label_at_bottom
        self.z = z
        self.enabled = False
        self.mode: Interpolation = "linear"
        self.x: float | None = None
        self._items: list[tuple[pg.InfiniteLine, pg.TextItem]] = []
        plot.config_changed.connect(self._rebuild)

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self.enabled:
            self.enabled = enabled
            self._rebuild()

    def set_mode(self, mode: Interpolation) -> None:
        self.mode = mode
        if self.x is not None:
            self.set_x(self.x)

    def _rebuild(self) -> None:
        for line, label in self._items:
            for item in (line, label):
                view = item.getViewBox()
                if view is not None:
                    view.removeItem(item)
        self._items = []
        if not self.enabled:
            return
        anchor = (0, 1) if self.label_at_bottom else (0, 0)
        for sub in self.plot.subplots:
            line = pg.InfiniteLine(angle=90, movable=False, pen=self.pen)
            label = pg.TextItem(anchor=anchor, color="#000000", fill=pg.mkBrush(255, 255, 255, 220))
            for item in (line, label):
                item.setZValue(self.z)
                sub.view_box.addItem(item, ignoreBounds=True)
            sub.view_box.sigRangeChanged.connect(self._place_labels)
            self._items.append((line, label))
        if self.x is not None:
            self.set_x(self.x)

    def set_x(self, x: float) -> None:
        self.x = x
        if not self.enabled:
            return
        for (line, label), sub_cfg in zip(self._items, self.plot.config.subplots, strict=False):
            line.setPos(x)
            absolute = self.plot.config.x_axis.x_mode == "absolute"
            x_text = format_x(x, absolute, 1.0) if absolute else format_number(x)
            rows = [f"<b>x = {html.escape(x_text)}</b>"]
            for curve in sub_cfg.curves:
                if not curve.visible:
                    continue
                value = curve_value(self.plot, curve, x, self.mode)
                name = html.escape(self.plot.series_label(curve))
                rows.append(
                    f'<span style="color:{curve.color}">■</span> {name} : '
                    f"{html.escape(format_number(value))}"
                )
            label.setHtml("<br>".join(rows))
        self._place_labels()

    def _place_labels(self, *_args: object) -> None:
        if not self.enabled or self.x is None:
            return
        for (_line, label), sub in zip(self._items, self.plot.subplots, strict=False):
            y_lo, y_hi = sub.view_box.viewRange()[1]
            label.setPos(self.x, y_lo if self.label_at_bottom else y_hi)

    def label_text(self, subplot: int = 0) -> str:
        return self._items[subplot][1].toPlainText() if subplot < len(self._items) else ""


class Tracker(ValueCursor):
    """Value cursor following the mouse (key T)."""

    moved = Signal(float)

    def __init__(self, plot: PlotWidget) -> None:
        super().__init__(plot, TRACKER_PEN)
        plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def _on_mouse_moved(self, scene_pos: QPointF) -> None:
        if not self.enabled:
            return
        for sub in self.plot.subplots:
            if sub.view_box.sceneBoundingRect().contains(scene_pos):
                x = sub.view_box.mapSceneToView(scene_pos).x()
                self.set_x(x)
                self.moved.emit(x)
                return


class ABCursors(QObject):
    """Two movable vertical cursors, mirrored in every subplot of the graph."""

    changed = Signal()

    def __init__(self, plot: PlotWidget) -> None:
        super().__init__(plot)
        self.plot = plot
        self.enabled = False
        self.a = 0.0
        self.b = 0.0
        self._lines: list[dict[str, pg.InfiniteLine]] = []
        self._updating = False
        plot.config_changed.connect(self._rebuild)

    @property
    def delta(self) -> float:
        return self.b - self.a

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not self.enabled:
            lo, hi = self.plot.x_range()
            self.a, self.b = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
        self.enabled = enabled
        self._rebuild()
        self.changed.emit()

    def set_positions(self, a: float, b: float) -> None:
        self.a, self.b = a, b
        self._sync_lines()
        self.changed.emit()

    def _rebuild(self) -> None:
        for old in self._lines:
            for line in old.values():
                view = line.getViewBox()
                if view is not None:
                    view.removeItem(line)
        self._lines = []
        if not self.enabled:
            return
        for sub in self.plot.subplots:
            lines: dict[str, pg.InfiniteLine] = {}
            for name in ("A", "B"):
                color = CURSOR_COLORS[name]
                line = pg.InfiniteLine(
                    pos=self.a if name == "A" else self.b,
                    angle=90,
                    movable=True,
                    pen=pg.mkPen(color, width=1.5),
                    hoverPen=pg.mkPen(color, width=3),
                    label=name,
                    labelOpts={"position": 0.03, "color": color, "fill": (255, 255, 255, 200)},
                )
                line.setZValue(CURSOR_Z)
                line.sigPositionChanged.connect(lambda ln, n=name: self._on_line_moved(n, ln))
                sub.view_box.addItem(line, ignoreBounds=True)
                lines[name] = line
            self._lines.append(lines)

    def _on_line_moved(self, name: str, line: pg.InfiniteLine) -> None:
        if self._updating:
            return
        value = float(line.value())
        if name == "A":
            self.a = value
        else:
            self.b = value
        self._sync_lines()
        self.changed.emit()

    def _sync_lines(self) -> None:
        self._updating = True
        try:
            for lines in self._lines:
                lines["A"].setValue(self.a)
                lines["B"].setValue(self.b)
        finally:
            self._updating = False
