"""Run the VM read-API server (v3 V3-1c) — the read plane the app fetches records + context from.

Deploy on the Oracle VM behind the scheduled fetch jobs (systemd timers running ``refresh_from_nse``
+ ``refresh_context.py`` write into ``--data-dir``; this serves them read-only). It is GET-only and
never runs the model. The served data is **public and token-free** (IPO records + the token-free
context cache), so remote exposure carries no secret; still, restrict inbound to the app where you
can (Oracle security list). See the blueprint Part II / operations manual.

    python scripts/run_vm_server.py --data-dir /path/to/vm-data --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.core.logging import configure_logging
from ipo.vm.server import create_vm_app


def main() -> None:  # pragma: no cover - runtime entrypoint (server loop)
    parser = argparse.ArgumentParser(description="Run the VM read-only data-plane API.")
    parser.add_argument(
        "--data-dir", required=True, help="the VM's data directory (where the fetch jobs write)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address (0.0.0.0 to serve the app)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    # Structured logs to the VM's data dir (an unattended VM needs a durable trail; V3-3 uses it).
    configure_logging("INFO", json_output=True, file_path=data_dir / "logs" / "vm.log")

    import uvicorn

    uvicorn.run(create_vm_app(data_dir), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
