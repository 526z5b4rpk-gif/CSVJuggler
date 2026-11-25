"""« Boîte à outils » panel: live graph/curve settings and annotation buttons."""

from __future__ import annotations

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
    w.resize(1400, 900)
    w.show()
    qtbot.waitExposed(w)
    w.open_files([csv], interactive=False)
    w.plot_docks[0].plot.add_series([SPEED, TORQUE])
    # The text/line dialogs are modal: accept them unchanged.
    w.annotations._edit_dialog = lambda ann, _parent: ann
    return w


def test_follows_the_current_graph(window: MainWindow) -> None:
    box = window.toolbox
    first = window.plot_docks[0]
    assert box.dock is first and box.sections.isEnabled()
    assert [box.curve_list.item(i).text() for i in range(box.curve_list.count())] == [
        "speed",
        "torque",
    ]
    second = window.new_plot()
    assert box.dock is second and box.curve_list.count() == 0
    assert not box.no_curve_label.isHidden() and box.curve_editor.isHidden()  # page folded
    window.close_all_plots()
    assert box.dock is None and not box.sections.isEnabled()


def test_graph_settings_are_applied_live(window: MainWindow) -> None:
    plot = window.plot_docks[0].plot
    general = window.toolbox.general
    general.grid_x_check.setChecked(not plot.config.show_grid_x)
    assert plot.config.show_grid_x == general.grid_x_check.isChecked()
    general.title_edit.setText("Banc 1")
    general.title_edit.editingFinished.emit()
    assert plot.config.title == "Banc 1"
    # Changes made elsewhere are reflected in the panel.
    config = plot.config
    config.legend_position = "bottom-right"
    plot.update_config(config)
    assert general.legend_combo.currentData() == "bottom-right"


def test_curve_settings_are_applied_live(window: MainWindow) -> None:
    box = window.toolbox
    plot = window.plot_docks[0].plot
    box.curve_list.setCurrentRow(1)
    assert box.selected_curve_key() == (0, TORQUE)
    box.curve_editor.gain_spin.setValue(3.0)
    assert plot.config.subplots[0].curve(TORQUE).gain == 3.0
    box.curve_editor.visible_check.setChecked(False)
    assert not plot.config.subplots[0].curve(TORQUE).visible
    assert box.selected_curve_key() == (0, TORQUE)  # selection kept across the refresh
    box.remove_curve_button.click()
    assert plot.config.subplots[0].curve(TORQUE) is None
    assert box.curve_list.count() == 1


@pytest.mark.parametrize("kind", ["text", "bubble", "delta", "vline", "hline", "region"])
def test_add_annotation_buttons(window: MainWindow, kind: str) -> None:
    box = window.toolbox
    box.curve_list.setCurrentRow(1)
    box.add_buttons[kind].click()
    added = window.session.annotations.all()
    assert [a.kind for a in added] == [kind]
    lo, hi = window.plot_docks[0].plot.x_range()
    assert lo <= added[0].x <= hi
    if kind in ("bubble", "delta"):
        assert added[0].series_id == TORQUE  # the curve selected in « Courbes »


def test_selected_annotation_can_be_deleted(window: MainWindow, qtbot) -> None:
    box = window.toolbox
    dock = window.plot_docks[0]
    ann = window.annotations.create("vline", dock.dock_id, dock.plot, 0, 0.2, 0.0, "pic")
    assert not box.delete_selection_button.isEnabled()
    dock.plot.annotation_layer.hub.selected.emit(ann.id)
    assert "pic" in box.selection_label.text() and box.delete_selection_button.isEnabled()
    box.delete_selection_button.click()
    assert window.session.annotations.get(ann.id) is None
    assert not box.delete_selection_button.isEnabled()
