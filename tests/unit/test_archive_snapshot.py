"""VM archive snapshot push (v3 V3-2 revised): mirror records + context into the ipo-archive clone.

The headline proof: both files land in the archive clone byte-for-byte, a missing source is
skipped (not an error — first run before context has ever refreshed), and re-running with
unchanged bytes is a true no-op at the file level (so the unit's git-diff-guard sees nothing to
commit).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_script(name: str) -> ModuleType:
    """Load a scripts/*.py module by path (scripts is not an importable package)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_data_dir(tmp_path: Path, records: bytes | None, context: bytes | None) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    if records is not None:
        (data / "ipo_records.parquet").write_bytes(records)
    if context is not None:
        ctx_dir = data / "context"
        ctx_dir.mkdir()
        (ctx_dir / "ipo_context.json").write_bytes(context)
    return data


def test_both_files_land_byte_for_byte(tmp_path: Path) -> None:
    snapshot = _load_script("vm_archive_snapshot")
    data = _make_data_dir(tmp_path, records=b"parquet-bytes", context=b'{"a": 1}')
    archive = tmp_path / "archive"

    copied = snapshot.sync_snapshot(data, archive)

    assert set(copied) == {"ipo_records.parquet", "ipo_context.json"}
    assert (archive / "ipo_records.parquet").read_bytes() == b"parquet-bytes"
    assert (archive / "ipo_context.json").read_bytes() == b'{"a": 1}'


def test_missing_source_is_skipped_not_an_error(tmp_path: Path) -> None:
    snapshot = _load_script("vm_archive_snapshot")
    data = _make_data_dir(tmp_path, records=b"parquet-bytes", context=None)  # no context yet
    archive = tmp_path / "archive"

    copied = snapshot.sync_snapshot(data, archive)

    assert copied == ["ipo_records.parquet"]
    assert not (archive / "ipo_context.json").exists()


def test_rerun_with_unchanged_bytes_is_a_true_no_op(tmp_path: Path) -> None:
    """Re-running with identical source bytes writes identical output — the git-diff-guard sees no
    change and skips the commit, so a healthy no-op cycle never produces empty commits."""
    snapshot = _load_script("vm_archive_snapshot")
    data = _make_data_dir(tmp_path, records=b"parquet-bytes", context=b'{"a": 1}')
    archive = tmp_path / "archive"

    snapshot.sync_snapshot(data, archive)
    before = (archive / "ipo_records.parquet").read_bytes()
    snapshot.sync_snapshot(data, archive)
    after = (archive / "ipo_records.parquet").read_bytes()

    assert before == after


def test_updated_source_bytes_flow_through_on_the_next_run(tmp_path: Path) -> None:
    snapshot = _load_script("vm_archive_snapshot")
    data = _make_data_dir(tmp_path, records=b"v1", context=b'{"v": 1}')
    archive = tmp_path / "archive"

    snapshot.sync_snapshot(data, archive)
    (data / "ipo_records.parquet").write_bytes(b"v2")
    snapshot.sync_snapshot(data, archive)

    assert (archive / "ipo_records.parquet").read_bytes() == b"v2"
