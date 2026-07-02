"""Phase 7 packaging: the sidecar's first-run seed provisioning is safe and idempotent.

The frozen engine ships a curated demo store as a read-only resource and copies it into the
user-writable data dir on first launch. This must (a) populate an empty dir, (b) never overwrite
existing user data, and (c) no-op cleanly when there is no bundled seed (the dev-from-source case).
"""

from __future__ import annotations

from pathlib import Path

from ipo.service.runner import _provision_data_dir


def _make_seed(resource_root: Path) -> None:
    seed = resource_root / "_seed"
    seed.mkdir(parents=True)
    (seed / "ipo_records.parquet").write_bytes(b"SEED-PARQUET")
    (seed / "verdict_transitions.json").write_text("[]", encoding="utf-8")


def test_provisions_empty_data_dir(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"

    _provision_data_dir(data_dir, res)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"SEED-PARQUET"
    assert (data_dir / "verdict_transitions.json").read_text(encoding="utf-8") == "[]"


def test_never_overwrites_existing_user_data(tmp_path: Path) -> None:
    res = tmp_path / "bundle"
    _make_seed(res)
    data_dir = tmp_path / "userdata"
    data_dir.mkdir()
    (data_dir / "ipo_records.parquet").write_bytes(b"USER-DATA")  # already present

    _provision_data_dir(data_dir, res)

    assert (data_dir / "ipo_records.parquet").read_bytes() == b"USER-DATA"  # untouched
    # a missing sibling is still filled in without clobbering the one that existed
    assert (data_dir / "verdict_transitions.json").read_text(encoding="utf-8") == "[]"


def test_noop_without_bundled_seed(tmp_path: Path) -> None:
    res = tmp_path / "bundle"  # no _seed/ dir (dev-from-source)
    res.mkdir()
    data_dir = tmp_path / "userdata"

    _provision_data_dir(data_dir, res)

    assert data_dir.is_dir()  # created, but empty — nothing to seed
    assert list(data_dir.iterdir()) == []
