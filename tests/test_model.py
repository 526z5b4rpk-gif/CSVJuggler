from __future__ import annotations

import json
from pathlib import Path

from csvjuggler.model.plot_config import CurveConfig, PlotConfig
from csvjuggler.model.session import Session


def test_curve_config_json_roundtrip() -> None:
    c = CurveConfig(series_id="a/b", color="#ff0000", width=2.5, alias="B", visible=False)
    assert CurveConfig.from_dict(json.loads(json.dumps(c.to_dict()))) == c


def test_plot_config_json_roundtrip() -> None:
    p = PlotConfig(
        title="Essai",
        show_grid_x=False,
        grid_alpha=0.5,
        curves=[CurveConfig("a/x", "#000000"), CurveConfig("a/y", "#111111")],
    )
    assert PlotConfig.from_dict(json.loads(json.dumps(p.to_dict()))) == p


def test_plot_config_ignores_unknown_keys() -> None:
    p = PlotConfig.from_dict({"title": "t", "future_field": 1, "curves": []})
    assert p.title == "t"


def test_session_unique_aliases_and_lookup(qtbot, data_dir: Path) -> None:
    session = Session()
    with qtbot.waitSignal(session.datasets_changed):
        a = session.load_csv(data_dir / "simple_comma.csv")
    b = session.load_csv(data_dir / "simple_comma.csv")
    assert (a.alias, b.alias) == ("simple_comma", "simple_comma_2")
    assert session.get_series("simple_comma_2/speed") is b.series["speed"]
    assert session.get_series("simple_comma/missing") is None
    assert session.get_series("no-slash") is None
