"""Default colour palette and colour cycling."""

from __future__ import annotations

from collections.abc import Iterable

# Tableau-10 like palette, readable on dark and light backgrounds.
DEFAULT_PALETTE: tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


def color_for_index(index: int, palette: tuple[str, ...] = DEFAULT_PALETTE) -> str:
    """Return the palette colour for ``index`` (cycling)."""
    return palette[index % len(palette)]


def next_color(used: Iterable[str], palette: tuple[str, ...] = DEFAULT_PALETTE) -> str:
    """Return the first palette colour not in ``used``, or cycle if all are used."""
    used_list = [c.lower() for c in used]
    for color in palette:
        if color.lower() not in used_list:
            return color
    return color_for_index(len(used_list), palette)
