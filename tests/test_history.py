"""Undo / redo of annotations and graph settings."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session

SPEED = "run/speed"
TORQUE = "run/torque"


@pytest.fixture
def window(qtbot, tmp_path: Path, data_dir: Path) -> MainWindow:
    csv = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", csv)
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.open_files([csv], interactive=False)
    w.plot_docks[0].plot.add_series([SPEED, TORQUE])
    w.history.reset()  # start from the loaded state
    return w


def test_annotation_add_move_delete_are_undoable(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    m, store, history = window.annotations, window.session.annotations, window.history
    ann = m.create("vline", dock.dock_id, dock.plot, 0, 0.2, 0.0, "pic")
    history.commit()
    m.move(ann.id, 0.3, 0.0, 0.3)
    history.commit()
    m.delete(ann.id)
    history.commit()
    assert store.get(ann.id) is None
    history.undo()
    assert store.get(ann.id).x == pytest.approx(0.3)
    history.undo()
    assert store.get(ann.id).x == pytest.approx(0.2)
    history.undo()
    assert store.all() == []
    assert not history.stack.canUndo()
    history.redo()
    history.redo()
    assert store.get(ann.id).x == pytest.approx(0.3)
    # The annotation is drawn again (the layer follows the store).
    assert dock.plot.annotation_layer.items_for(ann.id)


def test_graph_settings_and_title_are_undoable(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    history = window.history
    config = copy.deepcopy(dock.plot.config)
    config.show_grid_x = not config.show_grid_x
    dock.plot.update_config(config)
    history.commit()
    dock.rename("Banc 1")
    history.commit()
    history.undo()
    assert dock.windowTitle() != "Banc 1"
    history.undo()
    assert dock.plot.config.show_grid_x == (not config.show_grid_x)
    history.redo()
    assert dock.plot.config.show_grid_x == config.show_grid_x
    assert "Banc 1" not in history.stack.undoText()
    history.redo()
    assert dock.windowTitle() == "Banc 1"


def test_burst_of_changes_is_one_step(window: MainWindow, qtbot) -> None:
    plot = window.plot_docks[0].plot
    for gain in (2.0, 3.0, 4.0):  # e.g. a spin box being scrolled
        curve = copy.deepcopy(plot.config.subplots[0].curve(SPEED))
        curve.gain = gain
        plot.set_curve_config(0, curve)
    assert window.undo_action.isEnabled()  # pending edit: Ctrl+Z already works
    qtbot.wait(600)  # coalescing delay elapsed
    assert window.history.stack.count() == 1
    window.undo_action.trigger()
    assert plot.config.subplots[0].curve(SPEED).gain == 1.0


def test_undo_records_the_pending_edit_first(window: MainWindow) -> None:
    plot = window.plot_docks[0].plot
    config = copy.deepcopy(plot.config)
    config.title = "Essai"
    plot.update_config(config)
    window.history.undo()  # without waiting for the coalescing timer
    assert plot.config.title == ""
    window.history.redo()
    assert plot.config.title == "Essai"


def test_closed_graph_is_skipped_and_loading_resets(window: MainWindow, tmp_path: Path) -> None:
    dock = window.plot_docks[0]
    config = copy.deepcopy(dock.plot.config)
    config.title = "Essai"
    dock.plot.update_config(config)
    window.history.commit()
    second = window.new_plot()
    dock.close_plot()
    window.history.undo()  # the graph is gone: nothing to restore, no error
    assert window.plot_docks == [second]
    path = window.save_layout(tmp_path / "p")
    window.load_layout(path, interactive=False)
    assert not window.history.stack.canUndo()


def test_edit_menu_texts(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    window.annotations.create("vline", dock.dock_id, dock.plot, 0, 0.2, 0.0, "pic")
    window._on_edit_menu()
    assert window.undo_action.text() == "Annuler : annotations"
    assert not window.redo_action.isEnabled()
    window.undo_action.trigger()
    window._on_edit_menu()
    assert window.redo_action.text() == "Rétablir : annotations"
    assert window.undo_action.text() == "Annuler"


def test_opening_a_file_with_companion_annotations_is_not_undoable(
    qtbot, tmp_path: Path, data_dir: Path
) -> None:
    from csvjuggler.model.annotation import Annotation, save_companion

    csv = tmp_path / "essai.csv"
    shutil.copy(data_dir / "simple_comma.csv", csv)
    save_companion(csv, [Annotation(kind="vline", x=0.1, dataset_alias="essai")])
    w = MainWindow(Session())
    qtbot.addWidget(w)
    w.open_files([csv], interactive=False)
    assert len(w.session.annotations.all()) == 1
    w.history.undo()
    assert len(w.session.annotations.all()) == 1  # still there
    assert not w.history.stack.canUndo()
