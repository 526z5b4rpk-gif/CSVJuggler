"""Build the stand-alone application with PyInstaller.

    pip install -e ".[package]"
    python packaging/build_exe.py

Result: ``dist/CsvJuggler/`` (the executable and its libraries: copy the whole folder) and
``dist/CsvJuggler-<platform>.zip``. On Windows the executable is ``CsvJuggler.exe``; build on
Windows to get it (PyInstaller does not cross-compile). The GitHub workflow
``.github/workflows/build-windows.yml`` does it on a Windows machine of GitHub.
"""

from __future__ import annotations

import os
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "package"
DIST = ROOT / "dist"
NAME = "CsvJuggler"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def write_icons(folder: Path) -> tuple[Path, Path]:
    """``csvjuggler.ico`` (every size, PNG entries) and ``csvjuggler.png`` (512 px)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtWidgets import QApplication

    from csvjuggler.ui.theme import _icon_image

    _app = QApplication.instance() or QApplication([])
    folder.mkdir(parents=True, exist_ok=True)
    pngs: list[bytes] = []
    for size in ICO_SIZES:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        _icon_image(size).save(buffer, "PNG")
        pngs.append(bytes(data.data()))
    # ICO: header, one 16-byte directory entry per image, then the PNG data.
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = len(header) + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, png in zip(ICO_SIZES, pngs, strict=True):
        side = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    ico = folder / "csvjuggler.ico"
    ico.write_bytes(header + entries + blobs)
    png = folder / "csvjuggler.png"
    _icon_image(512).save(str(png))
    return ico, png


def main() -> int:
    import PyInstaller.__main__

    ico, _png = write_icons(BUILD)
    assets = ROOT / "csvjuggler" / "ui" / "assets"
    args = [
        str(ROOT / "packaging" / "launch.py"),
        "--name",
        NAME,
        "--windowed",  # no console window
        # Find csvjuggler in the sources: PyInstaller does not follow editable installs.
        "--paths",
        str(ROOT),
        "--noconfirm",
        "--clean",
        "--workpath",
        str(BUILD / "work"),
        "--specpath",
        str(BUILD),
        "--distpath",
        str(DIST),
        # .ico on Windows; macOS would need an .icns (the window icon is set at run time).
        *(("--icon", str(ico)) if sys.platform == "win32" else ()),
        "--add-data",
        f"{assets}{os.pathsep}csvjuggler/ui/assets",
        # Not used by CsvJuggler: keep the folder smaller.
        *("--exclude-module", "tkinter"),
        *("--exclude-module", "matplotlib"),
        *("--exclude-module", "IPython"),
        *("--exclude-module", "pytest"),
    ]
    PyInstaller.__main__.run(args)
    platform = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    archive = shutil.make_archive(str(DIST / f"{NAME}-{platform}"), "zip", DIST, NAME)
    print(f"\nApplication : {DIST / NAME}\nArchive     : {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
