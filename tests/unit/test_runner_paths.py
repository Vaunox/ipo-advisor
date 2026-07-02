"""Phase 7 packaging: the sidecar's store provisioning is dev-safe, versioned, and idempotent.

Provisioning only runs for the packaged app (``manage=True``); dev-from-source is a no-op so the
developer's ``data_store`` is never touched. When managing, it is **versioned** (``_SEED_VERSION``):
a fresh install or an update that changed the shipped data clears the old store so stale/demo
records don't persist; an unchanged version keeps the user's live-accumulated data. A live-only
build ships no seed, so a mismatch just clears the store and live ingestion refills it.
"""

from __future__ import annotations

from pathlib import Path

from ipo.service.runner import _SEED_VERSION, _provision_data_dir


def _make_seed(resource_root: Path) -> None:
    seed = resource_root / "_seed"
    seed.mkdir(parents=True)
    (seed / "ipo_records.parquet").write_bytes(b"SEED-PARQUET")
    (seed / "verdict_transitions.json").write_text("[]", encoding="utf-8")


def test_dev_is_a_noop(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"DEV-DATA")

    _provision_data_dir(data_dir, res, manage=False)  # dev-from-source

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"DEV-DATA"  # untouched
    assert not (data_dir / "seed_version").exists()


def test_provisions_empty_data_dir(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"

    _provision_data_dir(data_dir, res, manage=True)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"SEED-PARQUET"
    assert (data_dir / "seed_version").read_text(encoding="utf-8") == _SEED_VERSION


def test_keeps_data_when_version_matches(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"LIVE-DATA")  # user's accumulated store
    (data_dir / "seed_version").write_text(_SEED_VERSION, encoding="utf-8")  # up to date

    _provision_data_dir(data_dir, res, manage=True)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"LIVE-DATA"  # kept, not clobbered


def test_clears_stale_data_on_version_mismatch(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"OLD-DEMO")  # from a previous install
    # no seed_version marker → stale

    _provision_data_dir(data_dir, res, manage=True)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"SEED-PARQUET"  # re-provisioned
    assert (data_dir / "seed_version").read_text(encoding="utf-8") == _SEED_VERSION


def test_live_only_clears_stale_without_seed(tmp_path: Path) -> None:
    res = tmp_path / "bundle"  # no _seed/ (live-only build)
    res.mkdir()
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"OLD-DEMO")  # stale from an older install

    _provision_data_dir(data_dir, res, manage=True)

    # No seed to restore → the stale store is cleared (live ingest will refill it) and marked.
    assert not (data_dir / "ipo_records.parquet").exists()
    assert (data_dir / "seed_version").read_text(encoding="utf-8") == _SEED_VERSION
