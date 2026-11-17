"""Run a long function in a QThread behind a progress dialog, without freezing the UI.

The caller is blocked in a local event loop, so code stays sequential while the UI keeps
processing events (repaints, cancel button).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QProgressDialog, QWidget

from csvjuggler.i18n import Msg, tr

T = TypeVar("T")


class _Worker(QObject):
    progress_changed = Signal(float)
    finished = Signal(object, object)  # result, exception

    def __init__(self, fn: Callable[[Callable[[float], bool]], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.cancelled = False

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn(self._report)
        except BaseException as exc:  # forwarded to the caller's thread
            self.finished.emit(None, exc)
        else:
            self.finished.emit(result, None)

    def _report(self, fraction: float) -> bool:
        self.progress_changed.emit(fraction)
        return not self.cancelled


class _Receiver(QObject):
    """Lives in the GUI thread so that worker signals are queued to it."""

    def __init__(self, dialog: QProgressDialog, loop: QEventLoop) -> None:
        super().__init__()
        self.dialog = dialog
        self.loop = loop
        self.result: Any = None
        self.error: BaseException | None = None

    @Slot(float)
    def on_progress(self, fraction: float) -> None:
        self.dialog.setValue(int(fraction * 1000))

    @Slot(object, object)
    def on_finished(self, result: Any, error: BaseException | None) -> None:
        self.result, self.error = result, error
        self.loop.quit()


def run_with_progress(
    parent: QWidget | None, label: str, fn: Callable[[Callable[[float], bool]], T]
) -> T:
    """Run ``fn(report)`` in a worker thread; ``report(fraction)`` returns False if cancelled.

    Exceptions raised by ``fn`` are re-raised in the calling thread.
    """
    dialog = QProgressDialog(label, tr(Msg.CANCEL), 0, 1000, parent)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(400)
    dialog.setAutoClose(False)
    loop = QEventLoop()
    receiver = _Receiver(dialog, loop)
    worker = _Worker(fn)
    thread = QThread()
    worker.moveToThread(thread)
    worker.progress_changed.connect(receiver.on_progress)
    worker.finished.connect(receiver.on_finished)
    dialog.canceled.connect(lambda: setattr(worker, "cancelled", True))
    thread.started.connect(worker.run)
    thread.start()
    loop.exec()
    thread.quit()
    thread.wait()
    dialog.close()
    dialog.deleteLater()
    if receiver.error is not None:
        raise receiver.error
    return receiver.result
