"""Generate the MSIX tile/logo assets (GATE 7 — Store) into the desktop app's build/appx/.

electron-builder's appx target uses these branded PNGs instead of its placeholder "SampleAppx"
tiles. Each is the same mark as the app icon/splash: a vertical apply-green gradient with a
centered dark diamond, drawn full-bleed at the exact size Windows expects for each tile.

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


def _tile(width: int, height: int) -> Image.Image:
    """Full-bleed vertical green gradient with a centered dark diamond."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(int(_TOP[i] + (_BOTTOM[i] - _TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=(*color, 255))
    cx, cy = width / 2, height / 2
    r = min(width, height) * 0.30
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=(*_GLYPH, 255))
    return img


def main() -> None:
    """Write every tile PNG into build/appx/."""
    _OUT.mkdir(parents=True, exist_ok=True)
    for name, (w, h) in _TILES.items():
        _tile(w, h).save(_OUT / name, format="PNG")
    print(f"[appx-assets] wrote {len(_TILES)} tiles to {_OUT}")


if __name__ == "__main__":
    main()
