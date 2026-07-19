"""Progress-log integrity guard (v3 + v3-DP) — a silent doc-merge drop must fail LOUDLY.

`docs/v3/V3_PROGRESS.md`, `docs/v3/V3-DP_PROGRESS.md` and their blueprints are load-bearing: a
fresh session reads them to know where the project stands. But a 3-way merge can silently delete or
mangle a table row — during the finding-④ rebase it dropped the V3-8 row AND mangled the V3-11 row,
caught only by hand-checking the set. Gates protect code, not docs; this closes the gap by asserting
the row set inside the ordinary pytest gate, so the next silent drop fails a test by name instead of
vanishing unnoticed.

Each guarded log is a `_Log` entry in `_LOGS`, and every test runs against all of them. The two logs
deliberately do NOT share their rules:

* **Separate ledgers.** A merged ledger would let a v3-DP id satisfy a missing v3 row.
* **Separate row patterns.** v3's Date cell must be a real ISO date; v3-DP additionally accepts the
  "—" placeholder a not-started item carries. That relaxation is scoped to v3-DP ON PURPOSE — see
  `_ISO_ROW` for why applying it globally would WEAKEN the v3 guard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_V3 = _ROOT / "docs" / "v3"

# A data row starts with "| <ISO date> |". The header ("| Date |") and separator ("|---|") do not.
#
# This stays ISO-ONLY for v3, and that strictness is load-bearing: a row whose Date cell gets
# mangled by a merge falls out of the row set entirely, and if it is a _SHIPPED row the ledger check
# below then fails by name. Widening this pattern to also accept "—" (as v3-DP needs) would let such
# a mangled row back in and let the ledger check pass — a real weakening. Hence two patterns.
_ISO_ROW = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|")
# v3-DP only: a not-started item legitimately has no date yet and carries an em-dash placeholder.
_ISO_OR_PENDING_ROW = re.compile(r"^\|\s*(?:\d{4}-\d{2}-\d{2}|—)\s*\|")

# Split on UNescaped pipes only — Notes cells contain escaped "\|" (e.g. "MAX \|Δprob\|").
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
# DP-N included so v3-DP rows are actually CHECKED. Without it every DP row fails `fullmatch` and is
# skipped by the blueprint cross-check — the guard would go green while verifying nothing.
# The optional a/b suffix landed when DP-3 was built as two items (DP-3a engine data path,
# DP-3b chart). Without it "DP-3a" fails `fullmatch`, so the row is skipped by the blueprint
# cross-check and the guard goes green while verifying nothing — the same vacuous-pass mode
# that made DP-N need adding in the first place.
_ITEM_ID = re.compile(r"(V3-\d+|DP-\d+[ab]?|BUG \d+)")

# The ledger of items whose progress-log row must NEVER silently vanish. When an item ships, add its
# ID here — that deliberate, reviewed line puts the row under guard. New rows may be added freely;
# only DROPPING (or doubling) a listed row is the failure this catches.
_SHIPPED_V3 = frozenset(
    # V3-7 and V3-10 are dropped, not shipped — but their rows carry the "do not re-propose"
    # reasoning, so they must persist just as much as a shipped item's row.
    {
        "BUG 1",
        "BUG 2",
        "BUG 3",
        "V3-1",
        "V3-2",
        "V3-3",
        "V3-4",
        "V3-5",
        "V3-6",
        "V3-7",
        "V3-8",
        "V3-10",
        "V3-11",
        "V3-16",
        # Not blueprint items (so `test_progress_rows_reference_real_blueprint_items` skips them by
        # design), but shipped work whose row must not vanish: Finding-④ is emergent, BUG-4 was
        # found after the plan was written and is tracked in docs/PROJECT_LOG.md §6.
        "Finding-④",
        "BUG-4",
    }
)

# Each DP id joins this ledger AS IT LANDS, in the same commit that merges it — the guard was armed
# ahead of the first merge precisely so this step could never become a follow-up, which is how V3-16
# went five days without its `merged <sha>` marker.
#
# KNOWN GAP (guard-hardening candidate, not yet implemented): this catches a DROPPED or ORPHANED
# row, but NOT a stale-STATUS row — a ledger item whose row still reads "NOT STARTED"/pending after
# it shipped. That is precisely the V3-16 failure mode and it remains uncaught. "Is this status
# true?" is not automatable in general, but "a shipped-ledger item must not read NOT STARTED" is.
_SHIPPED_DP: frozenset[str] = frozenset({"DP-1", "DP-2", "DP-3a", "DP-3b"})


@dataclass(frozen=True)
class _Log:
    """One guarded progress log, with the rules that apply to IT and not to its siblings."""

    name: str
    progress: Path
    blueprint: Path
    data_row: re.Pattern[str]
    shipped: frozenset[str]


_LOGS = (
    _Log("v3", _V3 / "V3_PROGRESS.md", _V3 / "MASTER_BLUEPRINT_v3.md", _ISO_ROW, _SHIPPED_V3),
    _Log(
        "v3-DP",
        _V3 / "V3-DP_PROGRESS.md",
        _V3 / "MASTER_BLUEPRINT_v3-DP.md",
        _ISO_OR_PENDING_ROW,
        _SHIPPED_DP,
    ),
)
_LOG_IDS = [log.name for log in _LOGS]


def _rows(log: _Log) -> list[list[str]]:
    """Every data row of the progress table as its list of 5 cell strings."""
    out: list[list[str]] = []
    for line in log.progress.read_text(encoding="utf-8").splitlines():
        if log.data_row.match(line):
            cells = [c.strip() for c in _UNESCAPED_PIPE.split(line.strip())][1:-1]
            out.append(cells)
    return out


def _item(cell: str) -> str:
    """The item ID — the text before the em dash (e.g. 'V3-8', 'BUG 1', 'DP-1', 'Finding-④').

    Markdown emphasis is stripped: v3-DP bolds every item cell (``**DP-1 — …**``), which would
    otherwise yield ``'**DP-1'`` — matching no ID pattern, so every DP row would be silently skipped
    by the blueprint cross-check.
    """
    return cell.split("—")[0].strip().strip("*").strip()


@pytest.mark.parametrize("log", _LOGS, ids=_LOG_IDS)
def test_progress_rows_are_well_formed(log: _Log) -> None:
    rows = _rows(log)
    assert rows, f"{log.progress.name} has no data rows — the table was emptied?"
    for cells in rows:
        n = len(cells)
        assert n == 5, f"malformed progress row (expected 5 cells, got {n}): {cells[:2]}"
        assert cells[3], f"progress row for {_item(cells[1])!r} has an empty Outcome/Status cell"


@pytest.mark.parametrize("log", _LOGS, ids=_LOG_IDS)
def test_no_shipped_row_silently_disappeared(log: _Log) -> None:
    ids = [_item(c[1]) for c in _rows(log)]
    missing = log.shipped - set(ids)
    assert not missing, (
        f"{log.progress.name} is missing a row for {sorted(missing)} — a doc merge may have "
        "silently dropped it (cf. the V3-8 drop during the finding-④ rebase). Restore the row."
    )
    dupes = sorted(i for i in log.shipped if ids.count(i) > 1)
    assert not dupes, f"duplicate progress rows for {dupes} — a merge may have doubled a row"


@pytest.mark.parametrize("log", _LOGS, ids=_LOG_IDS)
def test_progress_rows_reference_real_blueprint_items(log: _Log) -> None:
    """Every V3-N / DP-N / BUG-N row maps to an item that exists in the blueprint (no orphans)."""
    blueprint = log.blueprint.read_text(encoding="utf-8")
    known = set(_ITEM_ID.findall(blueprint))
    for cells in _rows(log):
        item = _item(cells[1])
        if _ITEM_ID.fullmatch(item):  # skip non-blueprint items like 'Finding-④'
            assert item in known, f"progress row {item!r} is not a real blueprint item (mangled?)"
