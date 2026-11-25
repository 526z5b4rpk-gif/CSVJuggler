"""Packaging helpers: the multi-size Windows icon."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ico_has_every_size_as_png(qtbot, tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import build_exe
    finally:
        sys.path.pop(0)
    ico, png = build_exe.write_icons(tmp_path)
    data = ico.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind, count) == (0, 1, len(build_exe.ICO_SIZES))
    sizes = []
    for i in range(count):
        width, _h, _c, _r, _planes, _bpp, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * i
        )
        sizes.append(width or 256)
        assert data[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert offset + length <= len(data)
    assert sizes == list(build_exe.ICO_SIZES)
    assert png.read_bytes()[:4] == b"\x89PNG"
