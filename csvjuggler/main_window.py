"""Main window: menus, series tree on the left, plot docks in the central area."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QMessageBox, QWidget

from csvjuggler.data.importer import CsvImportError
from csvjuggler.i18n import Msg, tr
from csvjuggler.model.session import Session
from csvjuggler.ui.plot_dock import PlotDock
from csvjuggler.ui.series_tree import SeriesTree

log = logging.getLogger(__name__)

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}


def _csv_paths(urls: Iterable) -> list[Path]:
    paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
    return [p for p in paths if p.suffix.lower() in CSV_SUFFIXES]


class MainWindow(QMainWindow):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(tr(Msg.APP_NAME))
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        # Plot docks live in an inner QMainWindow so they never mix with the side panels.
        self.plot_area = QMainWindow(self)
        self.plot_area.setWindowFlags(Qt.WindowType.Widget)
        self.plot_area.setDockNestingEnabled(True)
        self.plot_area.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
        )
        self.setCentralWidget(self.plot_area)

        self.series_tree = SeriesTree(session)
        tree_dock = QDockWidget(tr(Msg.DOCK_SERIES), self)
        tree_dock.setObjectName("series_tree_dock")
        tree_dock.setWidget(self.series_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tree_dock)

        self._plot_counter = 0
        self.plot_docks: list[PlotDock] = []
        self._build_menus()
        self.new_plot()

    # -- menus ----------------------------------------------------------------------------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(tr(Msg.MENU_FILE))
        open_action = QAction(tr(Msg.ACTION_OPEN), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        quit_action = QAction(tr(Msg.ACTION_QUIT), self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # -- plots ----------------------------------------------------------------------------

    def new_plot(self) -> PlotDock:
        self._plot_counter += 1
        dock = PlotDock(
            self.session,
            dock_id=f"plot_{self._plot_counter}",
            title=tr(Msg.DOCK_PLOT).format(index=self._plot_counter),
            parent=self.plot_area,
        )
        dock.plot.missing_series_changed.connect(self._on_missing_series)
        self.plot_area.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        self.plot_docks.append(dock)
        return dock

    def _on_missing_series(self, missing: list[str]) -> None:
        for series_id in missing:
            self.statusBar().showMessage(
                tr(Msg.STATUS_MISSING_SERIES).format(series_id=series_id), 5000
            )

    # -- import ---------------------------------------------------------------------------

    def open_files(self, paths: Iterable[str | Path]) -> None:
        for path in paths:
            try:
                dataset = self.session.load_csv(path)
            except CsvImportError as exc:
                log.error("Import failed for %s: %s", path, exc)
                QMessageBox.warning(
                    self,
                    tr(Msg.IMPORT_ERROR_TITLE),
                    tr(Msg.IMPORT_ERROR_TEXT).format(path=path, error=exc),
                )
                continue
            self.statusBar().showMessage(
                tr(Msg.STATUS_LOADED).format(
                    alias=dataset.alias,
                    count=len(dataset.series),
                    points=dataset.point_count,
                ),
                5000,
            )

    def _on_open(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr(Msg.OPEN_DIALOG_TITLE), "", tr(Msg.OPEN_DIALOG_FILTER)
        )
        self.open_files(paths)

    # -- drop of CSV files on the window --------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and _csv_paths(event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _csv_paths(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self.open_files(paths)

    def closeEvent(self, event: QCloseEvent) -> None:
        log.debug("Main window closing")
        super().closeEvent(event)
