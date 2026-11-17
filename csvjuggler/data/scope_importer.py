"""Specifics of TwinCAT Scope CSV exports.

A Scope export starts with a metadata block (``Name``, ``File``, ``StartTime``…), then one
line per channel attribute (``Name``, ``SymbolName``, ``DataType``, ``SampleTime[ms]``,
``Unit``…), the first field being the attribute key. Data come as time/value pairs, one
pair per channel, times in milliseconds, often with a decimal comma.

The generic importer handles the structure; this module recognises the format and sets the
Scope defaults.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from csvjuggler.data.importer import ImportSettings

_SCOPE_KEYS = re.compile(
    r"^\s*\"?(SymbolName|SampleTime|DataType|VariableSize|SymbolBased|IndexGroup|TwinCAT)",
    re.IGNORECASE,
)


def is_scope_export(lines: list[str]) -> bool:
    """At least two Scope channel attribute lines in the head of the file."""
    return sum(1 for ln in lines if _SCOPE_KEYS.match(ln)) >= 2


def apply_defaults(settings: ImportSettings) -> None:
    """Scope times are in milliseconds."""
    if settings.time_unit == "s":
        settings.time_unit = "ms"
