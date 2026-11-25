"""A dock holding one graph and its local toolbar."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QScreen, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
    QInputDialog,
    QMenu,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.plot_config import PlotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.cursors import PLAYHEAD_PEN, ABCursors, Tracker, ValueCursor
from csvjuggler.ui.plot_menus import PlotController
from csvjuggler.ui.plot_widget import PlotWidget


class PlotDock(QDockWidget):
    closed = Signal(object)
    """Emitted with the dock when the user closes it."""
    title_changed = Signal(str)
    split_requested = Signal(object, object)
    """``(dock, Qt.Orientation)``: Horizontal → new graph on the right, Vertical → below."""

    def __init__(
        self,
        session: Session,
        dock_id: str,
        title: str,
        config: PlotConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setObjectName(dock_id)  # stable name, needed by QMainWindow.saveState
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.plot = PlotWidget(session, config)
        self.controller = PlotController(self.plot, self)
        self.tracker = Tracker(self.plot)
        self.playhead = ValueCursor(self.plot, PLAYHEAD_PEN, label_at_bottom=True, z=61)
        """Cursor driven by the « Lecture X » bar."""
        self.cursors = ABCursors(self.plot)

        self.toolbar = QToolBar(self)
        self.toolbar.setMovable(False)
        self.toolbar.addAction(tr(Msg.ACTION_AUTO_RANGE), self.plot.auto_range)
        self.cursors_action = self.toolbar.addAction(tr(Msg.ACTION_AB_CURSORS))
        self.cursors_action.setCheckable(True)
        self.cursors_action.toggled.connect(self.cursors.set_enabled)

        split_menu = QMenu(self)
        for text, tip, orientation in (
            (Msg.ACTION_SPLIT_RIGHT, Msg.TIP_SPLIT_RIGHT, Qt.Orientation.Horizontal),
            (Msg.ACTION_SPLIT_DOWN, Msg.TIP_SPLIT_DOWN, Qt.Orientation.Vertical),
        ):
            action = split_menu.addAction(tr(text), partial(self._request_split, orientation))
            action.setToolTip(tr(tip))
            action.setStatusTip(tr(tip))
        split_menu.addSeparator()
        split_menu.addAction(tr(Msg.ACTION_SPLIT), self.plot.split).setStatusTip(tr(Msg.TIP_SPLIT))
        split_menu.addAction(
            tr(Msg.ACTION_UNSPLIT), lambda: self.plot.remove_subplot(len(self.plot.subplots) - 1)
        ).setStatusTip(tr(Msg.TIP_UNSPLIT))
        self.split_menu = split_menu
        self._add_menu_button(tr(Msg.BUTTON_SPLIT), split_menu)

        self.window_menu = QMenu(self)
        self.window_menu.aboutToShow.connect(self._fill_window_menu)
        self._add_menu_button(tr(Msg.BUTTON_WINDOW), self.window_menu)

        graph_menu = QMenu(self)
        graph_menu.addAction(tr(Msg.MENU_PLOT_SETTINGS), self.controller.edit_plot_settings)
        graph_menu.addAction(tr(Msg.ACTION_RENAME), self.ask_rename)
        graph_menu.addSeparator()
        graph_menu.addAction(tr(Msg.ACTION_CLEAR_PLOT), self.plot.clear_curves)
        graph_menu.addAction(tr(Msg.ACTION_CLOSE_PLOT), self.close_plot)
        self.graph_menu = graph_menu
        self._add_menu_button(tr(Msg.BUTTON_GRAPH), graph_menu)

        # Detached window: F11 = full screen, Esc = leave full screen.
        for key, slot in (
            (Qt.Key.Key_F11, self.toggle_full_screen),
            (Qt.Key.Key_Escape, self._on_escape),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self._closing = False

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.plot)
        self.setWidget(body)

    def _add_menu_button(self, text: str, menu: QMenu) -> QToolButton:
        button = QToolButton(self.toolbar)
        button.setText(f"{text} ▾")
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(button)
        return button

    # -- separate window ------------------------------------------------------------------

    @property
    def detached(self) -> bool:
        """In its own window (maximisable, Windows snap, taskbar) rather than docked."""
        return (
            self.isFloating()
            and bool(self.windowFlags() & Qt.WindowType.Window)
            and bool(self.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)
        )

    def detach(self) -> None:
        """Move the graph to its own top-level window."""
        if self.detached:
            return
        size = self.size()
        if not self.isFloating():
            self.setFloating(True)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(max(size.width(), 900), max(size.height(), 560))
        self.show()
        self.raise_()
        self.activateWindow()

    def attach(self) -> None:
        """Put the graph back into the main window."""
        if self.isFullScreen() or self.isMaximized():
            self.showNormal()
        if self.isFloating():
            self.setFloating(False)
        self.show()

    def toggle_full_screen(self) -> None:
        self.detach()
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_escape(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def show_maximized(self) -> None:
        self.detach()
        self.showMaximized()

    def place_on_screen(self, side: str, screen: QScreen | None = None) -> None:
        """Detached window on ``side`` (``left``, ``right``, ``full``) of ``screen``."""
        self.detach()
        screen = screen or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        if self.isFullScreen() or self.isMaximized():
            self.showNormal()
        area = screen.availableGeometry()
        if side == "left":
            target = QRect(area.left(), area.top(), area.width() // 2, area.height())
        elif side == "right":
            half = area.width() // 2
            target = QRect(area.left() + half, area.top(), area.width() - half, area.height())
        else:
            target = QRect(area)
        # setGeometry places the client area: leave room for the window frame.
        frame = self.frameGeometry()
        inner = self.geometry()
        left, top = inner.left() - frame.left(), inner.top() - frame.top()
        right, bottom = frame.right() - inner.right(), frame.bottom() - inner.bottom()
        self.setGeometry(target.adjusted(left, top, -right, -bottom))
        if side == "full":
            self.showMaximized()

    def move_to_screen(self, screen: QScreen) -> None:
        """Same window state (full screen, maximised, half…) on another screen."""
        full = self.isFullScreen()
        self.detach()
        if full or self.isMaximized():
            self.showNormal()
        area = screen.availableGeometry()
        size = self.size().boundedTo(area.size())
        self.setGeometry(
            QRect(area.center() - QRect(0, 0, size.width(), size.height()).center(), size)
        )
        if full:
            self.showFullScreen()

    def _fill_window_menu(self) -> None:
        menu = self.window_menu
        menu.clear()
        if self.detached:
            menu.addAction(tr(Msg.ACTION_ATTACH), self.attach)
        else:
            menu.addAction(tr(Msg.ACTION_DETACH), self.detach)
        full = menu.addAction(tr(Msg.ACTION_FULL_SCREEN), self.toggle_full_screen)
        full.setCheckable(True)
        full.setChecked(self.isFullScreen())
        full.setShortcut(QKeySequence(Qt.Key.Key_F11))
        menu.addAction(tr(Msg.ACTION_MAXIMIZE), self.show_maximized)
        menu.addAction(tr(Msg.ACTION_LEFT_HALF), partial(self.place_on_screen, "left"))
        menu.addAction(tr(Msg.ACTION_RIGHT_HALF), partial(self.place_on_screen, "right"))
        screens = QGuiApplication.screens()
        if len(screens) > 1:
            screens_menu = menu.addMenu(tr(Msg.MENU_MOVE_TO_SCREEN))
            current = self.screen()
            for index, screen in enumerate(screens, start=1):
                size = screen.size()
                action = screens_menu.addAction(
                    tr(Msg.SCREEN_NAME).format(
                        index=index, name=screen.name(), width=size.width(), height=size.height()
                    ),
                    partial(self.move_to_screen, screen),
                )
                action.setCheckable(True)
                action.setChecked(screen is current and self.detached)

    def close_plot(self) -> None:
        """Close (destroy) the graph, docked or detached."""
        self._closing = True
        self.close()

    def _request_split(self, orientation: Qt.Orientation) -> None:
        self.split_requested.emit(self, orientation)

    @property
    def dock_id(self) -> str:
        return self.objectName()

    def rename(self, title: str) -> None:
        if title and title != self.windowTitle():
            self.setWindowTitle(title)
            self.title_changed.emit(title)

    def ask_rename(self) -> None:
        title, ok = QInputDialog.getText(
            self, tr(Msg.RENAME_PLOT_TITLE), tr(Msg.RENAME_PLOT_LABEL), text=self.windowTitle()
        )
        if ok:
            self.rename(title.strip())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.detached and not self._closing and self.isVisible():
            # The close button of a detached window puts the graph back (it is not lost);
            # « Graphe ▾ → Fermer le graphe » closes it for good.
            event.ignore()
            self.attach()
            return
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit(self)
