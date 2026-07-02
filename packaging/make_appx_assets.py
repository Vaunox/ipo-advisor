"""Generate the MSIX tile/logo assets (GATE 7 — Store) into the desktop app's build/appx/.

electron-builder's appx target uses these branded PNGs instead of its placeholder "SampleAppx"
tiles. For an MSIX app Windows draws the taskbar/Start icon from THESE assets (not the exe icon),
so each is the SAME mark as the app icon (packaging/make_icon.py) and the splash: a green-gradient
**rounded** square with a centered dark diamond, on a transparent background (the manifest's dark
backgroundColor shows through), so the taskbar/Start/tile all match the in-app + splash mark.

    python packaging/make_appx_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_OUT = (
    Path(__file__).resolve().parent.parent / "src" / "ipo" / "apps" / "desktop" / "build" / "appx"
)
_TOP = (61, 220, 132)  # --apply #3ddc84
_BOTTOM = (31, 157, 85)  # #1f9d55
_GLYPH = (4, 18, 10)  # near-black green

# electron-builder appx asset filenames -> (width, height).
_TILES = {
    "Square44x44Logo.png": (44, 44),
    "Square71x71Logo.png": (71, 71),
    "Square150x150Logo.png": (150, 150),
    "Square310x310Logo.png": (310, 310),
    "Wide310x150Logo.png": (310, 150),
    "StoreLogo.png": (50, 50),
    "SplashScreen.png": (620, 300),
}


def _mark(size: int) -> Image.Image:
    """The brand mark at ``size`` — a green-gradient rounded square + diamond (matches icon.ico)."""
    grad = Image.new("RGB", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(size - 1, 1)
        gd.line(
            [(0, y), (size, y)],
            fill=tuple(int(_TOP[i] + (_BOTTOM[i] - _TOP[i]) * t) for i in range(3)),
        )
    mask = Image.new("L", (size, size), 0)
    inset = max(1, round(size * 0.055))
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, size - inset, size - inset], radius=round(size * 0.20), fill=255
    )
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    c, r = size / 2, size * 0.24
    ImageDraw.Draw(img).polygon(
        [(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=(*_GLYPH, 255)
    )
    return img


def _tile(width: int, height: int) -> Image.Image:
    """Square tiles ARE the mark; non-square tiles center the mark on transparent."""
    if width == height:
        return _mark(width)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mark = _mark(min(width, height))
    canvas.paste(mark, ((width - mark.width) // 2, (height - mark.height) // 2), mark)
    return canvas


def main() -> None:
    """Write every tile PNG into build/appx/."""
    _OUT.mkdir(parents=True, exist_ok=True)
    for name, (w, h) in _TILES.items():
        _tile(w, h).save(_OUT / name, format="PNG")
    print(f"[appx-assets] wrote {len(_TILES)} tiles to {_OUT}")


if __name__ == "__main__":
    main()
