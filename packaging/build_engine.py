"""Build the engine sidecar binary with PyInstaller (GATE 7, step 1).

Freezes ``packaging/engine_entry.py`` via ``packaging/ipo-engine.spec`` into
``packaging/dist/ipo-engine/`` (live-only build — no demo store is bundled). electron-builder
picks that folder up as an extraResource.

    python -m packaging.build_engine
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = _ROOT / "packaging" / "ipo-engine.spec"
_DIST = _ROOT / "packaging" / "dist"
_WORK = _ROOT / "packaging" / "build"


def main() -> int:
    """Freeze the engine into packaging/dist/ipo-engine/ (live-only — no bundled demo store)."""
    # Freeze the engine (onedir) via the spec. No demo seed is bundled: the packaged app starts
    # empty and fills purely from live NSE ingestion.
    print("[build] running PyInstaller …")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(_SPEC),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(_DIST),
            "--workpath",
            str(_WORK),
        ],
        cwd=_ROOT,
        check=True,
    )

    exe = _DIST / "ipo-engine" / ("ipo-engine.exe" if sys.platform == "win32" else "ipo-engine")
    if not exe.is_file():
        print(f"[build] FAILED — expected binary not found at {exe}", file=sys.stderr)
        return 1
    print(f"[build] OK -> {exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
