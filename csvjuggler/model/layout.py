"""Complete layout (``*.cjl.json``): datasets and their import settings, docks and their
arrangement, graphs, axes, curves (by series id), annotations, derived series, X sync.

The JSON carries a ``version``; :func:`migrate` upgrades older files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from csvjuggler.data.importer import ImportSettings
from csvjuggler.model.annotation import Annotation
from csvjuggler.model.plot_config import PlotConfig

log = logging.getLogger(__name__)

LAYOUT_VERSION = 1
LAYOUT_SUFFIX = ".cjl.json"


class LayoutError(Exception):
    """The file is not a readable layout."""


@dataclass
class DatasetRef:
    alias: str
    path: str
    import_settings: ImportSettings = field(default_factory=ImportSettings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "path": self.path,
            "import_settings": self.import_settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetRef:
        return cls(
            alias=str(data["alias"]),
            path=str(data.get("path", "")),
            import_settings=ImportSettings.from_dict(data.get("import_settings") or {}),
        )

    def candidate_paths(self, layout_dir: Path | None) -> list[Path]:
        """Where to look for the file: the stored path, then next to the layout."""
        paths = [Path(self.path)] if self.path else []
        if layout_dir is not None and self.path:
            paths.append(layout_dir / Path(self.path).name)
        return paths


@dataclass
class DockConfig:
    dock_id: str
    title: str
    plot: PlotConfig = field(default_factory=PlotConfig)
    detached: bool = False
    """Shown in its own window (outside the main window)."""
    window_geometry: str = ""
    """``QWidget.saveGeometry()`` of that window, base64 (screen, size, maximised…)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dock_id": self.dock_id,
            "title": self.title,
            "plot": self.plot.to_dict(),
            "detached": self.detached,
            "window_geometry": self.window_geometry,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DockConfig:
        return cls(
            dock_id=str(data["dock_id"]),
            title=str(data.get("title", "")),
            plot=PlotConfig.from_dict(data.get("plot") or {}),
            detached=bool(data.get("detached", False)),
            window_geometry=str(data.get("window_geometry", "")),
        )


@dataclass
class Layout:
    version: int = LAYOUT_VERSION
    datasets: list[DatasetRef] = field(default_factory=list)
    docks: list[DockConfig] = field(default_factory=list)
    dock_state: str = ""
    """Base64 of ``QMainWindow.saveState()`` of the graph area."""
    window_state: str = ""
    """Base64 of ``QMainWindow.saveState()`` of the main window (side panels)."""
    annotations: list[Annotation] = field(default_factory=list)
    derived: list[dict[str, Any]] = field(default_factory=list)
    """Derived series definitions (see ``data.derived``)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "datasets": [d.to_dict() for d in self.datasets],
            "docks": [d.to_dict() for d in self.docks],
            "dock_state": self.dock_state,
            "window_state": self.window_state,
            "annotations": [a.to_dict() for a in self.annotations],
            "derived": list(self.derived),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Layout:
        data = migrate(data)
        return cls(
            version=LAYOUT_VERSION,
            datasets=[DatasetRef.from_dict(d) for d in data.get("datasets", [])],
            docks=[DockConfig.from_dict(d) for d in data.get("docks", [])],
            dock_state=str(data.get("dock_state", "")),
            window_state=str(data.get("window_state", "")),
            annotations=[Annotation.from_dict(a) for a in data.get("annotations", [])],
            derived=list(data.get("derived", [])),
        )

    def series_ids(self) -> set[str]:
        return {c.series_id for d in self.docks for c in d.plot.all_curves()}

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> Layout:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise LayoutError("Le fichier ne contient pas un layout.")
            return cls.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LayoutError(str(exc)) from exc


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a layout dictionary to :data:`LAYOUT_VERSION`."""
    version = int(data.get("version", 0))
    if version > LAYOUT_VERSION:
        log.warning("Layout version %d is newer than supported (%d)", version, LAYOUT_VERSION)
    if version < 1:
        # Version 0 (unversioned drafts): plots held a flat "curves" list.
        for dock in data.get("docks", []):
            plot = dock.get("plot") or {}
            if "curves" in plot and "subplots" not in plot:
                plot["subplots"] = [{"curves": plot.pop("curves")}]
        data["version"] = 1
    return data


def with_layout_suffix(path: str | Path) -> Path:
    path = Path(path)
    return path if path.name.endswith(LAYOUT_SUFFIX) else path.with_name(path.name + LAYOUT_SUFFIX)
