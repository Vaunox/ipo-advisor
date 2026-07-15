"""New-IPO onset context trigger (v3, context-off-scoring-path): close the display gap where a
freshly-detected IPO shows empty context fields until the next 3x/day batch.

The headline proofs: a genuinely-new ``ipo_id`` fires exactly one context pull; a previously-seen id
fires none on the next cycle; a simulated VM restart (fresh process, pre-populated store) does not
re-fire for IPOs the store already has. Plus the one real correctness risk the operator flagged: a
single-symbol merge must leave every OTHER cached IPO's context — and the store's ``refreshed_at`` —
untouched.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType

from ipo.data.sources.nse import NseClient, NseCurrentIssue, NseSubscription

_ISSUE_A = NseCurrentIssue(
    symbol="ALPHACO",
    company="Alpha Co Ltd",
    segment="mainboard",
    price_band_low=100.0,
    price_band_high=110.0,
    open_date=date(2026, 7, 1),
    close_date=date(2026, 7, 3),
)
_ISSUE_B = NseCurrentIssue(
    symbol="BETACO",
    company="Beta Co Ltd",
    segment="mainboard",
    price_band_low=200.0,
    price_band_high=220.0,
    open_date=date(2026, 7, 2),
    close_date=date(2026, 7, 4),
)
_SUB = NseSubscription(qib=5.0, nii=3.0, retail=2.0, total=4.0)


def _load_script(name: str) -> ModuleType:
    """Load scripts/<name>.py by path (scripts is not an importable package)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CannedNse(NseClient):
    """A canned NSE source (no network) serving a fixed set of current issues."""

    def __init__(self, issues: list[NseCurrentIssue]) -> None:
        self._issues = issues

    def current_issues(self, *, force: bool = True) -> list[NseCurrentIssue]:
        return list(self._issues)

    def upcoming_issues(self, *, force: bool = True) -> list[NseCurrentIssue]:
        return []

    def subscription(self, symbol: str, *, force: bool = False) -> NseSubscription:
        return _SUB

    def past_issues(self, *, force: bool = False) -> list:  # type: ignore[type-arg]
        return []

    def listing_prices(self, symbol: str, listing_day: date) -> tuple[float, float] | None:
        return None


# --- new_ids diffing: the seen-state derived from the records store itself ---------------------


def test_a_genuinely_new_ipo_is_reported_as_new(tmp_path: Path) -> None:
    script = _load_script("run_live_ingest")
    count, new_ids = script.live_ingest_new_ids(_CannedNse([_ISSUE_A]), tmp_path)
    assert count == 1
    assert new_ids == {"alphaco"}


def test_a_seen_ipo_is_not_new_on_the_next_cycle(tmp_path: Path) -> None:
    script = _load_script("run_live_ingest")
    script.live_ingest_new_ids(_CannedNse([_ISSUE_A]), tmp_path)  # cycle 1: alphaco is new
    _, new_ids = script.live_ingest_new_ids(_CannedNse([_ISSUE_A]), tmp_path)  # cycle 2: same issue
    assert new_ids == set()  # already in the store — not new again


def test_a_second_ipo_alongside_a_seen_one_is_the_only_one_reported_new(tmp_path: Path) -> None:
    script = _load_script("run_live_ingest")
    script.live_ingest_new_ids(_CannedNse([_ISSUE_A]), tmp_path)
    _, new_ids = script.live_ingest_new_ids(_CannedNse([_ISSUE_A, _ISSUE_B]), tmp_path)
    assert new_ids == {"betaco"}


def test_restart_does_not_re_fire_for_already_open_ipos(tmp_path: Path) -> None:
    """A fresh process (simulating a VM restart) must not treat currently-open IPOs as new — the
    parquet store IS the durable seen-state, with no separate seen-set file to lose on restart."""
    script = _load_script("run_live_ingest")
    script.live_ingest_new_ids(_CannedNse([_ISSUE_A, _ISSUE_B]), tmp_path)  # pre-restart: both seen
    assert (tmp_path / "ipo_records.parquet").is_file()  # durable on disk, survives the "restart"

    # A brand-new process/repo instance reads the same on-disk store, no in-memory state carries.
    _, new_ids = script.live_ingest_new_ids(_CannedNse([_ISSUE_A, _ISSUE_B]), tmp_path)
    assert new_ids == set()  # both already-open IPOs: zero re-fires


# --- firing the pull: dark-ship, per-symbol isolation, exactly-once ------------------------------


def test_fires_exactly_one_pull_per_new_id(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = _load_script("run_live_ingest")
    monkeypatch.setenv("UPSTOX_TOKEN", "tok")
    calls: list[tuple[str, Path, str]] = []

    def fake_refresh(token: str, data_dir: Path, symbol: str) -> bool:
        calls.append((token, data_dir, symbol))
        return True

    fired = script.fire_new_ipo_context_pulls(tmp_path, {"alphaco"}, refresh_fn=fake_refresh)
    assert fired == 1
    assert calls == [("tok", tmp_path, "ALPHACO")]


def test_no_new_ids_fires_nothing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = _load_script("run_live_ingest")
    monkeypatch.setenv("UPSTOX_TOKEN", "tok")
    calls: list[object] = []

    def record(token: str, data_dir: Path, symbol: str) -> bool:
        calls.append((token, data_dir, symbol))
        return True

    script.fire_new_ipo_context_pulls(tmp_path, set(), refresh_fn=record)
    assert calls == []


def test_darkships_without_a_token(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = _load_script("run_live_ingest")
    monkeypatch.delenv("UPSTOX_TOKEN", raising=False)
    calls: list[object] = []

    def record(token: str, data_dir: Path, symbol: str) -> bool:
        calls.append((token, data_dir, symbol))
        return True

    fired = script.fire_new_ipo_context_pulls(tmp_path, {"alphaco"}, refresh_fn=record)
    assert fired == 0
    assert calls == []  # no fetch attempted at all — not even a call made


def test_one_symbols_failure_does_not_abort_the_others(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    script = _load_script("run_live_ingest")
    monkeypatch.setenv("UPSTOX_TOKEN", "tok")

    def flaky(token: str, data_dir: Path, symbol: str) -> bool:
        if symbol == "ALPHACO":
            raise RuntimeError("upstox blew up")
        return True

    fired = script.fire_new_ipo_context_pulls(tmp_path, {"alphaco", "betaco"}, refresh_fn=flaky)
    assert fired == 1  # betaco still fired despite alphaco's failure


# --- the merge-preservation correctness risk -----------------------------------------------------


def test_merge_leaves_other_ipos_and_refreshed_at_untouched(tmp_path: Path) -> None:
    refresh_context = _load_script("refresh_context")
    data_dir = tmp_path
    ctx_dir = data_dir / "context"
    ctx_dir.mkdir()
    existing = {
        "refreshed_at": "2026-07-15T18:15:00+05:30",
        "ipos": {"BETACO": {"registrar": {"short": "KFIN"}}},
    }
    (ctx_dir / "ipo_context.json").write_text(json.dumps(existing), encoding="utf-8")

    written = refresh_context.merge_context(data_dir, "alphaco", {"rhp_url": "https://example/rhp"})

    assert written is True
    payload = json.loads((ctx_dir / "ipo_context.json").read_text(encoding="utf-8"))
    assert payload["refreshed_at"] == "2026-07-15T18:15:00+05:30"  # unchanged, see merge_context
    assert payload["ipos"]["BETACO"] == {"registrar": {"short": "KFIN"}}  # untouched
    assert payload["ipos"]["ALPHACO"] == {"rhp_url": "https://example/rhp"}  # new, upper-cased


def test_merge_with_an_empty_entry_writes_nothing(tmp_path: Path) -> None:
    refresh_context = _load_script("refresh_context")
    written = refresh_context.merge_context(tmp_path, "alphaco", {})
    assert written is False
    assert not (tmp_path / "context" / "ipo_context.json").is_file()


def test_merge_creates_the_cache_when_none_exists_yet(tmp_path: Path) -> None:
    refresh_context = _load_script("refresh_context")
    written = refresh_context.merge_context(tmp_path, "alphaco", {"lot_size": 50})
    assert written is True
    payload = json.loads((tmp_path / "context" / "ipo_context.json").read_text(encoding="utf-8"))
    assert payload["refreshed_at"] is None
    assert payload["ipos"] == {"ALPHACO": {"lot_size": 50}}


def test_refresh_one_resolves_the_symbols_id_then_fetches_its_context(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    refresh_context = _load_script("refresh_context")
    monkeypatch.setattr(refresh_context, "_list_ids", lambda token: {"ALPHACO": 4242})
    monkeypatch.setattr(
        refresh_context,
        "_context",
        lambda token, ipo_id: {"lot_size": 50} if ipo_id == 4242 else {},
    )
    assert refresh_context.refresh_one("tok", "alphaco") == {"lot_size": 50}


def test_refresh_one_returns_empty_when_the_symbol_is_unresolvable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    refresh_context = _load_script("refresh_context")
    monkeypatch.setattr(refresh_context, "_list_ids", lambda token: {})
    assert refresh_context.refresh_one("tok", "ghostco") == {}
