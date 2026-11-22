from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyqtgraph as pg
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from csvjuggler.main_window import MainWindow
from csvjuggler.model.annotation import (
    Annotation,
    AnnotationStore,
    companion_path,
    load_companion,
    save_companion,
)
from csvjuggler.model.session import Session
from csvjuggler.ui.annotation_items import (
    LineAnnotationItem,
    RegionAnnotationItem,
    TextAnnotationItem,
)

SPEED = "run/speed"
TORQUE = "run/torque"


@pytest.fixture
def csv(tmp_path: Path, data_dir: Path) -> Path:
    path = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", path)
    return path


@pytest.fixture
def window(qtbot, csv: Path) -> MainWindow:
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    w.open_files([csv], interactive=False)
    w.plot_docks[0].plot.add_series([SPEED, TORQUE])
    return w


def _layer(window: MainWindow, index: int = 0):
    return window.plot_docks[index].plot.annotation_layer


def test_annotation_roundtrip_and_store() -> None:
    a = Annotation(kind="region", x=1, x2=2, text="palier 1", locked=True, link_all=True)
    assert Annotation.from_dict(json.loads(json.dumps(a.to_dict()))) == a
    store = AnnotationStore()
    store.add(a)
    b = Annotation.from_dict(a.to_dict())
    b.text = "palier 2"
    store.merge([b])
    assert [x.text for x in store.all()] == ["palier 2"]


def test_companion_file_roundtrip_and_auto_load(qtbot, csv: Path) -> None:
    ann = Annotation(kind="vline", x=0.2, text="démarrage", dataset_alias="old")
    save_companion(csv, [ann])
    assert companion_path(csv).name == "run.csv.annotations.json"
    assert load_companion(csv)[0].text == "démarrage"
    session = Session()
    session.load_csv(csv, alias="essai")
    loaded = session.annotations.all()
    assert len(loaded) == 1
    assert loaded[0].dataset_alias == "essai" and loaded[0].dataset_path == str(csv.resolve())


def test_create_four_kinds(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    m = window.annotations
    text = m.create("text", dock.dock_id, dock.plot, 0, 0.1, 10.0, "pic")
    vline = m.create("vline", dock.dock_id, dock.plot, 0, 0.2, 0.0, "événement")
    hline = m.create("hline", dock.dock_id, dock.plot, 0, 0.0, 30.0, "seuil")
    region = m.create("region", dock.dock_id, dock.plot, 0, 0.25, 0.0, "palier 1")
    layer = _layer(window)
    assert isinstance(layer.items_for(text.id)[0], TextAnnotationItem)
    vitem = layer.items_for(vline.id)[0]
    assert isinstance(vitem, LineAnnotationItem) and vitem.angle == 90
    assert vitem.value() == pytest.approx(0.2)
    hitem = layer.items_for(hline.id)[0]
    assert hitem.angle == 0 and hitem.value() == pytest.approx(30.0)
    ritem = layer.items_for(region.id)[0]
    assert isinstance(ritem, RegionAnnotationItem)
    lo, hi = ritem.getRegion()
    assert lo < 0.25 < hi
    assert all(a.dataset_alias == "run" for a in window.session.annotations.all())


def test_move_line_updates_model(window: MainWindow, qtbot) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create("vline", dock.dock_id, dock.plot, 0, 0.2, 0.0)
    item = _layer(window).items_for(ann.id)[0]
    item.setValue(0.33)
    item.sigPositionChangeFinished.emit(item)
    qtbot.waitUntil(lambda: window.session.annotations.get(ann.id).x == pytest.approx(0.33))


def test_locked_annotation_is_not_movable(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create("vline", dock.dock_id, dock.plot, 0, 0.2, 0.0)
    window.annotations.set_locked(ann.id, True)
    assert not _layer(window).items_for(ann.id)[0].movable


def test_delete_key_removes_selected(window: MainWindow, qtbot) -> None:
    dock = window.plot_docks[0]
    ann = window.annotations.create("text", dock.dock_id, dock.plot, 0, 0.1, 5.0, "x")
    layer = _layer(window)
    layer.hub.selected.emit(ann.id)
    QTest.keyClick(dock.plot, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: window.session.annotations.get(ann.id) is None)
    assert layer.items_for(ann.id) == []


def test_linked_vline_on_synced_graphs_only(window: MainWindow) -> None:
    first = window.plot_docks[0]
    synced = window.new_plot()
    lonely = window.new_plot()
    lonely.plot.config.sync_group = ""
    ann = window.annotations.create("vline", first.dock_id, first.plot, 0, 0.2, 0.0)
    ann.link_all = True
    window.session.annotations.update(ann)
    assert synced.plot.annotation_layer.items_for(ann.id)
    assert not lonely.plot.annotation_layer.items_for(ann.id)


def test_annotation_without_its_graph_falls_back_to_dataset_graphs(window: MainWindow) -> None:
    ann = Annotation(kind="vline", x=0.1, plot_id="plot_999", dataset_alias="run")
    window.session.annotations.add(ann)
    assert _layer(window).items_for(ann.id)
    other = window.new_plot()  # shows nothing from "run"
    assert not other.plot.annotation_layer.items_for(ann.id)


def test_panel_lists_and_focuses(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    plot = dock.plot
    plot.subplots[0].view_box.setXRange(0.0, 0.1, padding=0)
    ann = window.annotations.create("vline", dock.dock_id, plot, 0, 0.35, 0.0, "fin")
    panel = window.annotation_panel
    assert panel.list.count() == 1
    assert "fin" in panel.list.item(0).text()
    panel._on_clicked(panel.list.item(0))
    lo, hi = plot.x_range()
    assert (lo + hi) / 2 == pytest.approx(ann.x)
    assert hi - lo == pytest.approx(0.1)


def test_context_menu_has_add_annotation(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    menu = dock.controller.build_plot_menu(0, QPointF(100, 100))
    add = next(a.menu() for a in menu.actions() if a.text() == "Ajouter une annotation")
    assert [a.text() for a in add.actions()] == [
        "Texte",
        "Ligne verticale (événement)",
        "Ligne horizontale (seuil)",
        "Région X",
    ]


def test_companion_written_after_change(window: MainWindow, csv: Path, qtbot) -> None:
    dock = window.plot_docks[0]
    window.annotations.create("region", dock.dock_id, dock.plot, 0, 0.2, 0.0, "palier 1")
    qtbot.waitUntil(lambda: companion_path(csv).exists(), timeout=3000)
    data = json.loads(companion_path(csv).read_text(encoding="utf-8"))
    assert data["annotations"][0]["text"] == "palier 1"


def test_text_annotation_hline_on_secondary_axis(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    plot = dock.plot
    plot.move_curve_to_axis(0, TORQUE, None)
    ann = window.annotations.create("hline", dock.dock_id, plot, 0, 0.0, 1.7, "seuil couple")
    ann.axis_id = "y1"
    window.session.annotations.update(ann)
    item = _layer(window).items_for(ann.id)[0]
    assert item.getViewBox() is plot.subplots[0].view_for_axis("y1")
    assert isinstance(item, pg.InfiniteLine)


def test_text_bubble_with_pointer(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    m = window.annotations
    ann = m.create("text", dock.dock_id, dock.plot, 0, 0.1, 10.0, "pic\nsecond")
    item = _layer(window).items_for(ann.id)[0]
    assert isinstance(item, TextAnnotationItem)
    # No pointer: the bubble's bottom-left corner is the anchor point.
    assert item.box.bottomLeft() == QPointF(0.0, 0.0)
    assert item.box.height() > 2 * item.PADDING[1]  # two lines of text
    stored = window.session.annotations.get(ann.id)
    assert stored is not None
    stored.arrow = True
    window.session.annotations.update(stored)
    item = _layer(window).items_for(ann.id)[0]
    assert len(_layer(window).items_for(ann.id)) == 1  # tail drawn by the bubble itself
    assert item.box.left() > 0 and item.box.bottom() < 0  # bubble above-right of the point
    assert item.shape().contains(QPointF(1.0, -1.0))  # the tail reaches the point


def test_text_bubble_shows_point_coordinates(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    m = window.annotations
    ann = m.create("text", dock.dock_id, dock.plot, 0, 0.25, 12.5, "pic")
    item = _layer(window).items_for(ann.id)[0]
    assert isinstance(item, TextAnnotationItem)
    assert item.coords_line.startswith("x = 0.25 s") and "y = 12.5" in item.coords_line
    m.move(ann.id, 0.5, 3.0, 0.0)
    item = _layer(window).items_for(ann.id)[0]
    assert item.coords_line.startswith("x = 0.5 s") and "y = 3" in item.coords_line
    stored = window.session.annotations.get(ann.id)
    assert stored is not None
    stored.show_coords = False
    window.session.annotations.update(stored)
    assert _layer(window).items_for(ann.id)[0].coords_line == ""


def test_text_bubble_can_be_dragged_with_the_mouse(window: MainWindow, qtbot) -> None:
    dock = window.plot_docks[0]
    view = dock.plot.subplots[0].view_box
    (x0, x1), (y0, y1) = view.viewRange()
    ann = window.annotations.create(
        "text", dock.dock_id, dock.plot, 0, (x0 + x1) / 2, (y0 + y1) / 2, "pic"
    )
    item = _layer(window).items_for(ann.id)[0]
    start = dock.plot.mapFromScene(item.mapToScene(item.box.center()))
    assert item in dock.plot.scene().items(item.mapToScene(item.box.center()))
    del item  # the layer must be the only owner: it rebuilds the item at the end of the drag
    viewport = dock.plot.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 11):
        QTest.mouseMove(viewport, start + QPoint(8 * step, 0))
        qtbot.wait(1)
    end = start + QPoint(80, 0)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    qtbot.waitUntil(lambda: window.session.annotations.get(ann.id).x > (x0 + x1) / 2)
    assert view.viewRange()[0] == pytest.approx([x0, x1])  # the view did not pan
