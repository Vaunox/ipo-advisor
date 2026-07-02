"""Build the engine sidecar binary with PyInstaller (GATE 7, step 1).

Ensures the curated demo store + clean transition log exist (so the bundled ``_seed`` is fresh),
then freezes ``packaging/engine_entry.py`` via ``packaging/ipo-engine.spec`` into
``packaging/dist/ipo-engine/``. electron-builder picks that folder up as an extraResource.

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
    """Seed the demo store, then freeze the engine into packaging/dist/ipo-engine/."""
    # 1. Refresh the curated demo store + clean 6-transition log that get bundled as _seed.
    print("[build] seeding demo store …")
    subprocess.run([sys.executable, "-m", "scripts.seed_demo_store"], cwd=_ROOT, check=True)

    # 2. Freeze the engine (onedir) via the spec.
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
