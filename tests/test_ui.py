from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from csvjuggler.main_window import MainWindow
from csvjuggler.model.plot_config import CurveConfig, PlotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.plot_widget import PlotWidget
from csvjuggler.ui.series_tree import SERIES_ID_ROLE, SeriesTree, decode_series_ids


def _drop(widget, mime: QMimeData) -> QDropEvent:
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)
    return event


def test_series_tree_lists_and_drags_series(qtbot, data_dir: Path) -> None:
    session = Session()
    tree = SeriesTree(session)
    qtbot.addWidget(tree)
    session.load_csv(data_dir / "simple_comma.csv")

    ds_item = tree.model.item(0)
    assert ds_item.text() == "simple_comma"
    assert ds_item.rowCount() == 3
    # Dragging the dataset node carries all its series.
    ids = decode_series_ids(tree.model.mimeData([ds_item.index()]))
    assert ids == ["simple_comma/speed", "simple_comma/torque", "simple_comma/status"]
    assert ds_item.child(1).data(SERIES_ID_ROLE) == "simple_comma/torque"

    tree.filter_edit.setText("torq")
    assert tree.proxy.rowCount(tree.proxy.index(0, 0)) == 1


def test_drop_series_on_plot(qtbot, data_dir: Path) -> None:
    session = Session()
    session.load_csv(data_dir / "simple_comma.csv")
    tree = SeriesTree(session)
    plot = PlotWidget(session)
    qtbot.addWidget(tree)
    qtbot.addWidget(plot)

    mime = tree.model.mimeData([tree.model.item(0).child(0).index()])
    with qtbot.waitSignal(plot.config_changed):
        event = _drop(plot, mime)
    assert event.isAccepted()
    assert [c.series_id for c in plot.config.curves] == ["simple_comma/speed"]
    item = plot.curve_item("simple_comma/speed")
    assert item is not None
    assert item.opts["clipToView"] and item.opts["autoDownsample"]

    # Dropping the same series again does not duplicate it; a new one gets another colour.
    _drop(plot, tree.model.mimeData([tree.model.item(0).index()]))
    assert len(plot.config.curves) == 3
    assert len({c.color for c in plot.config.curves}) == 3


def test_drop_foreign_mime_is_ignored(qtbot) -> None:
    plot = PlotWidget(Session())
    qtbot.addWidget(plot)
    mime = QMimeData()
    mime.setText("hello")
    event = _drop(plot, mime)
    assert not event.isAccepted()
    assert plot.config.curves == []


def test_apply_config_updates_without_recreating_items(qtbot, data_dir: Path) -> None:
    session = Session()
    session.load_csv(data_dir / "simple_comma.csv")
    plot = PlotWidget(session)
    qtbot.addWidget(plot)
    plot.add_series(["simple_comma/speed"])
    item = plot.curve_item("simple_comma/speed")

    cfg = PlotConfig(curves=[CurveConfig("simple_comma/speed", "#00ff00", width=3)])
    plot.apply_config(cfg)
    assert plot.curve_item("simple_comma/speed") is item
    assert item.opts["pen"].width() == 3


def test_missing_series_reported(qtbot) -> None:
    plot = PlotWidget(Session())
    qtbot.addWidget(plot)
    with qtbot.waitSignal(plot.missing_series_changed) as blocker:
        plot.apply_config(PlotConfig(curves=[CurveConfig("ghost/x", "#000000")]))
    assert blocker.args == [["ghost/x"]]


def test_main_window_csv_file_drop(qtbot, data_dir: Path) -> None:
    session = Session()
    window = MainWindow(session)
    qtbot.addWidget(window)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(data_dir / "simple_comma.csv"))])
    _drop(window, mime)
    assert [d.alias for d in session.datasets] == ["simple_comma"]
    assert len(window.plot_docks) == 1
