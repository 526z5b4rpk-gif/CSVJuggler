"""Timeline of the « Lecture X » bar: one lane per CSV file on a common X axis.

All files are drawn on the same axis (the X extent of every series), so files recorded with
the same absolute clock (date/time column, or a shared counter) appear where they are in time
relative to each other. The playhead and the visible range of the current graph are drawn on
top. Clicking or dragging moves the playhead; double-clicking a lane frames that file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from csvjuggler.data.analysis import format_number
from csvjuggler.i18n import Msg, tr

LANE_HEIGHT = 15
LANE_GAP = 3
AXIS_HEIGHT = 16
MARGIN = 6
PLAYHEAD_COLOR = "#ef6c00"
VIEW_COLOR = QColor(21, 101, 192, 40)
NICE_STEPS = (1.0, 2.0, 2.5, 5.0)
TIME_STEPS = (
    0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
    1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
    3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800,
)  # fmt: skip


@dataclass(frozen=True)
class Lane:
    alias: str
    lo: float
    hi: float
    color: str


def format_x(x: float, absolute: bool, span: float = 0.0, full: bool = False) -> str:
    """X as text: date/time (UTC, like the date axis) when absolute, else a number.

    ``span`` (the range being shown) picks the precision; ``full``: date and milliseconds.
    """
    if not absolute or not math.isfinite(x):
        return format_number(x)
    stamp = datetime.fromtimestamp(x, tz=UTC)
    if full:
        return stamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if span and span < 10:
        return stamp.strftime("%H:%M:%S.%f")[:-3]
    if span and span < 86400:
        return stamp.strftime("%H:%M:%S")
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def _ticks(lo: float, hi: float, max_ticks: int, absolute: bool) -> list[float]:
    span = hi - lo
    if span <= 0 or max_ticks < 1:
        return []
    raw = span / max_ticks
    if absolute:
        step = next((s for s in TIME_STEPS if s >= raw), TIME_STEPS[-1])
    else:
        magnitude = 10 ** math.floor(math.log10(raw))
        step = next((m * magnitude for m in NICE_STEPS if m * magnitude >= raw), 10 * magnitude)
    first = math.ceil(lo / step) * step
    count = int((hi - first) / step) + 1
    return [first + i * step for i in range(max(0, count))]


class TimelineWidget(QWidget):
    position_requested = Signal(float)
    """Click or drag: the user wants the playhead at this X."""
    lane_activated = Signal(float, float)
    """Double-click on a lane: ``(lo, hi)`` of that file."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lanes: list[Lane] = []
        self.lo, self.hi = 0.0, 1.0
        self.position: float | None = None
        self.view_range: tuple[float, float] | None = None
        self.absolute = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(300)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_height()

    # -- state ----------------------------------------------------------------------------

    def set_lanes(self, lanes: list[Lane], absolute: bool) -> None:
        self.lanes = lanes
        self.absolute = absolute
        self._update_height()
        self.update()

    def set_range(self, lo: float, hi: float) -> None:
        self.lo, self.hi = lo, hi
        self.update()

    def set_position(self, x: float | None) -> None:
        self.position = x
        self.update()

    def set_view_range(self, view: tuple[float, float] | None) -> None:
        self.view_range = view
        self.update()

    def _update_height(self) -> None:
        lanes = max(1, len(self.lanes))
        self.setFixedHeight(MARGIN + lanes * (LANE_HEIGHT + LANE_GAP) + AXIS_HEIGHT)

    def sizeHint(self) -> QSize:
        return QSize(600, self.height())

    # -- geometry -------------------------------------------------------------------------

    def _track(self) -> QRectF:
        return QRectF(MARGIN, MARGIN / 2, max(1.0, self.width() - 2 * MARGIN), self.height())

    def x_to_px(self, x: float) -> float:
        track = self._track()
        span = self.hi - self.lo
        return track.left() + (x - self.lo) / span * track.width() if span > 0 else track.left()

    def px_to_x(self, px: float) -> float:
        track = self._track()
        frac = (px - track.left()) / track.width()
        return self.lo + min(max(frac, 0.0), 1.0) * (self.hi - self.lo)

    def lane_rect(self, index: int) -> QRectF:
        lane = self.lanes[index]
        top = MARGIN / 2 + index * (LANE_HEIGHT + LANE_GAP)
        left, right = self.x_to_px(lane.lo), self.x_to_px(lane.hi)
        return QRectF(left, top, max(3.0, right - left), LANE_HEIGHT)

    def lane_at(self, point: QPointF) -> int | None:
        for index in range(len(self.lanes)):
            rect = self.lane_rect(index)
            row = QRectF(self._track().left(), rect.top(), self._track().width(), rect.height())
            if row.contains(point):
                return index
        return None

    # -- painting -------------------------------------------------------------------------

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        enabled = self.isEnabled() and self.hi > self.lo
        track = self._track()
        lanes_bottom = MARGIN / 2 + max(1, len(self.lanes)) * (LANE_HEIGHT + LANE_GAP)
        painter.fillRect(
            QRectF(track.left(), MARGIN / 2, track.width(), lanes_bottom - MARGIN / 2),
            palette.alternateBase(),
        )
        if not enabled:
            return

        # Lanes (one per file).
        metrics = QFontMetricsF(self.font())
        for index, lane in enumerate(self.lanes):
            rect = self.lane_rect(index)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(lane.color))
            painter.drawRoundedRect(rect, 3, 3)
            text_color = "#000000" if QColor(lane.color).lightness() > 150 else "#ffffff"
            label = metrics.elidedText(lane.alias, Qt.TextElideMode.ElideRight, rect.width() - 6)
            painter.setPen(QColor(text_color))
            painter.drawText(rect.adjusted(4, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter, label)

        # Visible range of the current graph.
        if self.view_range is not None:
            a, b = (self.x_to_px(v) for v in self.view_range)
            left, right = max(track.left(), min(a, b)), min(track.right(), max(a, b))
            if right > left:
                band = QRectF(left, MARGIN / 2, right - left, lanes_bottom - MARGIN / 2)
                painter.setPen(QPen(QColor(21, 101, 192, 140), 1))
                painter.setBrush(VIEW_COLOR)
                painter.drawRect(band)

        # Axis.
        painter.setPen(palette.text().color())
        axis_y = lanes_bottom + 1
        painter.drawLine(QPointF(track.left(), axis_y), QPointF(track.right(), axis_y))
        sample = format_x(self.hi, self.absolute, self.hi - self.lo)
        max_ticks = max(2, int(track.width() / (metrics.horizontalAdvance(sample) + 24)))
        for tick in _ticks(self.lo, self.hi, max_ticks, self.absolute):
            px = self.x_to_px(tick)
            painter.drawLine(QPointF(px, axis_y), QPointF(px, axis_y + 3))
            text = format_x(tick, self.absolute, self.hi - self.lo)
            width = metrics.horizontalAdvance(text)
            left = min(max(px - width / 2, 0.0), self.width() - width)
            painter.drawText(QPointF(left, axis_y + 3 + metrics.ascent()), text)

        # Playhead.
        if self.position is not None:
            px = self.x_to_px(self.position)
            painter.setPen(QPen(QColor(PLAYHEAD_COLOR), 2))
            painter.drawLine(QPointF(px, MARGIN / 2 - 2), QPointF(px, lanes_bottom))
            head = QPainterPath(QPointF(px - 5, 0))
            head.lineTo(px + 5, 0)
            head.lineTo(px, 6)
            head.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PLAYHEAD_COLOR))
            painter.drawPath(head)

    # -- mouse ----------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.hi > self.lo:
            self.position_requested.emit(self.px_to_x(event.position().x()))
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self.hi > self.lo:
            self.position_requested.emit(self.px_to_x(event.position().x()))
            return
        index = self.lane_at(event.position())
        if index is None:
            QToolTip.hideText()
            self.setToolTip("")
            return
        lane = self.lanes[index]
        span = lane.hi - lane.lo
        self.setToolTip(
            tr(Msg.TIMELINE_LANE_TIP).format(
                alias=lane.alias,
                start=format_x(lane.lo, self.absolute),
                end=format_x(lane.hi, self.absolute),
                duration=format_number(span),
            )
        )

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        index = self.lane_at(event.position())
        if index is not None:
            lane = self.lanes[index]
            self.lane_activated.emit(lane.lo, lane.hi)
            event.accept()
