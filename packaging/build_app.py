"""Build the full installable Windows app (GATE 7) — one command, in order.

Runs every prerequisite then invokes electron-builder:

    1. build_engine.py     -> packaging/dist/ipo-engine/ (frozen sidecar + bundled seed)
    2. pwa `npm run build` -> pwa/dist/ (the React dashboard)
    3. desktop `npm run dist` (electron-builder) -> desktop/release/IPO-Advisor-Setup-*.exe

The engine binary and the PWA dist are pulled in as electron-builder extraResources, so the
installer is fully self-contained. Requires Node/npm on PATH and the venv Python running this.

The desktop app icon (build/icon.ico) and the MSIX tiles (build/appx/*) are curated, committed
assets (the V3-12 "vertex-jewel" logo) — not generated as part of this build. There is no
regenerable source for them in this repo, so nothing here touches them; replace the files
directly if the branding ever changes.

    python packaging/build_app.py [--skip-install]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PWA = _ROOT / "src" / "ipo" / "apps" / "pwa"
_DESKTOP = _ROOT / "src" / "ipo" / "apps" / "desktop"


def _run(cmd: list[str], cwd: Path, *, shell: bool = False) -> None:
    print(f"\n[build_app] $ {' '.join(cmd)}  (cwd={cwd.relative_to(_ROOT)})")
    subprocess.run(cmd, cwd=cwd, check=True, shell=shell)


def main() -> int:
    """Run engine → pwa → installer in sequence."""
    skip_install = "--skip-install" in sys.argv
    npm = "npm.cmd" if sys.platform == "win32" else "npm"

    _run([sys.executable, "packaging/build_engine.py"], _ROOT)
    if not skip_install:
        _run([npm, "install"], _PWA)
        _run([npm, "install"], _DESKTOP)
    _run([npm, "run", "build"], _PWA)
    _run([npm, "run", "dist"], _DESKTOP)

    out = _DESKTOP / "release"
    installers = list(out.glob("IPO-Advisor-Setup-*.exe")) if out.is_dir() else []
    if not installers:
        print("[build_app] FAILED — no installer produced under desktop/release/", file=sys.stderr)
        return 1
    for exe in installers:
        print(f"[build_app] OK -> {exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
