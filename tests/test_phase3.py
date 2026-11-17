from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from csvjuggler.data.importer import analyze
from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session
from csvjuggler.ui.dialogs.import_dialog import ImportDialog
from csvjuggler.ui.progress import run_with_progress


def test_import_dialog_shows_and_edits_scope_settings(qtbot, data_dir: Path) -> None:
    path = data_dir / "scope_export.csv"
    dialog = ImportDialog(path, "scope", analyze(path))
    qtbot.addWidget(dialog)
    assert dialog.scope_label.isVisibleTo(dialog)
    assert dialog.header_spin.value() == 6  # 1-based in the UI
    assert dialog.series_table.rowCount() == 2
    assert dialog.series_table.item(0, 1).text() == "mm/s"

    dialog.series_table.item(0, 2).setText("Vitesse")
    dialog.alias_edit.setText("essai/1")
    dialog.time_unit_combo.setCurrentIndex(dialog.time_unit_combo.findData("s"))
    s = dialog.settings()
    assert s.renames == {"MAIN.fVitesse": "Vitesse"}
    assert s.time_unit == "s" and s.time_mode == "pairs"
    assert dialog.alias() == "essai_1"

    # Changing the header line refreshes the series list but keeps aliases.
    dialog.header_spin.setValue(7)  # SymbolName line
    assert dialog.series_table.item(0, 0).text() == "MAIN.fVitesse"
    assert dialog.series_table.item(0, 2).text() == "Vitesse"


def test_run_with_progress_returns_and_raises(qtbot) -> None:
    def work(report):
        for i in range(5):
            assert report(i / 5)
        return 42

    assert run_with_progress(None, "x", work) == 42

    def boom(report):
        raise ValueError("nope")

    with pytest.raises(ValueError):
        run_with_progress(None, "x", boom)


def test_open_non_interactive_reload_keeps_plots(qtbot, data_dir: Path, tmp_path: Path) -> None:
    csv = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", csv)
    session = Session()
    w = MainWindow(session)
    qtbot.addWidget(w)
    w.open_files([csv], interactive=False)
    plot = w.plot_docks[0].plot
    plot.add_series(["run/speed"])
    item = plot.curve_item("run/speed")

    csv.write_text("time,speed,torque,status\n0,5,1,0\n1,6,1,0\n2,7,1,0\n")
    w.reload_all()
    assert plot.curve_item("run/speed") is item  # not recreated
    np.testing.assert_allclose(item.getData()[1], [5, 6, 7])
    np.testing.assert_allclose(session.get_series("run/speed").x, [0, 1, 2])


def test_rename_series_from_tree_updates_legend_and_settings(qtbot, data_dir: Path) -> None:
    session = Session()
    w = MainWindow(session)
    qtbot.addWidget(w)
    w.open_files([data_dir / "simple_comma.csv"], interactive=False)
    plot = w.plot_docks[0].plot
    plot.add_series(["simple_comma/speed"])

    item = w.series_tree.model.item(0).child(0)
    item.setText("Vitesse")
    series = session.get_series("simple_comma/speed")
    assert series.label == "Vitesse"
    assert session.dataset("simple_comma").import_settings.renames == {"speed": "Vitesse"}
    assert plot.curve_item("simple_comma/speed").name() == "Vitesse"
