"""pyqtgraph items customised for CsvJuggler: view box and axes with our own menus/formats."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal

from csvjuggler.model.plot_config import AxisConfig


class PlotViewBox(pg.ViewBox):
    """ViewBox whose right-click and double-click are handled by the application."""

    menu_requested = Signal(object)
    """Right click: the pyqtgraph MouseClickEvent."""
    double_clicked = Signal(object)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.secondary_views: list[pg.ViewBox] = []
        """Secondary-axis views (X-linked): their X extent counts for the automatic X range."""

    def childrenBounds(self, frac=None, orthoRange=(None, None), items=None):
        bounds = super().childrenBounds(frac=frac, orthoRange=orthoRange, items=items)
        if items is None:
            for view in self.secondary_views:
                x_range = view.childrenBounds(frac=frac)[0]
                if x_range is None:
                    continue
                if bounds[0] is None:
                    bounds[0] = [x_range[0], x_range[1]]
                else:
                    bounds[0] = [min(bounds[0][0], x_range[0]), max(bounds[0][1], x_range[1])]
        return bounds

    def mouseClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            self.menu_requested.emit(ev)
            return
        if ev.button() == Qt.MouseButton.LeftButton and ev.double():
            ev.accept()
            self.double_clicked.emit(ev)
            return
        super().mouseClickEvent(ev)


def format_ticks(values: list[float], scale: float, fmt: AxisConfig) -> list[str] | None:
    """Tick labels for ``fmt``; ``None`` → use pyqtgraph's default formatting."""
    if fmt.decimals is None and not fmt.scientific and not fmt.si_prefix:
        return None
    out: list[str] = []
    for value in values:
        v = value * scale
        if fmt.scientific:
            out.append(f"{v:.{2 if fmt.decimals is None else fmt.decimals}e}")
        elif fmt.si_prefix:
            precision = 3 if fmt.decimals is None else fmt.decimals + 1
            out.append(pg.siFormat(v, precision=precision).strip())
        else:
            out.append(f"{v:.{fmt.decimals}f}")
    return out


class FormattedAxis(pg.AxisItem):
    """Axis with configurable tick format, context menu and double-click."""

    menu_requested = Signal(str, QPointF)
    """``(axis_id, screen position)``."""
    double_clicked = Signal(str)

    def __init__(self, orientation: str, axis_id: str) -> None:
        super().__init__(orientation)
        self.axis_id = axis_id
        self.fmt = AxisConfig(axis_id=axis_id)
        self.enableAutoSIPrefix(False)

    def set_format(self, fmt: AxisConfig) -> None:
        self.fmt = fmt
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):
        if self.logMode:
            return super().tickStrings(values, scale, spacing)
        return format_ticks(values, scale, self.fmt) or super().tickStrings(values, scale, spacing)

    def mouseClickEvent(self, ev) -> None:
        if _handle_axis_click(self, ev):
            return
        super().mouseClickEvent(ev)


class DateAxis(pg.DateAxisItem):
    """Absolute date/time X axis (values are seconds since the epoch)."""

    menu_requested = Signal(str, QPointF)
    double_clicked = Signal(str)

    def __init__(self, orientation: str, axis_id: str) -> None:
        super().__init__(orientation, utcOffset=0)
        self.axis_id = axis_id

    def set_format(self, fmt: AxisConfig) -> None:
        """Date axes use their own formatting."""

    def mouseClickEvent(self, ev) -> None:
        if _handle_axis_click(self, ev):
            return
        super().mouseClickEvent(ev)


def _handle_axis_click(axis: FormattedAxis | DateAxis, ev) -> bool:
    if ev.button() == Qt.MouseButton.RightButton:
        ev.accept()
        axis.menu_requested.emit(axis.axis_id, ev.screenPos())
        return True
    if ev.button() == Qt.MouseButton.LeftButton and ev.double():
        ev.accept()
        axis.double_clicked.emit(axis.axis_id)
        return True
    return False
