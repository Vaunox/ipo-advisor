"""Generate the desktop app icon (GATE 7) — a branded .ico for electron-builder.

Draws the same mark as the splash: a green-gradient rounded square with a dark diamond, exported
as a multi-resolution ``icon.ico`` under the desktop app's ``build/`` dir (electron-builder's
default Windows icon location).

    python packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_OUT = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ipo"
    / "apps"
    / "desktop"
    / "build"
    / "icon.ico"
)
_SIZE = 256
_TOP = (61, 220, 132)  # --apply #3ddc84
_BOTTOM = (31, 157, 85)  # #1f9d55
_GLYPH = (4, 18, 10)  # near-black green (matches splash logo text)


def _gradient() -> Image.Image:
    """Vertical apply-green gradient, one drawn line per row."""
    img = Image.new("RGB", (_SIZE, _SIZE))
    draw = ImageDraw.Draw(img)
    for y in range(_SIZE):
        t = y / (_SIZE - 1)
        color = tuple(int(_TOP[i] + (_BOTTOM[i] - _TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (_SIZE, y)], fill=color)
    return img


def main() -> None:
    """Compose the icon and write the multi-size .ico."""
    icon = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))

    # Rounded-square mask → paste the gradient through it.
    mask = Image.new("L", (_SIZE, _SIZE), 0)
    inset = 14
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, _SIZE - inset, _SIZE - inset], radius=52, fill=255
    )
    icon.paste(_gradient(), (0, 0), mask)

    # Centered diamond glyph.
    c, r = _SIZE // 2, 62
    ImageDraw.Draw(icon).polygon(
        [(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=(*_GLYPH, 255)
    )

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(
        _OUT, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    print(f"[icon] wrote {_OUT}")


if __name__ == "__main__":
    main()
