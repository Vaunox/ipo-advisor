# PyInstaller spec for the IPO Advisor engine sidecar (onedir).
#
# Produces packaging/dist/ipo-engine/ipo-engine.exe + an _internal/ folder, which electron-builder
# copies into the app's resources/engine/. The Electron shell spawns it with --port <free> and
# --data-dir <userData>. Read-only artifacts (calibrator, held-out reliability report, Nifty
# regime series) and the curated demo store (_seed) are bundled so the binary is self-contained.
#
# Build:  pyinstaller packaging/ipo-engine.spec --noconfirm   (see packaging/build_engine.py)

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # packaging/ -> repo root  # noqa: F821

# Bundled read-only artifacts: (source-on-disk, dest-dir-in-bundle). These land under sys._MEIPASS
# at runtime, where ipo.service.runner._resource_root() resolves them.
datas = [
    # Config drives feature weights / thresholds — MUST be bundled or verdicts silently change.
    (str(ROOT / "config" / "default.yaml"), "config"),
    (str(ROOT / "config" / "sources.yaml"), "config"),
    (str(ROOT / "config" / "env" / "dev.yaml"), "config/env"),
    (str(ROOT / "config" / "env" / "prod.yaml"), "config/env"),
    (str(ROOT / "models" / "calibrator.json"), "models"),
    (str(ROOT / "models" / "reliability.json"), "models"),
    (str(ROOT / "data" / "backfill" / "nifty.csv"), "data/backfill"),
    (str(ROOT / "data" / "backfill" / "vix.csv"), "data/backfill"),  # v2 B2 — cold-flag VIX read
    # Live-only build: NO bundled demo record store. The app starts empty and fills purely from
    # live NSE ingestion (ipo.data.ingest.live); no fabricated/curated companies ship.
]
binaries: list = []
# BUILD BOUNDARY: the engine bundles ONLY the `ipo` package (src/ipo/) + the deps below. Repo dirs
# outside src/ipo/ — notably `scripts/` and `research/` (the FAILED-gate enhancement backfill; see
# research/README.md, docs/ENHANCEMENT_GATE.md) — are NOT collected, NOT in `datas`, and NOT on
# `pathex`, so they can never be bundled or wired live. Keep failed/experimental code in research/.
#
# Our package plus the ASGI stack: uvicorn resolves its loop/protocol impls dynamically, so its
# submodules must be collected explicitly or the frozen server fails to start.
hiddenimports = collect_submodules("ipo") + collect_submodules("uvicorn")

for pkg in (
    "pyarrow",
    "pydantic",
    "pydantic_core",
    "fastapi",
    "starlette",
    "requests",  # live NSE ingestion (HTTP)
    "certifi",  # CA bundle requests needs for TLS to nseindia.com
    "urllib3",
    "charset_normalizer",
    "idna",
    "bs4",  # pulled in via ipo.data.sources.chittorgarh (collected with the ipo package)
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "engine_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ipo-engine",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # sidecar: stdout/stderr piped to the Electron shell for logging
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ipo-engine",
)
