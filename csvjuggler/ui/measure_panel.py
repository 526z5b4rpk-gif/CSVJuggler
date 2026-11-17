"""« Mesures » panel: A/B cursor readings and statistics of the current graph."""

from __future__ import annotations

import contextlib
import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.data.analysis import format_number, to_tsv
from csvjuggler.i18n import Msg, tr
from csvjuggler.ui.cursors import curve_stats, curve_value

if TYPE_CHECKING:
    from csvjuggler.model.annotation import AnnotationStore
    from csvjuggler.ui.plot_dock import PlotDock

HEADERS = (
    Msg.COL_CURVE,
    Msg.COL_YA,
    Msg.COL_YB,
    Msg.COL_DY,
    Msg.COL_MIN,
    Msg.COL_MAX,
    Msg.COL_MEAN,
    Msg.COL_STD,
    Msg.COL_RMS,
    Msg.COL_P2P,
    Msg.COL_COUNT,
)


class MeasurePanel(QWidget):
    def __init__(self, store: AnnotationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.dock: PlotDock | None = None
        self.cursor_label = QLabel()
        self.source_label = QLabel()
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels([tr(h) for h in HEADERS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        copy_button = QPushButton(tr(Msg.MEASURE_COPY))
        copy_button.clicked.connect(self.copy_tsv)
        top = QHBoxLayout()
        top.addWidget(self.cursor_label, 1)
        top.addWidget(copy_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.source_label)
        layout.addWidget(self.table)
        # Coalesce bursts (pan/zoom, cursor drags) into one refresh.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(80)
        self._refresh_timer.timeout.connect(self.refresh)
        store.annotations_changed.connect(self.schedule_refresh)
        self._connections: list[tuple[object, object]] = []
        self.refresh()

    def set_dock(self, dock: PlotDock | None) -> None:
        for signal, slot in self._connections:
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(slot)  # type: ignore[attr-defined]
        self._connections = []
        self.dock = dock
        if dock is not None:
            immediate = [dock.plot.config_changed, dock.cursors.changed]
            layer = dock.plot.annotation_layer
            if layer is not None:
                immediate.append(layer.hub.selected)
            for signal in immediate:
                signal.connect(self.refresh)
                self._connections.append((signal, self.refresh))
            # Range changes come in bursts (pan/zoom): coalesced. The view box signal (not
            # PlotWidget.x_range_changed) also fires when another graph's X sync sets it.
            range_signal = dock.plot.subplots[0].view_box.sigXRangeChanged
            range_signal.connect(self.schedule_refresh)
            self._connections.append((range_signal, self.schedule_refresh))
        self.refresh()

    # -- content --------------------------------------------------------------------------

    def interval(self) -> tuple[float, float, str] | None:
        """``(x0, x1, description)`` used for the statistics."""
        if self.dock is None:
            return None
        cursors = self.dock.cursors
        if cursors.enabled:
            return cursors.a, cursors.b, tr(Msg.MEASURE_SOURCE_AB)
        layer = self.dock.plot.annotation_layer
        if layer is not None and layer.selected_id:
            ann = self.store.get(layer.selected_id)
            if ann is not None and ann.kind == "region":
                return ann.x, ann.x2, tr(Msg.MEASURE_SOURCE_REGION).format(text=ann.text)
        lo, hi = self.dock.plot.x_range()
        return lo, hi, tr(Msg.MEASURE_SOURCE_VIEW)

    def rows(self) -> list[list[object]]:
        if self.dock is None:
            return []
        plot, cursors = self.dock.plot, self.dock.cursors
        interval = self.interval()
        assert interval is not None
        x0, x1, _ = interval
        out: list[list[object]] = []
        for curve in plot.config.all_curves():
            if not curve.visible:
                continue
            if cursors.enabled:
                ya = curve_value(plot, curve, cursors.a, "linear")
                yb = curve_value(plot, curve, cursors.b, "linear")
                dy = yb - ya
            else:
                ya = yb = dy = math.nan
            st = curve_stats(plot, curve, x0, x1)
            out.append(
                [
                    plot.series_label(curve),
                    ya,
                    yb,
                    dy,
                    st.min,
                    st.max,
                    st.mean,
                    st.std,
                    st.rms,
                    st.peak_to_peak,
                    st.count,
                ]
            )
        return out

    def schedule_refresh(self, *_args: object) -> None:
        self._refresh_timer.start()

    def refresh(self, *_args: object) -> None:
        if self.dock is None:
            self.cursor_label.setText(tr(Msg.MEASURE_NO_PLOT))
            self.source_label.clear()
            self.table.setRowCount(0)
            return
        cursors = self.dock.cursors
        if cursors.enabled:
            dt = cursors.delta
            self.cursor_label.setText(
                tr(Msg.MEASURE_CURSORS).format(
                    a=format_number(cursors.a),
                    b=format_number(cursors.b),
                    dt=format_number(dt),
                    inv=format_number(1.0 / dt) if dt else "∞",
                )
            )
        else:
            self.cursor_label.setText(self.dock.windowTitle())
        interval = self.interval()
        self.source_label.setText(interval[2] if interval else "")
        rows = self.rows()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                text = format_number(value) if isinstance(value, float) else str(value)
                self.table.setItem(r, c, QTableWidgetItem(text))

    def tsv(self) -> str:
        headers = [tr(h) for h in HEADERS]
        rows = self.rows()
        if self.dock is not None and self.dock.cursors.enabled:
            c = self.dock.cursors
            rows = [["A", c.a, "B", c.b, "Δt", c.delta], *rows]
        return to_tsv(headers, rows)

    def copy_tsv(self) -> None:
        QApplication.clipboard().setText(self.tsv())
