from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from csvjuggler.data.importer import (
    CsvImportCancelled,
    CsvImportError,
    ImportSettings,
    analyze,
    detect_settings,
    load_csv,
)


def test_comma_file(data_dir: Path) -> None:
    s = detect_settings(data_dir / "simple_comma.csv")
    assert (s.delimiter, s.decimal, s.time_column) == (",", ".", "time")
    ds = load_csv(data_dir / "simple_comma.csv", s)
    assert ds.alias == "simple_comma"
    assert list(ds.series) == ["speed", "torque", "status"]
    speed = ds.series["speed"]
    assert speed.id == "simple_comma/speed"
    np.testing.assert_allclose(speed.x, [0.0, 0.1, 0.2, 0.3, 0.4])
    np.testing.assert_allclose(speed.y, [0.0, 10.2, 20.5, 30.1, 40.0])


def test_semicolon_with_decimal_comma(data_dir: Path) -> None:
    s = detect_settings(data_dir / "semicolon_decimal_comma.csv")
    assert (s.delimiter, s.decimal) == (";", ",")
    assert s.time_column == "Temps (ms)"
    ds = load_csv(data_dir / "semicolon_decimal_comma.csv", s)
    np.testing.assert_allclose(ds.series["Courant"].y, [0.5, 0.6, 0.55, 0.7])
    np.testing.assert_allclose(ds.series["Tension"].y[0], 230.1)


def test_time_unit_ms(data_dir: Path) -> None:
    s = detect_settings(data_dir / "semicolon_decimal_comma.csv")
    s.time_unit = "ms"
    ds = load_csv(data_dir / "semicolon_decimal_comma.csv", s)
    np.testing.assert_allclose(ds.series["Courant"].x, [0.0, 0.01, 0.02, 0.03])


def test_tab_without_time_column_uses_index(data_dir: Path) -> None:
    s = detect_settings(data_dir / "tab_no_time.tsv")
    assert s.delimiter == "\t"
    assert s.time_column is None and s.time_mode == "index"
    ds = load_csv(data_dir / "tab_no_time.tsv", s)
    assert list(ds.series) == ["index", "A", "B"]
    np.testing.assert_allclose(ds.series["A"].x, [0, 1, 2])


def test_cp1252_fallback(data_dir: Path) -> None:
    s = detect_settings(data_dir / "cp1252.csv")
    assert s.encoding == "cp1252"
    ds = load_csv(data_dir / "cp1252.csv", s)
    assert "Température °C" in ds.series


def test_explicit_alias_and_detection_when_settings_missing(data_dir: Path) -> None:
    ds = load_csv(data_dir / "simple_comma.csv", alias="run1")
    assert ds.series["torque"].id == "run1/torque"
    assert ds.import_settings is not None


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CsvImportError):
        load_csv(tmp_path / "nope.csv")


def test_import_settings_json_roundtrip() -> None:
    s = ImportSettings(encoding="cp1252", delimiter=";", decimal=",", time_column="t")
    assert ImportSettings.from_dict(s.to_dict()) == s


def test_scope_export_multi_header_decimal_comma_pairs(data_dir: Path) -> None:
    preview = analyze(data_dir / "scope_export.csv")
    s = preview.settings
    assert preview.is_scope
    assert (s.delimiter, s.decimal) == (";", ",")
    assert (s.header_row, s.unit_row, s.data_start) == (5, 9, 11)
    assert (s.time_mode, s.time_unit) == ("pairs", "ms")
    assert preview.series_names == ["MAIN.fVitesse", "MAIN.nCourant"]

    ds = load_csv(data_dir / "scope_export.csv", s)
    speed, current = ds.series["MAIN.fVitesse"], ds.series["MAIN.nCourant"]
    np.testing.assert_allclose(speed.x, np.arange(6) * 1e-3)
    np.testing.assert_allclose(speed.y, [0, 1.5, 3, 4.5, 6, 7.5])
    np.testing.assert_allclose(current.x, [0, 0.002, 0.004, 0.006])  # own X vector
    np.testing.assert_allclose(current.y, [100, 110, 120, 130])
    assert (speed.unit, current.unit) == ("mm/s", "mA")


def test_header_row_choice(data_dir: Path) -> None:
    preview = analyze(data_dir / "scope_export.csv")
    s = preview.settings
    s.header_row = 7  # DataType line
    names = analyze(data_dir / "scope_export.csv", s).series_names
    assert names == ["REAL64", "INT"]


def test_units_in_brackets(data_dir: Path) -> None:
    ds = load_csv(data_dir / "units_brackets.csv")
    assert ds.import_settings.time_column == "time [s]"
    assert ds.series["Speed [rpm]"].unit == "rpm"
    assert ds.series["Load (%)"].unit == "%"


def test_datetime_time_column(data_dir: Path) -> None:
    s = detect_settings(data_dir / "datetime.csv")
    assert (s.time_column, s.time_unit) == ("Horodatage", "datetime")
    ds = load_csv(data_dir / "datetime.csv", s)
    x = ds.series["Valeur"].x
    np.testing.assert_allclose(np.diff(x), [1.0, 2.0])
    assert x[0] == pytest.approx(1709294400.0)  # 2024-03-01 12:00:00 UTC (naive)


def test_renames_and_progress_and_cancel(data_dir: Path) -> None:
    s = detect_settings(data_dir / "simple_comma.csv")
    s.renames = {"speed": "Vitesse"}
    seen: list[float] = []
    ds = load_csv(data_dir / "simple_comma.csv", s, progress=lambda f: seen.append(f) or True)
    assert ds.series["speed"].label == "Vitesse"
    assert seen[-1] == 1.0
    with pytest.raises(CsvImportCancelled):
        load_csv(data_dir / "simple_comma.csv", s, progress=lambda f: False)
