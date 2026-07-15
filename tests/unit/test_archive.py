"""Durable transitions archive (v3 V3-2) — validation, append-only merge, and the pull core.

Proves the guarantees the design rests on: a malformed/truncated drop is REJECTED (never merged);
the union merge is idempotent + order-independent (missed / doubled / out-of-order pulls converge);
append-only never deletes archived history, a rejected drop leaves the archive untouched, and the
archive stays OFF the scoring path. Offline + deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from ipo.archive.merge import merge_transitions
from ipo.archive.pull import pull_merge
from ipo.archive.store import read_archive, write_archive
from ipo.archive.validate import ArchiveRejected, load_validated
from ipo.core.types import VerdictType
from ipo.service.transitions import VerdictTransition


def _t(
    ipo_id: str,
    day: int,
    to_verdict: str = "APPLY",
    *,
    from_verdict: str | None = None,
    prob: float | None = 0.9,
    crossed: bool = True,
) -> VerdictTransition:
    return VerdictTransition(
        ipo_id=ipo_id,
        asof=datetime(2026, 7, day, 18, 0),
        from_verdict=VerdictType(from_verdict) if from_verdict else None,
        to_verdict=VerdictType(to_verdict),
        probability=prob,
        crossed_into_apply=crossed,
    )


def _dump(ts: list[VerdictTransition]) -> list[dict[str, object]]:
    """Compare transition lists by content (order-sensitive on the deterministic merge output)."""
    return [t.model_dump(mode="json") for t in ts]


def _as_json(ts: list[VerdictTransition]) -> str:
    return json.dumps([t.model_dump(mode="json") for t in ts])


# --- validation: don't trust the drop ---------------------------------------------------------


def test_rejects_non_json() -> None:
    with pytest.raises(ArchiveRejected):
        load_validated("this is not json {[")


def test_rejects_truncated_array() -> None:
    # A drop cut off mid-write — the classic truncation the archive must never ingest.
    with pytest.raises(ArchiveRejected):
        load_validated('[{"ipo_id": "x", "asof": "2026-07-14T18:00:00",')


def test_rejects_malformed_row() -> None:
    # Parses as JSON, but a row is missing required fields → must be rejected, not coerced.
    with pytest.raises(ArchiveRejected):
        load_validated('[{"ipo_id": "x"}]')


def test_rejects_non_array() -> None:
    with pytest.raises(ArchiveRejected):
        load_validated('{"ipo_id": "x"}')


def test_accepts_valid_drop() -> None:
    ts = [_t("alpha", 10), _t("beta", 11)]
    loaded = load_validated(_as_json(ts))
    assert _dump(loaded) == _dump(ts)


# --- merge: idempotent, order-independent, append-only ----------------------------------------


def test_union_dedupes_identical() -> None:
    a = _t("alpha", 10)
    assert _dump(merge_transitions([a], [a])) == _dump([a])  # one copy, not two


def test_double_pull_is_idempotent() -> None:
    existing = [_t("alpha", 10)]
    incoming = [_t("alpha", 10), _t("beta", 11)]
    once = merge_transitions(existing, incoming)
    twice = merge_transitions(once, incoming)  # pulling the SAME drop again
    assert _dump(twice) == _dump(once)  # no growth, no change


def test_out_of_order_pulls_converge() -> None:
    earlier, later = _t("alpha", 10), _t("beta", 20)
    # Pull the later drop first, then the earlier one — vs. the other order.
    a = merge_transitions(merge_transitions([], [later]), [earlier])
    b = merge_transitions(merge_transitions([], [earlier]), [later])
    assert _dump(a) == _dump(b)  # same archive regardless of pull order
    assert _dump(a) == _dump([earlier, later])  # and sorted chronologically


def test_append_only_never_deletes_on_a_shorter_drop() -> None:
    full = [_t("alpha", 10), _t("beta", 11), _t("gamma", 12)]
    archive = merge_transitions([], full)
    short_drop = [_t("alpha", 10)]  # a valid-but-incomplete drop
    merged = merge_transitions(archive, short_drop)
    assert _dump(merged) == _dump(full)  # nothing archived was lost


def test_distinct_transitions_for_same_ipo_are_both_kept() -> None:
    # Two genuine changes for one IPO (different asof) are distinct records — both retained.
    t1 = _t("alpha", 10, "MARGINAL", crossed=False)
    t2 = _t("alpha", 12, "APPLY")
    assert len(merge_transitions([t1], [t2])) == 2


# --- store: round-trip + atomic, corrupt archive raises ----------------------------------------


def test_store_roundtrip_and_absent_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "verdict_transitions.json"
    assert read_archive(path) == []  # absent → empty, not an error
    ts = [_t("alpha", 10), _t("beta", 11)]
    write_archive(path, ts)
    assert _dump(read_archive(path)) == _dump(ts)


def test_store_read_corrupt_archive_raises(tmp_path: Path) -> None:
    path = tmp_path / "verdict_transitions.json"
    path.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(ArchiveRejected):  # never silently reset — losing history is worse
        read_archive(path)


# --- pull core: end-to-end, idempotent, rejection leaves the archive untouched ------------------


def test_pull_merge_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "verdict_transitions.json"
    src.write_text(_as_json([_t("alpha", 10), _t("beta", 11)]), encoding="utf-8")
    archive = tmp_path / "archive"
    added = pull_merge(src, archive)
    assert added == 2
    assert _dump(read_archive(archive / "verdict_transitions.json")) == _dump(
        [_t("alpha", 10), _t("beta", 11)]
    )


def test_pull_merge_double_pull_adds_nothing(tmp_path: Path) -> None:
    src = tmp_path / "verdict_transitions.json"
    src.write_text(_as_json([_t("alpha", 10)]), encoding="utf-8")
    archive = tmp_path / "archive"
    assert pull_merge(src, archive) == 1
    assert pull_merge(src, archive) == 0  # second identical pull is a no-op


def test_pull_merge_rejected_drop_leaves_archive_untouched(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    good = tmp_path / "good.json"
    good.write_text(_as_json([_t("alpha", 10)]), encoding="utf-8")
    pull_merge(good, archive)  # seed the archive with one good transition
    before = (archive / "verdict_transitions.json").read_text(encoding="utf-8")

    bad = tmp_path / "bad.json"
    bad.write_text('[{"ipo_id": "x",', encoding="utf-8")  # truncated
    with pytest.raises(ArchiveRejected):
        pull_merge(bad, archive)
    after = (archive / "verdict_transitions.json").read_text(encoding="utf-8")
    assert after == before  # a malformed drop NEVER touches the durable archive


def test_pull_merge_mirrors_records_snapshot(tmp_path: Path) -> None:
    src = tmp_path / "verdict_transitions.json"
    src.write_text(_as_json([_t("alpha", 10)]), encoding="utf-8")
    records = tmp_path / "ipo_records.parquet"
    records.write_bytes(b"PAR1-snapshot")
    archive = tmp_path / "archive"
    pull_merge(src, archive, records=records)
    assert (archive / "ipo_records.parquet").read_bytes() == b"PAR1-snapshot"


def test_pull_merge_tolerates_utf8_bom_in_drop(tmp_path: Path) -> None:
    # A Windows tool may re-save the rendezvous file as UTF-8-with-BOM; the content is still valid,
    # so it must be admitted (the read boundary uses utf-8-sig), not rejected as "malformed".
    src = tmp_path / "verdict_transitions.json"
    src.write_bytes(b"\xef\xbb\xbf" + _as_json([_t("alpha", 10)]).encode("utf-8"))
    archive = tmp_path / "archive"
    assert pull_merge(src, archive) == 1


# --- boundary: the archive is strictly downstream of verdicts, never a model input --------------


def test_scoring_path_does_not_reference_the_archive() -> None:
    """Fast direct check: no scoring-path FILE names ``ipo.archive`` or its symbols (mirrors the
    context-store boundary in test_ipo_context.py; the transitive closure check is extended there).
    """
    root = Path(__file__).resolve().parents[2] / "src" / "ipo"
    scoring_pkgs = ("features", "model", "calibration", "core")
    forbidden = (
        "ipo.archive",
        "merge_transitions",
        "load_validated",
        "ArchiveRejected",
        "pull_merge",
    )
    offenders = [
        f"{py.relative_to(root)} references {sym}"
        for pkg in scoring_pkgs
        for py in (root / pkg).rglob("*.py")
        for sym in forbidden
        if sym in py.read_text(encoding="utf-8")
    ]
    assert not offenders, "the archive must not reach the scoring path: " + "; ".join(offenders)
