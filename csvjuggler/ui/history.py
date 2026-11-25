"""Undo / redo of the annotations and of the graph settings (Ctrl+Z, Ctrl+Shift+Z / Ctrl+Y).

The history works with snapshots rather than one command per kind of edit: after any change
(annotation store, a graph's config or title), the editable state (every annotation, and the
config and title of every graph) is compared with the last recorded one; if it differs, an
undo step « before → after » is pushed on a plain Python stack (:class:`UndoStack`).
Changes arriving within :data:`COALESCE_MS` form a single step (typing in a spin box, a
burst of config updates), and the pending step is recorded before any undo/redo. Undoing
re-applies a snapshot through the normal APIs (``AnnotationStore.replace_all``,
``PlotWidget.update_config``, ``PlotDock.rename``), so the screen, the panels and the saved
project stay consistent.

Not part of the history: data files, graphs opened or closed (the snapshot of a graph that no
longer exists is skipped), window layout, zoom.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.annotation import Annotation, AnnotationStore
from csvjuggler.model.plot_config import PlotConfig

log = logging.getLogger(__name__)

COALESCE_MS = 400
MAX_STEPS = 200


@dataclass
class Snapshot:
    annotations: list[dict[str, Any]] = field(default_factory=list)
    plots: dict[str, dict[str, Any]] = field(default_factory=dict)
    """dock id → {"title": …, "config": PlotConfig.to_dict()}."""

    def key(self) -> str:
        return json.dumps({"a": self.annotations, "p": self.plots}, sort_keys=True, default=str)


@dataclass
class Step:
    before: Snapshot
    after: Snapshot
    text: str


class UndoStack:
    """Steps and a position, in plain Python.

    (Not ``QUndoStack``: its commands would be Python-created ``QUndoCommand`` objects owned
    by Qt, which PySide then deletes a second time when collecting garbage — segfault.)
    """

    def __init__(self, limit: int = MAX_STEPS) -> None:
        self.steps: list[Step] = []
        self.index = 0
        """Number of steps currently applied."""
        self.limit = limit

    def push(self, step: Step) -> None:
        del self.steps[self.index :]
        self.steps.append(step)
        if len(self.steps) > self.limit:
            del self.steps[0]
        self.index = len(self.steps)

    def clear(self) -> None:
        self.steps.clear()
        self.index = 0

    def count(self) -> int:
        return len(self.steps)

    def canUndo(self) -> bool:
        return self.index > 0

    def canRedo(self) -> bool:
        return self.index < len(self.steps)

    def undoText(self) -> str:
        return self.steps[self.index - 1].text if self.canUndo() else ""

    def redoText(self) -> str:
        return self.steps[self.index].text if self.canRedo() else ""


class EditHistory(QObject):
    changed = Signal()
    """The undo/redo availability or texts changed."""

    def __init__(
        self,
        store: AnnotationStore,
        plots: Callable[[], list[Any]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._plots = plots
        self.stack = UndoStack()
        self._applying = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COALESCE_MS)
        self._timer.timeout.connect(self.commit)
        self._committed = self.snapshot()

    # -- snapshots ------------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        return Snapshot(
            annotations=[a.to_dict() for a in sorted(self.store.all(), key=lambda a: a.id)],
            plots={
                dock.dock_id: {"title": dock.windowTitle(), "config": dock.plot.config.to_dict()}
                for dock in self._plots()
            },
        )

    def apply(self, snap: Snapshot) -> None:
        """Bring annotations and graphs back to ``snap`` (graphs gone since are skipped)."""
        self._applying = True
        try:
            self.store.replace_all([Annotation.from_dict(a) for a in snap.annotations])
            for dock in self._plots():
                state = snap.plots.get(dock.dock_id)
                if state is None:
                    continue
                config = PlotConfig.from_dict(state["config"])
                if config != dock.plot.config:
                    dock.plot.update_config(config)
                if state["title"] != dock.windowTitle():
                    dock.rename(state["title"])
        finally:
            self._applying = False
        self._timer.stop()
        self._committed = self.snapshot()

    # -- recording ------------------------------------------------------------------------

    def schedule(self, *_args: object) -> None:
        """Something editable changed: record it shortly (coalescing bursts)."""
        if not self._applying:
            was_pending = self._timer.isActive()
            self._timer.start()
            if not was_pending:
                self.changed.emit()  # « Annuler » is available as soon as something changed

    def commit(self) -> None:
        """Record the pending change as one undo step (if anything changed)."""
        self._timer.stop()
        after = self.snapshot()
        before = self._committed
        if after.key() == before.key():
            return
        self._committed = after
        self.stack.push(Step(before, after, self._describe(before, after)))
        self.changed.emit()

    def rebase(self) -> None:
        """Restart from the current state without recording what just happened (a graph
        added or removed, a file opened with its annotations). Callers record the user's
        pending edits first with :meth:`commit`."""
        self._timer.stop()
        self._committed = self.snapshot()

    def reset(self) -> None:
        """New project state (layout loaded): forget the history."""
        self._timer.stop()
        self.stack.clear()
        self._committed = self.snapshot()
        self.changed.emit()

    def _describe(self, before: Snapshot, after: Snapshot) -> str:
        if before.annotations != after.annotations:
            return tr(Msg.UNDO_ANNOTATIONS)
        titles = [
            state["title"]
            for dock_id, state in after.plots.items()
            if before.plots.get(dock_id) != state
        ]
        if len(titles) == 1:
            return tr(Msg.UNDO_PLOT).format(name=titles[0])
        return tr(Msg.UNDO_PLOTS)

    # -- user actions ---------------------------------------------------------------------

    def undo(self) -> None:
        self.commit()
        if self.stack.canUndo():
            self.stack.index -= 1
            self.apply(self.stack.steps[self.stack.index].before)
            self.changed.emit()

    def redo(self) -> None:
        self.commit()
        if self.stack.canRedo():
            self.apply(self.stack.steps[self.stack.index].after)
            self.stack.index += 1
            self.changed.emit()

    def can_undo(self) -> bool:
        return self.stack.canUndo() or self._timer.isActive()

    def can_redo(self) -> bool:
        return self.stack.canRedo()
