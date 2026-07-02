"""PyInstaller entry point for the bundled engine sidecar.

A thin wrapper so the frozen binary has a stable, import-light entry: it simply hands off to
``ipo.service.runner.main`` (argparse handles ``--port`` / ``--host`` / ``--data-dir``). Kept
separate from the package so the spec's Analysis has a single, obvious script to trace.
"""

from __future__ import annotations

from ipo.service.runner import main

if __name__ == "__main__":
    main()
