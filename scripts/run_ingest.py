"""Run a Layer-1 ingest from the configured sources into the Parquet store.

Thin shell over ``ipo.data`` (production logic lives in the package). Builds the
curated seed source and the Parquet repository from config, runs the pipeline over
every seeded IPO, and prints the run report.

Usage:
    python scripts/run_ingest.py [--env dev|prod]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ipo.core.config import load_config
from ipo.core.logging import configure_logging, get_logger
from ipo.data.ingest.pipeline import IngestPipeline
from ipo.data.sources.csv_seed import CsvSeedSource
from ipo.data.store.repository import ParquetRepository

_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Parse args, build the pipeline from config, run the ingest, print the report."""
    parser = argparse.ArgumentParser(description="Run a Layer-1 IPO ingest.")
    parser.add_argument("--env", default=None, help="environment (dev|prod)")
    args = parser.parse_args()

    config = load_config(env=args.env)
    configure_logging(config.logging.level, json_output=config.logging.json_output)
    log = get_logger("ipo.scripts.run_ingest")

    seed_source = CsvSeedSource(_REPO_ROOT / config.ingest.seed_csv)
    repo = ParquetRepository(_REPO_ROOT / config.storage.data_dir)
    pipeline = IngestPipeline(
        [seed_source],
        repo,
        cross_check_fields=frozenset(config.ingest.official_required_fields),
        source_priority=["csv_seed", "chittorgarh"],
    )

    report = pipeline.run(seed_source.ipo_ids())
    log.info(
        "run_ingest_done",
        extra={
            "records_ingested": report.records_ingested,
            "labels_built": report.labels_built,
            "bad_records": len(report.bad_records),
        },
    )
    print(
        f"Ingested {report.records_ingested} records, "
        f"built {report.labels_built} labels, "
        f"{len(report.bad_records)} bad, {len(report.conflicts)} conflicts."
    )


if __name__ == "__main__":
    main()
