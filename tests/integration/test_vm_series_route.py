"""`/subscription-series` — the DP-2 read route (v3-DP).

Proves the obligations the blueprint sets, against the synthetic shapes in
``tests/fixtures/series/``: GET-only, bounded, honestly empty, and volume-contained.

The route's real design work is volume: it is the first route serving a TIME SERIES rather than
current state, so the payload — not just the request rate — had to be reasoned about.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ipo.vm.models import SeriesEnvelope
from ipo.vm.server import _RATE_LIMIT_REQUESTS, create_vm_app

# Committed JSON in the store's own on-disk shape. Loaded by Path — the PRE-EXISTING convention of
# this directory (cf. tests/unit/test_nse.py and test_allotment.py, which read
# tests/fixtures/*.json the same way); tests/ is deliberately not a package. The `series/`
# subdirectory is new; the loading pattern is not.
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "series"

FULL = "fixture-testco"  # complete trajectory, incl. a weekend flat stretch
SPARSE = "fixture-mockon"  # a single sample — recorded once, not broken
GAPPED = "fixture-gapco"  # a fetch-failure window: real absence, never interpolated
CORRUPT = "fixture-corrupt"  # a truncated file — a torn write for a REAL id
EMPTY = "fixture-neverrec"  # NO FILE — never recorded; absence is the fixture


def _seed(data_dir: Path) -> Path:
    """Copy every fixture series into ``data_dir/series`` — the layout the route reads."""
    series = data_dir / "series"
    series.mkdir(parents=True, exist_ok=True)
    for src in _FIXTURES.glob("*.json"):
        shutil.copy(src, series / src.name)
    return series


def _client(tmp_path: Path) -> TestClient:
    _seed(tmp_path)
    return TestClient(create_vm_app(tmp_path))


# --- the shapes -------------------------------------------------------------


def test_full_trajectory_is_served_oldest_first(tmp_path: Path) -> None:
    body = _client(tmp_path).get(f"/subscription-series?ipo_id={FULL}").json()
    env = SeriesEnvelope.model_validate(body)  # don't trust a 200 — parse it
    assert env.ipo_id == FULL
    assert len(env.samples) == 48
    stamps = [s.captured_at for s in env.samples]
    assert stamps == sorted(stamps), "samples must be ordered oldest-first"
    # The book builds, so the curve rises overall.
    assert env.samples[-1].qib_sub is not None and env.samples[0].qib_sub is not None
    assert env.samples[-1].qib_sub > env.samples[0].qib_sub


def test_freshness_is_per_ipo_not_global(tmp_path: Path) -> None:
    """DP-3 must read THIS curve's own clock — a finished curve is complete, not stale."""
    client = _client(tmp_path)
    full = SeriesEnvelope.model_validate(client.get(f"/subscription-series?ipo_id={FULL}").json())
    sparse = SeriesEnvelope.model_validate(
        client.get(f"/subscription-series?ipo_id={SPARSE}").json()
    )
    assert full.refreshed_at == max(s.captured_at for s in full.samples)
    assert sparse.refreshed_at == sparse.samples[0].captured_at
    assert full.refreshed_at != sparse.refreshed_at, "freshness must be per-IPO, not shared"


def test_a_single_sample_is_a_valid_series(tmp_path: Path) -> None:
    """An IPO recorded once (the recorder deployed mid-book) is sparse, not broken."""
    env = SeriesEnvelope.model_validate(
        _client(tmp_path).get(f"/subscription-series?ipo_id={SPARSE}").json()
    )
    assert len(env.samples) == 1
    assert env.refreshed_at is not None


def test_a_fetch_gap_is_absent_samples_never_invented_ones(tmp_path: Path) -> None:
    """DP-1 banks NOTHING on a failed fetch, so the gap must survive to the wire as real absence.

    This is what lets DP-3 draw a BROKEN line instead of an interpolated bridge — the route must
    not helpfully fill a hole the recorder deliberately refused to fabricate.
    """
    client = _client(tmp_path)
    full = SeriesEnvelope.model_validate(client.get(f"/subscription-series?ipo_id={FULL}").json())
    gapped = SeriesEnvelope.model_validate(
        client.get(f"/subscription-series?ipo_id={GAPPED}").json()
    )
    assert len(gapped.samples) == len(full.samples) - 12
    times = [s.captured_at for s in gapped.samples]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert max(gaps).total_seconds() > 30 * 60, "the fetch-failure window vanished"
    assert times == sorted(times)


# --- honest degradation (the months-long common case) -----------------------


def test_unknown_ipo_id_is_an_empty_envelope_not_an_error(tmp_path: Path) -> None:
    """For MONTHS most IPOs have no series. That must read as 'not recorded', never as failure."""
    resp = _client(tmp_path).get(f"/subscription-series?ipo_id={EMPTY}")
    assert resp.status_code == 200
    env = SeriesEnvelope.model_validate(resp.json())
    assert env.ipo_id == EMPTY
    assert env.samples == []
    assert env.refreshed_at is None  # honestly "nothing recorded", not the epoch


def test_missing_param_is_4xx_and_unknown_ipo_is_200_empty(tmp_path: Path) -> None:
    """The ONE genuine client error, pinned AGAINST its look-alike.

    These two must never collapse into each other: a MALFORMED REQUEST (no ``ipo_id`` at all) is the
    caller's bug and gets a 4xx; a VALID request for an IPO with nothing recorded is the normal,
    months-long answer and gets a 200 with an empty list. Asserting only the 4xx would leave the
    distinction untested, which is the part that actually matters — an unknown IPO answering 4xx
    would tell the app "you asked wrong" when the truth is "we never watched that one".
    """
    client = _client(tmp_path)

    malformed = client.get("/subscription-series")
    assert 400 <= malformed.status_code < 500, "a missing required param must be a client error"
    assert malformed.status_code != 404, "must not be confusable with 'unknown IPO'"

    unknown = client.get(f"/subscription-series?ipo_id={EMPTY}")
    assert unknown.status_code == 200, "an unrecorded IPO is not a client error"
    assert SeriesEnvelope.model_validate(unknown.json()).samples == []

    assert malformed.status_code != unknown.status_code, "the two cases must stay distinguishable"


def test_corrupt_series_file_is_empty_200_and_LOGS_A_WARNING(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A torn file for a REAL id: empty envelope + a logged warning, never a 500.

    The blueprint requires the warning, not just the 200, and that is the load-bearing half. On the
    wire a corrupt series and a never-recorded one look identical — both empty — so without the log
    a genuine VM-side fault would be indistinguishable from honest absence, which is exactly the
    silent-failure class this project treats as the enemy. The 200 protects the box; the warning
    protects the diagnosis.

    Uses a COMMITTED truncated fixture (a valid prefix cut mid-object — what a torn write actually
    looks like) rather than random bytes.
    """
    _seed(tmp_path)
    assert (tmp_path / "series" / f"{CORRUPT}.json").is_file(), "corrupt fixture did not seed"

    with caplog.at_level(logging.WARNING, logger="ipo.series.store"):
        resp = TestClient(create_vm_app(tmp_path)).get(f"/subscription-series?ipo_id={CORRUPT}")

    assert resp.status_code == 200, "a torn read must not 500 the box"
    env = SeriesEnvelope.model_validate(resp.json())
    assert env.samples == []
    assert env.ipo_id == CORRUPT

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a corrupt series was served as empty with NO warning — silent failure"
    assert any(
        r.message == "series_read_failed" for r in warnings
    ), f"expected the series_read_failed event; got {[r.message for r in warnings]}"
    assert any(
        getattr(r, "ipo_id", None) == CORRUPT for r in warnings
    ), "the warning must name which IPO failed, or it cannot be acted on"


def test_a_corrupt_file_does_not_poison_the_other_series(tmp_path: Path) -> None:
    """Per-IPO files bound the blast radius on the READ side too."""
    client = _client(tmp_path)
    assert client.get(f"/subscription-series?ipo_id={CORRUPT}").json()["samples"] == []
    assert len(client.get(f"/subscription-series?ipo_id={FULL}").json()["samples"]) == 48


def test_an_ipo_id_unsafe_as_a_filename_cannot_escape_the_store(tmp_path: Path) -> None:
    """A traversal attempt is refused into the same empty envelope — no file read, no 500."""
    (tmp_path / "secret.json").write_text('["nope"]', encoding="utf-8")
    client = _client(tmp_path)
    for evil in ("../secret", "../../etc/passwd", "a/b"):
        resp = client.get("/subscription-series", params={"ipo_id": evil})
        assert resp.status_code == 200
        assert SeriesEnvelope.model_validate(resp.json()).samples == []


# --- the volume decision ----------------------------------------------------


def test_the_wire_projection_strips_the_raw_blob(tmp_path: Path) -> None:
    """DP-2's real design decision, pinned by test so a later edit cannot quietly re-add ~900 KB.

    The STORE keeps the complete NSE response and every category row (DP-1: a field discarded at
    collection can never be recovered). The WIRE must not carry them: measured on the first real
    banked sample a stored row is ~6.2 KB, so a full trajectory would be ~900 KB per detail-page
    open against a 1 vCPU / 1 GB box.
    """
    body = _client(tmp_path).get(f"/subscription-series?ipo_id={FULL}").json()
    sample = body["samples"][0]
    assert "raw_response" not in sample
    assert "categories" not in sample
    assert "raw_response_hash" not in sample
    # ...and the fields DP-3 actually plots ARE present.
    for field in ("captured_at", "qib_sub", "nii_sub", "retail_sub", "source_update_time"):
        assert field in sample

    # The store row really did carry the heavy fields — otherwise this test proves nothing.
    stored = json.loads((tmp_path / "series" / f"{FULL}.json").read_text(encoding="utf-8"))[0]
    assert "raw_response" in stored and "categories" in stored

    # And the saving is real, not notional. The threshold is deliberately loose because the FIXTURE
    # understates it: its raw_response carries one category row, where a real NSE response carries
    # ~18 plus the full document. Measured on the first genuinely banked sample the ratio is ~16x
    # (6,163 -> 376 bytes); here it is ~3x. Asserting the real ratio against synthetic data would
    # be pinning the fixture's proportions rather than the route's behaviour.
    assert len(json.dumps(sample)) < len(json.dumps(stored)) / 2


# --- inherited guarantees ---------------------------------------------------


def test_series_route_is_get_only(tmp_path: Path) -> None:
    """Belt-and-suspenders beside the all-routes read-only test, which covers this automatically."""
    client = _client(tmp_path)
    for verb in ("post", "put", "patch", "delete"):
        resp = getattr(client, verb)(f"/subscription-series?ipo_id={FULL}")
        assert resp.status_code == 405, f"{verb.upper()} must not be allowed"


def test_series_response_carries_retry_after_and_cors_when_limited(tmp_path: Path) -> None:
    """Bounded the moment it exists — it inherits the limiter, mirroring the /health test."""
    client = _client(tmp_path)
    for _ in range(_RATE_LIMIT_REQUESTS):
        client.get(f"/subscription-series?ipo_id={FULL}")
    refused = client.get(
        f"/subscription-series?ipo_id={FULL}", headers={"Origin": "https://ipoadvisor.in"}
    )
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1
    assert refused.headers["access-control-allow-origin"] == "*"
