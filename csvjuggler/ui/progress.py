"""Run a long function in a worker thread behind a progress dialog, without freezing the UI.

The caller is blocked in a local event loop, so code stays sequential while the UI keeps
processing events (repaints, cancel button).

The worker is a plain Python thread (``concurrent.futures``) that never touches a Qt object:
it only writes its progress into a shared value, which a GUI timer reads.

Python's cyclic garbage collector runs in whichever thread happens to allocate. Run in the
worker (pandas allocates a lot), it would destroy Qt objects left in reference cycles by
closed windows or dialogs — from a non-GUI thread, which deadlocks or crashes now and then.
So garbage is collected in the GUI thread just before starting, and automatic collection is
paused while the worker runs.
"""

from __future__ import annotations

import gc
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget

from csvjuggler.i18n import Msg, tr

T = TypeVar("T")

POLL_MS = 30


class _Progress:
    """Shared between the worker (writes) and the GUI timer (reads): plain attributes."""

    def __init__(self) -> None:
        self.fraction = 0.0
        self.cancelled = False

    def report(self, fraction: float) -> bool:
        self.fraction = fraction
        return not self.cancelled


def run_with_progress(
    parent: QWidget | None, label: str, fn: Callable[[Callable[[float], bool]], T]
) -> T:
    """Run ``fn(report)`` in a worker thread; ``report(fraction)`` returns False if cancelled.

    Exceptions raised by ``fn`` are re-raised in the calling thread.
    """
    progress = _Progress()
    dialog = QProgressDialog(label, tr(Msg.CANCEL), 0, 1000, parent)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(400)
    dialog.setAutoClose(False)
    dialog.canceled.connect(lambda: setattr(progress, "cancelled", True))

    gc.collect()  # Qt objects in garbage cycles are destroyed here, in the GUI thread
    gc_was_enabled = gc.isenabled()
    gc.disable()  # …and never by a collection started in the worker thread
    try:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="csvjuggler-import")
        future = executor.submit(fn, progress.report)
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(POLL_MS)

        def poll() -> None:
            if future.done():
                loop.quit()
            else:
                dialog.setValue(int(progress.fraction * 1000))

        timer.timeout.connect(poll)
        timer.start()
        if not future.done():
            loop.exec()  # the timer keeps polling: a result arriving now still ends the loop
        timer.stop()
        executor.shutdown(wait=True)
    finally:
        if gc_was_enabled:
            gc.enable()
    dialog.close()
    dialog.deleteLater()
    return future.result()  # re-raises the worker's exception, if any
