"""Annotations: text, bubble attached to a curve, delta between two curve points, vertical
line, horizontal line, X region.

X coordinates are stored in the time unit of the series (seconds after import scaling),
never in pixels. Annotations are attached to a dataset (alias + file path) and are saved
in the layout and in a companion file ``<file>.annotations.json`` next to the CSV.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

AnnotationKind = Literal["text", "bubble", "delta", "vline", "hline", "region"]
COMPANION_SUFFIX = ".annotations.json"
COMPANION_VERSION = 1


@dataclass
class Annotation:
    kind: AnnotationKind
    x: float = 0.0
    y: float = 0.0
    x2: float = 0.0
    """End of an X region; X of point B of a delta."""
    text: str = ""
    color: str = "#d62728"
    font_size: int = 10
    text_background: str | None = "#ffffff"
    opacity: float = 1.0
    locked: bool = False
    arrow: bool = False
    """Text only: the bubble has a tail pointing to the anchor point."""
    show_coords: bool = True
    """Text and bubble: show the anchor point coordinates in the bubble."""
    series_id: str = ""
    """Bubble and delta (point A): curve the point is attached to (y = curve value at ``x``)."""
    series_id_b: str = ""
    """Delta only: curve of point B, at ``x2``."""
    offset_x: float = 24.0
    offset_y: float = -36.0
    """Bubble only: bottom-left corner of the bubble relative to its point, in pixels
    (y downwards)."""
    link_all: bool = False
    """Vertical line only: shown on every graph of the same X sync group."""
    axis_id: str = "y0"
    """Y axis of ``y`` (text, horizontal line)."""
    plot_id: str = ""
    """Dock id of the graph where the annotation was created."""
    subplot: int = 0
    dataset_alias: str = ""
    dataset_path: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Annotation:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    @property
    def center_x(self) -> float:
        return (self.x + self.x2) / 2 if self.kind in ("region", "delta") else self.x


class AnnotationStore(QObject):
    """All annotations of the session, keyed by id.

    The store keeps its own copies and hands out copies: changing an annotation always goes
    through :meth:`update`, which emits :attr:`annotations_changed`.
    """

    annotations_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: dict[str, Annotation] = {}

    def all(self) -> list[Annotation]:
        return [copy.deepcopy(a) for a in self._items.values()]

    def get(self, ann_id: str) -> Annotation | None:
        ann = self._items.get(ann_id)
        return copy.deepcopy(ann) if ann is not None else None

    def for_dataset(self, alias: str) -> list[Annotation]:
        return [copy.deepcopy(a) for a in self._items.values() if a.dataset_alias == alias]

    def add(self, annotation: Annotation) -> Annotation:
        self._items[annotation.id] = copy.deepcopy(annotation)
        self.annotations_changed.emit()
        return copy.deepcopy(annotation)

    def update(self, annotation: Annotation) -> None:
        if self._items.get(annotation.id) != annotation:
            self._items[annotation.id] = copy.deepcopy(annotation)
            self.annotations_changed.emit()

    def remove(self, ann_id: str) -> None:
        if self._items.pop(ann_id, None) is not None:
            self.annotations_changed.emit()

    def merge(self, annotations: list[Annotation]) -> None:
        """Add or replace by id (used when loading a companion file or a layout)."""
        if not annotations:
            return
        for a in annotations:
            self._items[a.id] = copy.deepcopy(a)
        self.annotations_changed.emit()

    def clear(self) -> None:
        if self._items:
            self._items.clear()
            self.annotations_changed.emit()


def companion_path(csv_path: str | Path) -> Path:
    """``mesure.csv`` → ``mesure.csv.annotations.json``."""
    csv_path = Path(csv_path)
    return csv_path.with_name(csv_path.name + COMPANION_SUFFIX)


def save_companion(csv_path: str | Path, annotations: list[Annotation]) -> Path:
    path = companion_path(csv_path)
    data = {
        "version": COMPANION_VERSION,
        "dataset_path": str(csv_path),
        "annotations": [a.to_dict() for a in annotations],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def load_companion(csv_path: str | Path) -> list[Annotation]:
    path = companion_path(csv_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Annotation.from_dict(a) for a in data.get("annotations", [])]
    except (OSError, ValueError, TypeError) as exc:
        log.warning("Cannot read %s: %s", path, exc)
        return []
