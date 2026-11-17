"""Main window: menus, series tree on the left, plot docks in the central area."""

from __future__ import annotations

import copy
import itertools
import logging
import math
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QWidget,
)

from csvjuggler.data.dataset import Dataset
from csvjuggler.data.importer import (
    CsvImportCancelled,
    CsvImportError,
    ImportSettings,
    ProgressCallback,
    analyze,
    default_alias,
    load_csv,
)
from csvjuggler.i18n import Msg, tr
from csvjuggler.model.layout import (
    DatasetRef,
    DockConfig,
    Layout,
    LayoutError,
    with_layout_suffix,
)
from csvjuggler.model.plot_config import PlotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.annotation_items import AnnotationManager
from csvjuggler.ui.annotation_panel import AnnotationPanel
from csvjuggler.ui.dialogs.annotation_dialog import edit_annotation
from csvjuggler.ui.dialogs.import_dialog import ImportDialog
from csvjuggler.ui.plot_dock import PlotDock
from csvjuggler.ui.progress import run_with_progress
from csvjuggler.ui.series_tree import SeriesTree
from csvjuggler.ui.x_sync import XSyncManager

log = logging.getLogger(__name__)

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
MAX_RECENT = 10
KEY_RECENT_FILES = "recent_files"
KEY_RECENT_LAYOUTS = "recent_layouts"
KEY_LAST_LAYOUT = "last_layout"


def _csv_paths(urls: Iterable) -> list[Path]:
    paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
    return [p for p in paths if p.suffix.lower() in CSV_SUFFIXES]


def _load(
    path: Path, settings: ImportSettings | None, alias: str, report: ProgressCallback
) -> Dataset:
    return load_csv(path, settings, alias, report)


class MainWindow(QMainWindow):
    def __init__(
        self,
        session: Session,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.settings = settings if settings is not None else QSettings()
        self.layout_path: Path | None = None
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
        self.layout_extensions: list[Callable[[Layout], None]] = []
        """Called after a layout is applied (derived series…)."""
        self.plot_docks: list[PlotDock] = []
        self.current_dock: PlotDock | None = None
        self.x_sync = XSyncManager(self)

        self.annotations = AnnotationManager(
            session,
            lambda: [(d.dock_id, d.plot) for d in self.plot_docks],
            self,
            edit_dialog=edit_annotation,
        )
        self.annotations.focus_requested.connect(self._raise_dock)
        self.annotation_panel = AnnotationPanel(self.annotations)
        self.annotation_dock = QDockWidget(tr(Msg.DOCK_ANNOTATIONS), self)
        self.annotation_dock.setObjectName("annotation_dock")
        self.annotation_dock.setWidget(self.annotation_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.annotation_dock)
        # Companion files are written shortly after the last change.
        self._companion_timer = QTimer(self)
        self._companion_timer.setSingleShot(True)
        self._companion_timer.setInterval(500)
        self._companion_timer.timeout.connect(session.save_companions)
        session.annotations.annotations_changed.connect(self._companion_timer.start)
        self._build_menus()
        session.series_data_changed.connect(self._on_series_data_changed)
        session.series_names_changed.connect(self._refresh_all_plots)
        session.datasets_changed.connect(self._refresh_all_plots)
        self.new_plot()

    # -- menus ----------------------------------------------------------------------------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(tr(Msg.MENU_FILE))
        open_action = QAction(tr(Msg.ACTION_OPEN), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_open)
        file_menu.addAction(open_action)
        reload_action = QAction(tr(Msg.ACTION_RELOAD), self)
        reload_action.setShortcut(QKeySequence("Ctrl+R"))
        reload_action.triggered.connect(self.reload_all)
        file_menu.addAction(reload_action)
        self.recent_files_menu = file_menu.addMenu(tr(Msg.MENU_RECENT_FILES))
        self.recent_files_menu.aboutToShow.connect(
            lambda: self._fill_recent(self.recent_files_menu, KEY_RECENT_FILES)
        )
        file_menu.addSeparator()
        open_layout = QAction(tr(Msg.ACTION_OPEN_LAYOUT), self)
        open_layout.setShortcut(QKeySequence("Ctrl+L"))
        open_layout.triggered.connect(self._on_open_layout)
        file_menu.addAction(open_layout)
        save_layout = QAction(tr(Msg.ACTION_SAVE_LAYOUT), self)
        save_layout.setShortcut(QKeySequence.StandardKey.Save)
        save_layout.triggered.connect(self._on_save_layout)
        file_menu.addAction(save_layout)
        save_layout_as = QAction(tr(Msg.ACTION_SAVE_LAYOUT_AS), self)
        save_layout_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_layout_as.triggered.connect(self._on_save_layout_as)
        file_menu.addAction(save_layout_as)
        self.recent_layouts_menu = file_menu.addMenu(tr(Msg.MENU_RECENT_LAYOUTS))
        self.recent_layouts_menu.aboutToShow.connect(
            lambda: self._fill_recent(self.recent_layouts_menu, KEY_RECENT_LAYOUTS)
        )
        file_menu.addSeparator()
        quit_action = QAction(tr(Msg.ACTION_QUIT), self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        window_menu = self.menuBar().addMenu(tr(Msg.MENU_WINDOW))
        new_action = QAction(tr(Msg.ACTION_NEW_PLOT), self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.new_plot)
        window_menu.addAction(new_action)
        window_menu.addAction(tr(Msg.ACTION_TILE), self.tile_plots)
        window_menu.addAction(tr(Msg.ACTION_CLOSE_ALL), self.close_all_plots)

    # -- plots ----------------------------------------------------------------------------

    def new_plot(
        self, config: PlotConfig | None = None, dock_id: str | None = None, title: str | None = None
    ) -> PlotDock:
        self._plot_counter += 1
        while dock_id is None or any(d.dock_id == dock_id for d in self.plot_docks):
            dock_id = f"plot_{self._plot_counter}"
            self._plot_counter += 1
        dock = PlotDock(
            self.session,
            dock_id=dock_id,
            title=title or tr(Msg.DOCK_PLOT).format(index=len(self.plot_docks) + 1),
            config=config,
            parent=self.plot_area,
        )
        dock.plot.missing_series_changed.connect(self._on_missing_series)
        dock.plot.activated.connect(lambda d=dock: self._set_current(d))
        dock.closed.connect(self._on_dock_closed)
        self.x_sync.register(dock.plot)
        dock.controller.menu_extensions.append(self.annotations.menu_extension(dock.dock_id))
        if self.plot_docks:
            self.plot_area.splitDockWidget(self.plot_docks[-1], dock, Qt.Orientation.Vertical)
        else:
            self.plot_area.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        self.plot_docks.append(dock)
        self.annotations.register_plot(dock.plot)
        self._set_current(dock)
        return dock

    def _raise_dock(self, dock_id: str) -> None:
        for dock in self.plot_docks:
            if dock.dock_id == dock_id:
                dock.show()
                dock.raise_()
                self._set_current(dock)

    def _set_current(self, dock: PlotDock) -> None:
        self.current_dock = dock

    def _on_dock_closed(self, dock: PlotDock) -> None:
        if dock in self.plot_docks:
            self.plot_docks.remove(dock)
        self.x_sync.unregister(dock.plot)
        self.annotations.unregister_plot(dock.plot)
        if self.current_dock is dock:
            self.current_dock = self.plot_docks[-1] if self.plot_docks else None
        self.plot_area.removeDockWidget(dock)
        dock.deleteLater()

    def close_all_plots(self) -> None:
        for dock in list(self.plot_docks):
            dock.close()

    def tile_plots(self) -> None:
        """Arrange all graphs in a grid (columns first)."""
        docks = list(self.plot_docks)
        if not docks:
            return
        cols = math.ceil(math.sqrt(len(docks)))
        for dock in docks:
            dock.setFloating(False)
            self.plot_area.removeDockWidget(dock)
        columns = [docks[c::cols] for c in range(cols)]
        heads = [col[0] for col in columns]
        self.plot_area.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, heads[0])
        for prev, head in itertools.pairwise(heads):
            self.plot_area.splitDockWidget(prev, head, Qt.Orientation.Horizontal)
        for col in columns:
            for prev, dock in itertools.pairwise(col):
                self.plot_area.splitDockWidget(prev, dock, Qt.Orientation.Vertical)
        for dock in docks:
            dock.show()

    def _on_missing_series(self, missing: list[str]) -> None:
        for series_id in missing:
            self.statusBar().showMessage(
                tr(Msg.STATUS_MISSING_SERIES).format(series_id=series_id), 5000
            )

    # -- import ---------------------------------------------------------------------------

    def open_files(self, paths: Iterable[str | Path], interactive: bool = True) -> None:
        """Import CSV files. ``interactive`` shows the import dialog for each file."""
        for path in paths:
            path = Path(path)
            try:
                request = self._import_request(path, interactive)
                if request is None:
                    continue
                settings, alias = request
                alias = self.session.unique_alias(alias)
                dataset = run_with_progress(
                    self,
                    tr(Msg.PROGRESS_IMPORT).format(name=path.name),
                    partial(_load, path, settings, alias),
                )
            except CsvImportCancelled:
                continue
            except CsvImportError as exc:
                self._import_error(path, exc)
                continue
            self.session.add_dataset(dataset)
            self._push_recent(KEY_RECENT_FILES, path)
            self.statusBar().showMessage(
                tr(Msg.STATUS_LOADED).format(
                    alias=dataset.alias,
                    count=len(dataset.series),
                    points=dataset.point_count,
                ),
                5000,
            )

    def _import_request(
        self, path: Path, interactive: bool
    ) -> tuple[ImportSettings | None, str] | None:
        """Settings and alias for ``path``; ``None`` if the user cancelled the dialog."""
        if not interactive:
            return None, default_alias(path)
        preview = analyze(path)
        dialog = ImportDialog(path, default_alias(path), preview, self)
        if dialog.exec() != ImportDialog.DialogCode.Accepted:
            return None
        return dialog.settings(), dialog.alias() or default_alias(path)

    def _import_error(self, path: Path, exc: Exception) -> None:
        log.error("Import failed for %s: %s", path, exc)
        QMessageBox.warning(
            self,
            tr(Msg.IMPORT_ERROR_TITLE),
            tr(Msg.IMPORT_ERROR_TEXT).format(path=path, error=exc),
        )

    def reload_all(self) -> None:
        """Re-read every file with its import settings; graphs are kept."""
        count = 0
        for dataset in self.session.datasets:
            if dataset.path is None:
                continue
            try:
                fresh = run_with_progress(
                    self,
                    tr(Msg.PROGRESS_RELOAD).format(name=dataset.path.name),
                    partial(_load, dataset.path, dataset.import_settings, dataset.alias),
                )
            except CsvImportCancelled:
                continue
            except CsvImportError as exc:
                self._import_error(dataset.path, exc)
                continue
            self.session.replace_data(dataset.alias, fresh)
            count += 1
        self.statusBar().showMessage(tr(Msg.STATUS_RELOADED).format(count=count), 5000)

    def _on_series_data_changed(self, _alias: str) -> None:
        for dock in self.plot_docks:
            dock.plot.refresh_data()

    def _refresh_all_plots(self) -> None:
        for dock in self.plot_docks:
            dock.plot.apply_config(dock.plot.config)

    def _on_open(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr(Msg.OPEN_DIALOG_TITLE), "", tr(Msg.OPEN_DIALOG_FILTER)
        )
        self.open_files(paths)

    # -- recent files ---------------------------------------------------------------------

    def recent(self, key: str) -> list[str]:
        value = self.settings.value(key, [])
        if isinstance(value, str):  # QSettings returns a str for one-element lists
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value]
        return []

    def _push_recent(self, key: str, path: str | Path) -> None:
        path = str(Path(path).resolve())
        items = [path] + [p for p in self.recent(key) if p != path]
        self.settings.setValue(key, items[:MAX_RECENT])

    def _fill_recent(self, menu: QMenu, key: str) -> None:
        menu.clear()
        items = self.recent(key)
        if not items:
            menu.addAction(tr(Msg.RECENT_EMPTY)).setEnabled(False)
        for path in items:
            if key == KEY_RECENT_FILES:
                menu.addAction(path, partial(self.open_files, [path]))
            else:
                menu.addAction(path, partial(self.load_layout, path))

    # -- layouts --------------------------------------------------------------------------

    def current_layout(self) -> Layout:
        """Snapshot of the session: what is on screen is what gets saved."""
        return Layout(
            datasets=[
                DatasetRef(ds.alias, str(ds.path), copy.deepcopy(ds.import_settings))
                for ds in self.session.datasets
                if ds.path is not None and ds.import_settings is not None
            ],
            docks=[
                DockConfig(d.dock_id, d.windowTitle(), copy.deepcopy(d.plot.config))
                for d in self.plot_docks
            ],
            dock_state=bytes(self.plot_area.saveState().toBase64().data()).decode("ascii"),
            window_state=bytes(self.saveState().toBase64().data()).decode("ascii"),
            annotations=self.session.annotations.all(),
        )

    def save_layout(self, path: str | Path) -> Path:
        path = with_layout_suffix(path)
        self.current_layout().save(path)
        self.layout_path = path
        self._push_recent(KEY_RECENT_LAYOUTS, path)
        self.settings.setValue(KEY_LAST_LAYOUT, str(path.resolve()))
        self.statusBar().showMessage(tr(Msg.STATUS_LAYOUT_SAVED).format(path=path), 5000)
        return path

    def load_layout(
        self,
        path: str | Path,
        file_overrides: Iterable[str | Path] = (),
        interactive: bool = True,
    ) -> list[str]:
        """Apply a layout. ``file_overrides`` replace the layout's files, in order.

        Missing files/series never block: they are reported. Returns the missing series ids.
        """
        path = Path(path)
        try:
            layout = Layout.load(path)
        except LayoutError as exc:
            log.error("Cannot load layout %s: %s", path, exc)
            if interactive:
                QMessageBox.warning(
                    self,
                    tr(Msg.LAYOUT_ERROR_TITLE),
                    tr(Msg.LAYOUT_ERROR_TEXT).format(path=path, error=exc),
                )
            return []
        overrides = [Path(p) for p in file_overrides]
        self._load_layout_datasets(layout, path.parent, overrides, interactive)
        if len(overrides) > len(layout.datasets):
            self.open_files(overrides[len(layout.datasets) :], interactive=False)
        self._apply_layout_docks(layout)
        self.session.reload_companions()
        self.session.annotations.merge(layout.annotations)
        for extension in self.layout_extensions:
            extension(layout)

        self.layout_path = path
        self._push_recent(KEY_RECENT_LAYOUTS, path)
        self.settings.setValue(KEY_LAST_LAYOUT, str(path.resolve()))
        missing = self.session.missing_series(layout.series_ids())
        if missing:
            log.warning("Layout %s: missing series %s", path, ", ".join(missing))
            self.statusBar().showMessage(
                tr(Msg.STATUS_LAYOUT_MISSING).format(count=len(missing)), 10000
            )
            if interactive:
                QMessageBox.information(
                    self,
                    tr(Msg.LAYOUT_MISSING_SERIES_TITLE),
                    tr(Msg.LAYOUT_MISSING_SERIES_TEXT).format(ids="\n".join(missing)),
                )
        else:
            self.statusBar().showMessage(tr(Msg.STATUS_LAYOUT_LOADED).format(name=path.name), 5000)
        return missing

    def _load_layout_datasets(
        self, layout: Layout, layout_dir: Path, overrides: list[Path], interactive: bool
    ) -> None:
        for i, ref in enumerate(layout.datasets):
            source: Path | None
            if i < len(overrides):
                source = overrides[i]
            elif self.session.dataset(ref.alias) is not None:
                continue  # already loaded under that alias: keep it
            else:
                source = next((p for p in ref.candidate_paths(layout_dir) if p.is_file()), None)
                if source is None and interactive:
                    source = self._ask_replacement(ref)
            if source is None:
                log.warning("Layout dataset %r: file not found (%s)", ref.alias, ref.path)
                continue
            try:
                fresh = run_with_progress(
                    self,
                    tr(Msg.PROGRESS_IMPORT).format(name=source.name),
                    partial(_load, source, copy.deepcopy(ref.import_settings), ref.alias),
                )
            except CsvImportCancelled:
                continue
            except CsvImportError as exc:
                if interactive:
                    self._import_error(source, exc)
                else:
                    log.error("Import failed for %s: %s", source, exc)
                continue
            if self.session.dataset(ref.alias) is not None:
                self.session.replace_data(ref.alias, fresh)
            else:
                self.session.add_dataset(fresh)

    def _ask_replacement(self, ref: DatasetRef) -> Path | None:
        answer = QMessageBox.question(
            self,
            tr(Msg.LAYOUT_MISSING_FILE_TITLE),
            tr(Msg.LAYOUT_MISSING_FILE_TEXT).format(alias=ref.alias, path=ref.path),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr(Msg.LAYOUT_PICK_FILE).format(alias=ref.alias),
            "",
            tr(Msg.OPEN_DIALOG_FILTER),
        )
        return Path(path) if path else None

    def _apply_layout_docks(self, layout: Layout) -> None:
        for dock in list(self.plot_docks):
            dock.close()
        for dock_cfg in layout.docks:
            self.new_plot(copy.deepcopy(dock_cfg.plot), dock_cfg.dock_id, dock_cfg.title)
        if layout.dock_state:
            self.plot_area.restoreState(QByteArray.fromBase64(layout.dock_state.encode("ascii")))
        if layout.window_state:
            self.restoreState(QByteArray.fromBase64(layout.window_state.encode("ascii")))
        for dock in self.plot_docks:
            dock.plot.auto_range()

    def _on_open_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr(Msg.LAYOUT_OPEN_TITLE), "", tr(Msg.LAYOUT_FILTER)
        )
        if path:
            self.load_layout(path)

    def _on_save_layout(self) -> None:
        if self.layout_path is None:
            self._on_save_layout_as()
        else:
            self._save_layout_reporting(self.layout_path)

    def _on_save_layout_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr(Msg.LAYOUT_SAVE_TITLE), "", tr(Msg.LAYOUT_FILTER)
        )
        if path:
            self._save_layout_reporting(Path(path))

    def _save_layout_reporting(self, path: Path) -> None:
        try:
            self.save_layout(path)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr(Msg.LAYOUT_ERROR_TITLE),
                tr(Msg.LAYOUT_SAVE_ERROR_TEXT).format(path=path, error=exc),
            )

    def restore_last_layout(self) -> bool:
        """Startup: reload the last saved/opened layout, without dialogs."""
        last = self.settings.value(KEY_LAST_LAYOUT, "")
        if last and Path(str(last)).is_file():
            self.load_layout(str(last), interactive=False)
            return True
        return False

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
        if self._companion_timer.isActive():
            self._companion_timer.stop()
            self.session.save_companions()
        super().closeEvent(event)
