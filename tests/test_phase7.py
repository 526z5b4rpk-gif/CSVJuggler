from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSettings

from csvjuggler.main_window import KEY_LAST_LAYOUT, MainWindow
from csvjuggler.model.annotation import Annotation
from csvjuggler.model.layout import Layout, migrate
from csvjuggler.model.plot_config import PlotConfig
from csvjuggler.model.session import Session


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def files(tmp_path: Path, data_dir: Path) -> dict[str, Path]:
    run = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", run)
    elec = tmp_path / "elec.csv"
    shutil.copy(data_dir / "semicolon_decimal_comma.csv", elec)
    run2 = tmp_path / "other" / "run_b.csv"
    run2.parent.mkdir()
    run2.write_text("time,speed,torque,status\n0,1,2,0\n1,3,4,1\n2,5,6,0\n")
    return {"run": run, "elec": elec, "run2": run2}


def _window(qtbot, settings: QSettings) -> MainWindow:
    w = MainWindow(Session(), settings)
    qtbot.addWidget(w)
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    return w


def _build(w: MainWindow, files: dict[str, Path]) -> None:
    w.open_files([files["run"], files["elec"]], interactive=False)
    elec = w.session.dataset("elec")
    elec.import_settings.time_unit = "ms"
    w.reload_all()
    first = w.plot_docks[0]
    first.rename("Mécanique")
    first.plot.add_series(["run/speed", "run/torque"])
    first.plot.move_curve_to_axis(0, "run/torque", None)
    first.plot.split()
    first.plot.add_series(["run/status"], 1)
    second = w.new_plot()
    second.plot.add_series(["elec/Courant"])
    second.plot.set_sync_group("élec")
    w.session.rename_series("run/speed", "Vitesse")
    w.annotations.create("vline", first.dock_id, first.plot, 0, 0.2, 0.0, "événement")


def test_layout_json_roundtrip_and_migration() -> None:
    layout = Layout(annotations=[Annotation(kind="text", text="a")], derived=[{"name": "d"}])
    assert Layout.from_dict(json.loads(json.dumps(layout.to_dict()))) == layout
    old = {
        "docks": [
            {
                "dock_id": "p",
                "title": "t",
                "plot": {"curves": [{"series_id": "a/b", "color": "#000"}]},
            }
        ]
    }
    migrated = Layout.from_dict(migrate(old))
    assert migrated.version == 1
    assert migrated.docks[0].plot.subplots[0].curves[0].series_id == "a/b"


def test_save_and_restore_full_layout(qtbot, settings, files, tmp_path: Path) -> None:
    w = _window(qtbot, settings)
    _build(w, files)
    path = w.save_layout(tmp_path / "essai")
    assert path.name == "essai.cjl.json"
    saved = w.current_layout()

    w2 = _window(qtbot, settings)
    missing = w2.load_layout(path, interactive=False)
    assert missing == []
    assert [d.windowTitle() for d in w2.plot_docks] == ["Mécanique", "Graphe 2"]
    assert [d.dock_id for d in w2.plot_docks] == [d.dock_id for d in w.plot_docks]
    for d1, d2 in zip(w.plot_docks, w2.plot_docks, strict=True):
        assert d1.plot.config == d2.plot.config
    assert w2.session.dataset("elec").import_settings.time_unit == "ms"
    np.testing.assert_allclose(w2.session.get_series("elec/Courant").x, [0, 0.01, 0.02, 0.03])
    assert w2.session.get_series("run/speed").label == "Vitesse"
    assert [a.text for a in w2.session.annotations.all()] == ["événement"]
    assert w2.plot_docks[0].plot.annotation_layer.items_for(saved.annotations[0].id)
    assert "y1" in w2.plot_docks[0].plot.subplots[0].multi_axis


def test_layout_on_another_csv_with_same_structure(qtbot, settings, files, tmp_path) -> None:
    w = _window(qtbot, settings)
    _build(w, files)
    path = w.save_layout(tmp_path / "essai.cjl.json")

    w2 = _window(qtbot, settings)
    missing = w2.load_layout(path, file_overrides=[files["run2"]], interactive=False)
    assert missing == []
    speed = w2.session.get_series("run/speed")  # layout alias kept, data from run_b.csv
    np.testing.assert_allclose(speed.y, [1, 3, 5])
    assert w2.session.dataset("run").path == files["run2"].resolve()
    np.testing.assert_allclose(
        w2.plot_docks[0].plot.curve_item("run/speed").getData()[1], [1, 3, 5]
    )


def test_missing_series_and_files_are_reported_not_blocking(qtbot, settings, files, tmp_path):
    w = _window(qtbot, settings)
    _build(w, files)
    path = w.save_layout(tmp_path / "essai.cjl.json")
    files["elec"].unlink()
    (tmp_path / "less.csv").write_text("time,speed\n0,1\n1,2\n")

    w2 = _window(qtbot, settings)
    missing = w2.load_layout(path, file_overrides=[tmp_path / "less.csv"], interactive=False)
    assert missing == ["elec/Courant", "run/status", "run/torque"]
    # The curves stay in the configuration: re-applying on a complete file brings them back.
    assert len(w2.plot_docks[0].plot.config.all_curves()) == 3
    assert w2.plot_docks[0].plot.curve_item("run/speed") is not None


def test_recent_files_and_last_layout(qtbot, settings, files, tmp_path) -> None:
    w = _window(qtbot, settings)
    w.open_files([files["run"]], interactive=False)
    w.plot_docks[0].plot.add_series(["run/speed"])
    path = w.save_layout(tmp_path / "last.cjl.json")
    assert w.recent("recent_files") == [str(files["run"].resolve())]
    assert w.recent("recent_layouts") == [str(path.resolve())]
    assert settings.value(KEY_LAST_LAYOUT) == str(path.resolve())
    w._fill_recent(w.recent_files_menu, "recent_files")
    assert [a.text() for a in w.recent_files_menu.actions()] == [str(files["run"].resolve())]

    w2 = _window(qtbot, settings)
    assert w2.restore_last_layout()
    assert w2.plot_docks[0].plot.curve_item("run/speed") is not None


def test_invalid_layout_file(qtbot, settings, tmp_path) -> None:
    bad = tmp_path / "bad.cjl.json"
    bad.write_text("[1, 2]")
    w = _window(qtbot, settings)
    assert w.load_layout(bad, interactive=False) == []
    assert len(w.plot_docks) == 1  # untouched
    assert PlotConfig() == w.plot_docks[0].plot.config
