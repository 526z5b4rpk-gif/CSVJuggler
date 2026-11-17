from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from csvjuggler.data.derived import (
    DerivedSeriesConfig,
    FormulaError,
    evaluate,
    formula_variables,
    integral,
    lowpass,
)
from csvjuggler.data.export import CsvExportOptions, export_csv
from csvjuggler.data.series import Series
from csvjuggler.main_window import MainWindow
from csvjuggler.model.session import Session
from csvjuggler.ui.dialogs.derived_dialog import DerivedDialog

X = np.array([0.0, 1.0, 2.0, 3.0])


def _resolver(**series: Series):
    table = {f"d/{k}": v for k, v in series.items()}
    return table.get


def _s(name: str, y, x=X) -> Series:
    return Series(name=name, x=np.asarray(x, float), y=np.asarray(y, float), source="d")


@pytest.mark.parametrize(
    "formula",
    [
        "a.__class__",
        "__import__('os')",
        "open('x')",
        "(lambda: 1)()",
        "a[0]",
        "'texte'",
        "sum(a)",
        "derivative(a, x=1)",
        "a +",
    ],
)
def test_forbidden_formulas(formula: str) -> None:
    config = DerivedSeriesConfig("bad", formula, {"a": "d/a"})
    with pytest.raises(FormulaError):
        evaluate(config, _resolver(a=_s("a", [1, 2, 3, 4])))


def test_formula_evaluation() -> None:
    a, b = _s("a", [1, 2, 3, 4]), _s("b", [2, 2, 2, 2])
    resolve = _resolver(a=a, b=b)

    def run(formula: str) -> np.ndarray:
        return evaluate(DerivedSeriesConfig("r", formula, {"a": "d/a", "b": "d/b"}), resolve).y

    np.testing.assert_allclose(run("a / b"), [0.5, 1, 1.5, 2])
    np.testing.assert_allclose(run("derivative(a)"), [1, 1, 1, 1])
    np.testing.assert_allclose(run("integral(b)"), [0, 2, 4, 6])
    np.testing.assert_allclose(run("(a > 2) * 10 - pi * 0"), [0, 0, 10, 10])
    np.testing.assert_allclose(run("clip(a, 2, 3) + abs(-b)"), [4, 4, 5, 5])
    assert formula_variables("lowpass(b, 3) + a * b") == ["b", "a"]


def test_variables_resampled_on_first_x() -> None:
    a = _s("a", [0, 10, 20, 30])
    b = _s("b", [0, 100], x=[0.0, 3.0])  # other time base
    out = evaluate(DerivedSeriesConfig("r", "a + b", {"a": "d/a", "b": "d/b"}), _resolver(a=a, b=b))
    assert out.x is a.x
    np.testing.assert_allclose(out.y, [0, 43.333333, 86.666667, 130], rtol=1e-6)


def test_missing_variable_and_series() -> None:
    a = _s("a", [1, 2, 3, 4])
    with pytest.raises(FormulaError, match="non affectée"):
        evaluate(DerivedSeriesConfig("r", "a + c", {"a": "d/a"}), _resolver(a=a))
    with pytest.raises(FormulaError, match="introuvable"):
        evaluate(DerivedSeriesConfig("r", "a", {"a": "d/zz"}), _resolver(a=a))


def test_lowpass_and_integral_helpers() -> None:
    x = np.arange(1000) * 1e-3
    np.testing.assert_allclose(lowpass(np.full(1000, 3.0), x, 10), 3.0)
    step = np.r_[np.zeros(100), np.ones(900)]
    out = lowpass(step, x, 10)  # tau = 15.9 ms → 63 % after one tau
    assert out[100 + 16] == pytest.approx(0.63, abs=0.03)
    np.testing.assert_allclose(integral(np.ones(4), X), [0, 1, 2, 3])


@pytest.fixture
def window(qtbot, data_dir: Path, tmp_path: Path) -> MainWindow:
    csv = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", csv)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(Session(), settings)
    qtbot.addWidget(w)
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    w.open_files([csv], interactive=False)
    return w


def test_derived_series_in_session_plot_reload_and_layout(window: MainWindow, tmp_path) -> None:
    session = window.session
    session.add_derived(
        DerivedSeriesConfig(
            "power", "speed * torque", {"speed": "run/speed", "torque": "run/torque"}, "W"
        )
    )
    power = session.get_series("calc/power")
    np.testing.assert_allclose(power.y, [0, 16.32, 34.85, 49.665, 72.0])
    assert power.unit == "W"
    assert [d.alias for d in session.datasets] == ["run", "calc"]
    assert session.unique_alias("calc") == "calc_2"

    plot = window.plot_docks[0].plot
    plot.add_series(["calc/power"])
    item = plot.curve_item("calc/power")

    csv = session.dataset("run").path
    csv.write_text("time,speed,torque,status\n0,1,2,0\n1,3,4,0\n")
    window.reload_all()
    assert plot.curve_item("calc/power") is item
    np.testing.assert_allclose(item.getData()[1], [2, 12])

    path = window.save_layout(tmp_path / "with_calc.cjl.json")
    w2 = MainWindow(Session(), window.settings)
    w2.load_layout(path, interactive=False)
    assert w2.session.derived[0].formula == "speed * torque"
    np.testing.assert_allclose(w2.session.get_series("calc/power").y, [2, 12])
    assert w2.plot_docks[0].plot.curve_item("calc/power") is not None
    w2.close()


def test_broken_derived_series_is_reported_not_raised(window: MainWindow) -> None:
    config = DerivedSeriesConfig("x", "a * 2", {"a": "run/speed"})
    window.session.add_derived(config)
    window.session.remove_dataset("run")
    assert "x" in window.session.derived_errors
    assert window.session.get_series("calc/x") is None


def test_derived_dialog(window: MainWindow, qtbot) -> None:
    dialog = DerivedDialog(window.session, preselected=["run/speed", "run/torque"])
    qtbot.addWidget(dialog)
    assert dialog.formula_edit.text() == "a / b"
    config = dialog.config()
    assert config.variables == {"a": "run/speed", "b": "run/torque"}
    dialog.name_edit.setText("ratio")
    dialog.formula_edit.setText("a / c")
    dialog.accept()
    assert "non affectée" in dialog.error_label.text()
    assert dialog.result() == 0


def test_tree_menu_for_derived_series(window: MainWindow) -> None:
    window.session.add_derived(DerivedSeriesConfig("d", "a + 1", {"a": "run/speed"}))
    texts = [a.text() for a in window.build_tree_menu(["calc/d"]).actions()]
    assert "Modifier la formule…" in texts and "Supprimer la série calculée" in texts
    next(
        a for a in window.build_tree_menu(["calc/d"]).actions() if a.text().startswith("Supprimer")
    ).trigger()
    assert window.session.derived == []


def test_export_csv_same_and_different_x(tmp_path: Path) -> None:
    a = _s("a", [1, 2, 3, 4])
    b = _s("b", [5, 6, 7, 8])
    c = _s("c", [9, 10], x=[0.5, 2.5])
    path = tmp_path / "out.csv"
    assert export_csv(path, [a, b], 1, 2) == 2
    frame = pd.read_csv(path)
    assert list(frame.columns) == ["time", "a", "b"]
    assert frame.to_numpy().tolist() == [[1, 2, 6], [2, 3, 7]]

    export_csv(path, [a, c], 0, 3, CsvExportOptions(delimiter=";", decimal=","))
    text = path.read_text()
    assert text.splitlines()[0] == "time (a);a;time (c);c"
    assert "0,5;9" in text


def test_image_exports_and_clipboard(window: MainWindow, tmp_path: Path) -> None:
    plot = window.plot_docks[0].plot
    plot.add_series(["run/speed", "run/torque"])
    plot.move_curve_to_axis(0, "run/torque", None)
    window.annotations.create("vline", window.plot_docks[0].dock_id, plot, 0, 0.2, 0, "evt")
    png = window.export_plot_image(tmp_path / "g.png")
    svg = window.export_plot_image(tmp_path / "g.svg")
    assert png.stat().st_size > 1000
    content = svg.read_text()
    assert "<svg" in content and "evt" in content
    assert window.export_window_image(tmp_path / "w.png").stat().st_size > 1000
    assert "<svg" in window.export_window_image(tmp_path / "w.svg").read_text()
    window.copy_plot_image()
    assert not QApplication.clipboard().image().isNull()


def test_export_ranges(window: MainWindow) -> None:
    dock = window.plot_docks[0]
    dock.plot.add_series(["run/speed"])
    dock.cursors_action.toggle()
    dock.cursors.set_positions(0.3, 0.1)
    ann = window.annotations.create("region", dock.dock_id, dock.plot, 0, 0.2, 0, "palier")
    dock.plot.annotation_layer.hub.selected.emit(ann.id)
    labels = [r[0] for r in window.export_ranges(dock)]
    assert labels[0] == "Plage visible"
    assert labels[1] == "Entre les curseurs A et B"
    assert labels[2].startswith("Région sélectionnée")
    assert window.export_ranges(dock)[1][1:] == (0.1, 0.3)
