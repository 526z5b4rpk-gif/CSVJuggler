"""Synchronisation of the X range between graphs sharing a sync group."""

from __future__ import annotations

from PySide6.QtCore import QObject

from csvjuggler.ui.plot_widget import PlotWidget


class XSyncManager(QObject):
    """Propagates X range changes to every graph of the same (non-empty) sync group."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plots: list[PlotWidget] = []
        self._propagating = False

    def register(self, plot: PlotWidget) -> None:
        self._plots.append(plot)
        plot.x_range_changed.connect(lambda lo, hi, p=plot: self._on_changed(p, lo, hi))

    def unregister(self, plot: PlotWidget) -> None:
        if plot in self._plots:
            self._plots.remove(plot)

    def peers(self, plot: PlotWidget) -> list[PlotWidget]:
        group = plot.config.sync_group
        if not group:
            return []
        return [p for p in self._plots if p is not plot and p.config.sync_group == group]

    def _on_changed(self, source: PlotWidget, lo: float, hi: float) -> None:
        if self._propagating:
            return
        self._propagating = True
        try:
            for plot in self.peers(source):
                plot.set_x_range(lo, hi)
        finally:
            self._propagating = False
