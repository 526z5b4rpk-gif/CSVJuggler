"""Application look: palette and icon."""

from __future__ import annotations

from PySide6.QtGui import QPalette

from csvjuggler.ui.theme import _icon_image, app_icon, light_palette


def test_icon_has_every_size_and_is_drawn(qtbot) -> None:
    icon = app_icon()
    sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
    assert {(16, 16), (32, 32), (256, 256)} <= sizes
    for size in (16, 64):
        image = _icon_image(size)
        assert image.pixelColor(size // 2, size // 2).alpha() == 255  # opaque tile
        assert image.pixelColor(0, 0).alpha() == 0  # rounded transparent corner


def test_light_palette_even_in_dark_mode(qtbot) -> None:
    palette = light_palette()
    assert palette.color(QPalette.ColorRole.Base).lightness() > 240
    assert palette.color(QPalette.ColorRole.Text).lightness() < 60
