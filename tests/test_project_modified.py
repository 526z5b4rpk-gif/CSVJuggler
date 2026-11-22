"""Project save: modified state, window title and the « save? » prompt on close."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from csvjuggler.main_window import MainWindow
from csvjuggler.model.annotation import Annotation
from csvjuggler.model.session import Session


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(Session(), settings)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


@pytest.fixture
def csv(tmp_path: Path, data_dir: Path) -> Path:
    path = tmp_path / "run.csv"
    shutil.copy(data_dir / "simple_comma.csv", path)
    return path


def test_modified_state_and_title(window: MainWindow, csv: Path, tmp_path: Path) -> None:
    assert not window.is_modified() and not window.isWindowModified()
    assert window.windowTitle().startswith("Sans titre")
    window.open_files([csv], interactive=False)
    window.plot_docks[0].plot.add_series(["run/speed"])
    window.update_modified()
    assert window.is_modified() and window.isWindowModified()

    path = window.save_layout(tmp_path / "essai")
    assert path.name == "essai.cjl.json"
    assert not window.is_modified() and window.windowTitle().startswith("essai.cjl.json")

    window.session.annotations.add(Annotation(kind="vline", x=0.5, dataset_alias="run"))
    assert window.is_modified()  # annotations are part of the project
    window.save_layout(path)
    window.plot_docks[0].plot.auto_range()
    assert not window.is_modified()  # zooming is not a modification

    window.load_layout(path, interactive=False)
    assert not window.is_modified()


@pytest.mark.parametrize(
    ("answer", "closes", "saved"),
    [
        (QMessageBox.StandardButton.Cancel, False, False),
        (QMessageBox.StandardButton.Discard, True, False),
        (QMessageBox.StandardButton.Save, True, True),
    ],
)
def test_close_asks_to_save(
    window: MainWindow, csv: Path, tmp_path: Path, monkeypatch, answer, closes, saved
) -> None:
    project = tmp_path / "p.cjl.json"
    window.open_files([csv], interactive=False)
    window.save_layout(project)
    window.plot_docks[0].plot.add_series(["run/speed"])
    asked: list[str] = []

    def fake_question(*args, **_kwargs):
        asked.append(args[2])
        return answer

    monkeypatch.setattr(MainWindow, "confirm_unsaved", True)
    monkeypatch.setattr(QMessageBox, "question", fake_question)
    before = project.read_text()
    assert window.close() is closes
    assert len(asked) == 1 and "p.cjl.json" in asked[0]
    assert (project.read_text() != before) is saved


def test_close_unmodified_does_not_ask(window: MainWindow, monkeypatch) -> None:
    monkeypatch.setattr(MainWindow, "confirm_unsaved", True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("asked"))
    assert window.close()
