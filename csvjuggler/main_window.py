"""Main window: menus, series tree on the left, plot docks in the central area."""

from __future__ import annotations

import copy
import itertools
import json
import logging
import math
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path

import pyqtgraph.exporters
from PySide6.QtCore import QByteArray, QPoint, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QPainter,
)
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QGraphicsView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
    QWidget,
)

from csvjuggler.data.dataset import Dataset
from csvjuggler.data.derived import DERIVED_ALIAS, DerivedSeriesConfig, FormulaError
from csvjuggler.data.export import export_csv
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
from csvjuggler.ui.dialogs.derived_dialog import DerivedDialog
from csvjuggler.ui.dialogs.export_dialog import ExportCsvDialog
from csvjuggler.ui.dialogs.import_dialog import ImportDialog
from csvjuggler.ui.measure_panel import MeasurePanel
from csvjuggler.ui.plot_dock import PlotDock
from csvjuggler.ui.progress import run_with_progress
from csvjuggler.ui.series_tree import SeriesTree
from csvjuggler.ui.time_slider import TimeSliderBar
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


def _render_svg(widget: QWidget, path: Path) -> None:
    """Vector rendering of ``widget`` (and its children) into an SVG file."""
    # SVG 1.1 keeps the clip paths (curves clipped to their view boxes; Tiny 1.2 has none),
    # and the widget's DPI keeps text metrics and layout identical to the screen.
    generator = QSvgGenerator(QSvgGenerator.SvgVersion.Svg11)
    generator.setResolution(widget.logicalDpiX())
    generator.setFileName(str(path))
    generator.setSize(widget.size())
    generator.setViewBox(QRectF(0, 0, widget.width(), widget.height()))
    generator.setTitle(tr(Msg.APP_NAME))
    painter = QPainter(generator)
    try:
        if isinstance(widget, QGraphicsView):
            # QGraphicsView.render() is the scene-rendering overload.
            widget.render(
                painter, QRectF(0, 0, widget.width(), widget.height()), widget.viewport().rect()
            )
        else:
            widget.render(painter, QPoint())
    finally:
        painter.end()


class MainWindow(QMainWindow):
    confirm_unsaved = True
    """Ask to save a modified project before closing it (disabled in the test suite)."""

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
        self._saved_snapshot = ""
        self._dirty_timer = QTimer(self)
        self._dirty_timer.setSingleShot(True)
        self._dirty_timer.setInterval(200)
        self._dirty_timer.timeout.connect(self.update_modified)
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

        self.measure_panel = MeasurePanel(session.annotations)
        self.measure_dock = QDockWidget(tr(Msg.DOCK_MEASURES), self)
        self.measure_dock.setObjectName("measure_dock")
        self.measure_dock.setWidget(self.measure_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.measure_dock)
        self.tracker_enabled = False
        self.tracker_mode = "linear"

        self.time_bar = TimeSliderBar()
        self.time_toolbar = QToolBar(tr(Msg.TOOLBAR_SLIDER), self)
        self.time_toolbar.setObjectName("time_toolbar")
        self.time_toolbar.setMovable(False)
        self.time_toolbar.addWidget(self.time_bar)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.time_toolbar)
        self.time_bar.position_changed.connect(self._on_playhead_moved)
        self.time_bar.visibility_changed.connect(self._on_playhead_visibility)
        session.datasets_changed.connect(self._update_time_range)
        session.series_data_changed.connect(self._update_time_range)
        self._build_menus()
        for signal in (
            session.datasets_changed,
            session.series_names_changed,
            session.annotations.annotations_changed,
        ):
            signal.connect(self.schedule_modified_check)
        session.series_data_changed.connect(self._on_series_data_changed)
        session.series_names_changed.connect(self._refresh_all_plots)
        session.datasets_changed.connect(self._refresh_all_plots)
        self.series_tree.context_menu_requested.connect(self._on_tree_menu)
        self.new_plot()
        self.mark_saved()  # an empty window with its default graph is not a modification

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
        window_menu.addSeparator()
        for dock in (self.annotation_dock, self.measure_dock):
            window_menu.addAction(dock.toggleViewAction())
        window_menu.addAction(self.time_toolbar.toggleViewAction())

        measure_menu = self.menuBar().addMenu(tr(Msg.MENU_MEASURE))
        self.tracker_action = QAction(tr(Msg.ACTION_TRACKER), self)
        self.tracker_action.setShortcut(QKeySequence("T"))
        self.tracker_action.setCheckable(True)
        self.tracker_action.toggled.connect(self.set_tracker_enabled)
        measure_menu.addAction(self.tracker_action)
        interp_menu = measure_menu.addMenu(tr(Msg.MENU_INTERPOLATION))
        group = QActionGroup(self)
        for text, mode in ((Msg.INTERP_LINEAR, "linear"), (Msg.INTERP_NEAREST, "nearest")):
            action = interp_menu.addAction(tr(text), partial(self.set_tracker_mode, mode))
            action.setCheckable(True)
            action.setChecked(mode == "linear")
            group.addAction(action)
        ab_action = QAction(tr(Msg.ACTION_AB_CURSORS), self)
        ab_action.setShortcut(QKeySequence("Ctrl+B"))
        ab_action.triggered.connect(self.toggle_current_cursors)
        measure_menu.addAction(ab_action)

        series_menu = self.menuBar().addMenu(tr(Msg.MENU_SERIES))
        series_menu.addAction(tr(Msg.ACTION_NEW_DERIVED), self.new_derived_series)

        export_menu = self.menuBar().addMenu(tr(Msg.MENU_EXPORT))
        export_menu.addAction(tr(Msg.ACTION_EXPORT_PLOT_IMAGE), self._on_export_plot_image)
        export_menu.addAction(tr(Msg.ACTION_EXPORT_WINDOW_IMAGE), self._on_export_window_image)
        copy_image = QAction(tr(Msg.ACTION_COPY_PLOT_IMAGE), self)
        copy_image.setShortcut(QKeySequence("Ctrl+Shift+C"))
        copy_image.triggered.connect(self.copy_plot_image)
        export_menu.addAction(copy_image)
        export_menu.addSeparator()
        export_menu.addAction(tr(Msg.ACTION_EXPORT_CSV), self._on_export_csv)

    # -- plots ----------------------------------------------------------------------------

    def new_plot(
        self,
        config: PlotConfig | None = None,
        dock_id: str | None = None,
        title: str | None = None,
        split_from: PlotDock | None = None,
        orientation: Qt.Orientation = Qt.Orientation.Vertical,
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
        dock.split_requested.connect(self.split_plot)
        dock.plot.config_changed.connect(self.schedule_modified_check)
        dock.title_changed.connect(self.schedule_modified_check)
        self.x_sync.register(dock.plot)
        dock.controller.menu_extensions.append(self._split_menu_extension(dock))
        dock.controller.menu_extensions.append(self.annotations.menu_extension(dock.dock_id))
        if split_from is not None:
            self.plot_area.splitDockWidget(split_from, dock, orientation)
        elif self.plot_docks:
            self.plot_area.splitDockWidget(self.plot_docks[-1], dock, Qt.Orientation.Vertical)
        else:
            self.plot_area.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        self.plot_docks.append(dock)
        self.annotations.register_plot(dock.plot)
        dock.tracker.set_mode(self.tracker_mode)  # type: ignore[arg-type]
        dock.tracker.set_enabled(self.tracker_enabled)
        dock.tracker.moved.connect(lambda x, d=dock: self._on_tracker_moved(d, x))
        dock.playhead.set_mode(self.tracker_mode)  # type: ignore[arg-type]
        dock.playhead.x = self.time_bar.position
        dock.playhead.set_enabled(self.time_bar.cursor_visible)
        self._set_current(dock)
        self.schedule_modified_check()
        return dock

    # -- measurement ----------------------------------------------------------------------

    def set_tracker_enabled(self, enabled: bool) -> None:
        self.tracker_enabled = enabled
        if self.tracker_action.isChecked() != enabled:
            self.tracker_action.setChecked(enabled)
        for dock in self.plot_docks:
            dock.tracker.set_enabled(enabled)

    def set_tracker_mode(self, mode: str) -> None:
        self.tracker_mode = mode
        for dock in self.plot_docks:
            dock.tracker.set_mode(mode)  # type: ignore[arg-type]
            dock.playhead.set_mode(mode)  # type: ignore[arg-type]

    def _on_tracker_moved(self, source: PlotDock, x: float) -> None:
        """The tracker follows the mouse on the synchronised graphs too."""
        peers = set(map(id, self.x_sync.peers(source.plot)))
        for dock in self.plot_docks:
            if id(dock.plot) in peers:
                dock.tracker.set_x(x)

    def _update_time_range(self, *_args: object) -> None:
        self.time_bar.set_range(self.session.x_extent())

    def _on_playhead_visibility(self, visible: bool) -> None:
        for dock in self.plot_docks:
            dock.playhead.x = self.time_bar.position
            dock.playhead.set_enabled(visible)

    def _on_playhead_moved(self, x: float) -> None:
        """The « Lecture X » bar moved: cursor on every graph, views follow if asked."""
        for dock in self.plot_docks:
            dock.playhead.set_x(x)
        if not self.time_bar.follow:
            return
        for dock in self.plot_docks:
            lo, hi = dock.plot.x_range()  # may already have moved through the X sync
            if not lo <= x <= hi:
                width = hi - lo
                dock.plot.subplots[0].view_box.setXRange(x - width / 2, x + width / 2, padding=0)

    def toggle_current_cursors(self) -> None:
        if self.current_dock is not None:
            self.current_dock.cursors_action.toggle()

    def split_plot(self, source: PlotDock, orientation: Qt.Orientation) -> PlotDock:
        """New graph next to ``source`` (right if Horizontal, below if Vertical), X-synced.

        The new graph joins the sync group of ``source``; if ``source`` was not synchronised,
        both join a new named group (other graphs are not affected).
        """
        group = source.plot.config.sync_group
        if not group:
            used = {d.plot.config.sync_group for d in self.plot_docks}
            n = 1
            while tr(Msg.SPLIT_GROUP).format(index=n) in used:
                n += 1
            group = tr(Msg.SPLIT_GROUP).format(index=n)
            source.plot.set_sync_group(group)
        config = PlotConfig(sync_group=group)
        lo, hi = source.plot.x_range()
        if source.isFloating():
            source.setFloating(False)
        dock = self.new_plot(config, split_from=source, orientation=orientation)
        dock.plot.set_x_range(lo, hi)
        return dock

    def _split_menu_extension(self, dock: PlotDock) -> Callable[..., None]:
        def extend(menu: QMenu, *_args: object) -> None:
            menu.addAction(
                tr(Msg.MENU_SPLIT_RIGHT),
                partial(self.split_plot, dock, Qt.Orientation.Horizontal),
            )
            menu.addAction(
                tr(Msg.MENU_SPLIT_DOWN), partial(self.split_plot, dock, Qt.Orientation.Vertical)
            )

        return extend

    def _raise_dock(self, dock_id: str) -> None:
        for dock in self.plot_docks:
            if dock.dock_id == dock_id:
                dock.show()
                dock.raise_()
                self._set_current(dock)

    def _set_current(self, dock: PlotDock | None) -> None:
        if dock is self.current_dock:
            return
        self.current_dock = dock
        self.measure_panel.set_dock(dock)

    def _on_dock_closed(self, dock: PlotDock) -> None:
        if dock in self.plot_docks:
            self.plot_docks.remove(dock)
        self.x_sync.unregister(dock.plot)
        self.annotations.unregister_plot(dock.plot)
        if self.current_dock is dock:
            self._set_current(self.plot_docks[-1] if self.plot_docks else None)
        self.plot_area.removeDockWidget(dock)
        dock.deleteLater()
        self.schedule_modified_check()

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

    # -- derived series -------------------------------------------------------------------

    def new_derived_series(self, preselected: list[str] | None = None) -> None:
        ids = preselected if preselected is not None else self.series_tree.selected_series_ids()
        dialog = DerivedDialog(self.session, preselected=ids, parent=self)
        if dialog.exec() == DerivedDialog.DialogCode.Accepted:
            self._store_derived(dialog.config())

    def edit_derived_series(self, name: str) -> None:
        config = self.session.derived_config(name)
        if config is None:
            return
        dialog = DerivedDialog(self.session, config, parent=self)
        if dialog.exec() == DerivedDialog.DialogCode.Accepted:
            new = dialog.config()
            if new.name != name:
                self.session.remove_derived(name)
            self._store_derived(new)

    def _store_derived(self, config: DerivedSeriesConfig) -> None:
        try:
            self.session.add_derived(config)
        except FormulaError as exc:
            QMessageBox.warning(self, tr(Msg.DERIVED_TITLE), str(exc))

    def _on_tree_menu(self, series_ids: list[str], global_pos: QPoint) -> None:
        self.build_tree_menu(series_ids).exec(global_pos)

    def build_tree_menu(self, series_ids: list[str]) -> QMenu:
        menu = QMenu(self)
        menu.addAction(
            tr(Msg.ACTION_NEW_DERIVED), partial(self.new_derived_series, list(series_ids))
        )
        if len(series_ids) == 1:
            series_id = series_ids[0]
            menu.addAction(
                tr(Msg.ACTION_RENAME_SERIES), partial(self.series_tree.edit_series, series_id)
            )
            alias, _, name = series_id.partition("/")
            if alias == DERIVED_ALIAS:
                menu.addSeparator()
                menu.addAction(tr(Msg.ACTION_EDIT_DERIVED), partial(self.edit_derived_series, name))
                menu.addAction(
                    tr(Msg.ACTION_DELETE_DERIVED), partial(self.session.remove_derived, name)
                )
        return menu

    # -- export ---------------------------------------------------------------------------

    def _require_plot(self) -> PlotDock | None:
        if self.current_dock is None:
            QMessageBox.information(self, tr(Msg.EXPORT_ERROR_TITLE), tr(Msg.EXPORT_NO_PLOT))
        return self.current_dock

    def export_plot_image(self, path: str | Path, dock: PlotDock | None = None) -> Path:
        """PNG or SVG (by extension) of a graph, annotations and secondary axes included."""
        dock = dock or self.current_dock
        if dock is None:
            raise ValueError("no graph")
        path = Path(path)
        if path.suffix.lower() == ".svg":
            # pyqtgraph's SVGExporter cannot parse the SVG paths written by recent Qt
            # versions: render the view through Qt's own SVG generator instead.
            _render_svg(dock.plot, path)
        else:
            # The whole scene: secondary ViewBoxes are top-level scene items.
            pyqtgraph.exporters.ImageExporter(dock.plot.scene()).export(str(path))
        return path

    def export_window_image(self, path: str | Path) -> Path:
        """PNG or SVG of the whole graph area."""
        path = Path(path)
        if path.suffix.lower() == ".svg":
            _render_svg(self.plot_area, path)
        else:
            self.plot_area.grab().save(str(path))
        return path

    def copy_plot_image(self) -> None:
        dock = self._require_plot()
        if dock is not None:
            QApplication.clipboard().setImage(dock.plot.grab().toImage())
            self.statusBar().showMessage(tr(Msg.EXPORT_COPIED), 5000)

    def _ask_image_path(self) -> Path | None:
        path, selected = QFileDialog.getSaveFileName(
            self, tr(Msg.ACTION_EXPORT_PLOT_IMAGE), "", tr(Msg.IMAGE_FILTER)
        )
        if not path:
            return None
        result = Path(path)
        if result.suffix.lower() not in (".png", ".svg"):
            result = result.with_suffix(".svg" if "svg" in selected.lower() else ".png")
        return result

    def _on_export_plot_image(self) -> None:
        if self._require_plot() is None or (path := self._ask_image_path()) is None:
            return
        self._report_export(lambda: self.export_plot_image(path))

    def _on_export_window_image(self) -> None:
        path = self._ask_image_path()
        if path is not None:
            self._report_export(lambda: self.export_window_image(path))

    def _report_export(self, action: Callable[[], Path]) -> None:
        try:
            path = action()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr(Msg.EXPORT_ERROR_TITLE), str(exc))
            return
        self.statusBar().showMessage(tr(Msg.EXPORT_IMAGE_DONE).format(path=path), 5000)

    def export_ranges(self, dock: PlotDock) -> list[tuple[str, float, float]]:
        """Visible range, A/B cursors, selected region: from the least to the most specific."""
        lo, hi = dock.plot.x_range()
        ranges = [(tr(Msg.EXPORT_RANGE_VIEW), lo, hi)]
        if dock.cursors.enabled:
            a, b = sorted((dock.cursors.a, dock.cursors.b))
            ranges.append((tr(Msg.EXPORT_RANGE_AB), a, b))
        layer = dock.plot.annotation_layer
        if layer is not None and layer.selected_id:
            ann = self.session.annotations.get(layer.selected_id)
            if ann is not None and ann.kind == "region":
                ranges.append((f"{tr(Msg.EXPORT_RANGE_REGION)} « {ann.text} »", ann.x, ann.x2))
        return ranges

    def _on_export_csv(self) -> None:
        dock = self._require_plot()
        if dock is None:
            return
        curves = dock.plot.config.all_curves()
        dialog = ExportCsvDialog(
            self.export_ranges(dock),
            [(dock.plot.series_label(c), c.series_id, c.visible) for c in curves],
            self,
        )
        if dialog.exec() != ExportCsvDialog.DialogCode.Accepted:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr(Msg.EXPORT_CSV_TITLE), "", tr(Msg.CSV_FILTER)
        )
        if not path:
            return
        series = [s for sid in dialog.series_ids() if (s := self.session.get_series(sid))]
        x0, x1 = dialog.interval()
        try:
            rows = export_csv(path, series, x0, x1, dialog.options())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr(Msg.EXPORT_ERROR_TITLE), str(exc))
            return
        self.statusBar().showMessage(tr(Msg.EXPORT_DONE).format(rows=rows, path=path), 5000)

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
                menu.addAction(path, partial(self._open_recent_layout, path))

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
            derived=[c.to_dict() for c in self.session.derived],
        )

    def save_layout(self, path: str | Path) -> Path:
        path = with_layout_suffix(path)
        layout = self.current_layout()
        layout.save(path)
        self.layout_path = path
        self.mark_saved(layout)
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
        self.session.set_derived([DerivedSeriesConfig.from_dict(d) for d in layout.derived])
        self._apply_layout_docks(layout)
        self.session.reload_companions()
        self.session.annotations.merge(layout.annotations)

        self.layout_path = path
        self.mark_saved()
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

    def _open_recent_layout(self, path: str) -> None:
        if self.maybe_save():
            self.load_layout(path)

    def _on_open_layout(self) -> None:
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr(Msg.LAYOUT_OPEN_TITLE), "", tr(Msg.LAYOUT_FILTER)
        )
        if path:
            self.load_layout(path)

    def _on_save_layout(self) -> bool:
        if self.layout_path is None:
            return self._on_save_layout_as()
        return self._save_layout_reporting(self.layout_path)

    def _on_save_layout_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, tr(Msg.LAYOUT_SAVE_TITLE), "", tr(Msg.LAYOUT_FILTER)
        )
        return bool(path) and self._save_layout_reporting(Path(path))

    def _save_layout_reporting(self, path: Path) -> bool:
        try:
            self.save_layout(path)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr(Msg.LAYOUT_ERROR_TITLE),
                tr(Msg.LAYOUT_SAVE_ERROR_TEXT).format(path=path, error=exc),
            )
            return False
        return True

    # -- unsaved changes ------------------------------------------------------------------

    def _snapshot(self, layout: Layout | None = None) -> str:
        """What a save would write, minus the window geometry (moving docks is not a change)."""
        data = (layout or self.current_layout()).to_dict()
        data.pop("dock_state", None)
        data.pop("window_state", None)
        return json.dumps(data, sort_keys=True, default=str)

    def mark_saved(self, layout: Layout | None = None) -> None:
        self._dirty_timer.stop()
        self._saved_snapshot = self._snapshot(layout)
        self.update_modified()

    def schedule_modified_check(self, *_args: object) -> None:
        self._dirty_timer.start()

    def is_modified(self) -> bool:
        return self._snapshot() != self._saved_snapshot

    def update_modified(self) -> None:
        name = self.layout_path.name if self.layout_path else tr(Msg.UNTITLED_PROJECT)
        self.setWindowTitle(tr(Msg.WINDOW_TITLE).format(name=name))
        self.setWindowModified(self.is_modified())

    def maybe_save(self) -> bool:
        """Before closing the project: offer to save it. False = the user cancelled."""
        if not self.confirm_unsaved or not self.is_modified():
            return True
        name = self.layout_path.name if self.layout_path else tr(Msg.UNTITLED_PROJECT)
        buttons = (
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        answer = QMessageBox.question(
            self,
            tr(Msg.UNSAVED_TITLE),
            tr(Msg.UNSAVED_TEXT).format(name=name),
            buttons,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._on_save_layout()
        return answer == QMessageBox.StandardButton.Discard

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
        if not self.maybe_save():
            event.ignore()
            return
        log.debug("Main window closing")
        if self._companion_timer.isActive():
            self._companion_timer.stop()
            self.session.save_companions()
        super().closeEvent(event)
