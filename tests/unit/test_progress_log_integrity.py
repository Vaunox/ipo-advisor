"""Progress-log integrity guard (v3) — a silent doc-merge drop must fail LOUDLY.

`docs/v3/V3_PROGRESS.md` and the blueprint are load-bearing: a fresh session reads them to know
where the project stands. But a 3-way merge can silently delete or mangle a table row — during the
finding-④ rebase it dropped the V3-8 row AND mangled the V3-11 row, caught only by hand-checking the
set. Gates protect code, not docs; this closes the gap by asserting the row set inside the ordinary
pytest gate, so the next silent drop fails a test by name instead of vanishing unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PROGRESS = _ROOT / "docs" / "v3" / "V3_PROGRESS.md"
_BLUEPRINT = _ROOT / "docs" / "v3" / "MASTER_BLUEPRINT_v3.md"

# The ledger of items whose progress-log row must NEVER silently vanish. When an item ships, add its
# ID here — that deliberate, reviewed line puts the row under guard. New rows may be added freely;
# only DROPPING (or doubling) a listed row is the failure this catches.
_SHIPPED = frozenset(
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
        # design), but shipped work whose row must not vanish: Finding-④ is emergent, BUG-4 was found
        # after the plan was written and is tracked in docs/PROJECT_LOG.md §6.
        "Finding-④",
        "BUG-4",
    }
)

# A data row starts with "| <ISO date> |". The header ("| Date |") and separator ("|---|") do not.
_DATA_ROW = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|")
# Split on UNescaped pipes only — Notes cells contain escaped "\|" (e.g. "MAX \|Δprob\|").
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_ITEM_ID = re.compile(r"(V3-\d+|BUG \d+)")


def _rows() -> list[list[str]]:
    """Every data row of the progress table as its list of 5 cell strings."""
    out: list[list[str]] = []
    for line in _PROGRESS.read_text(encoding="utf-8").splitlines():
        if _DATA_ROW.match(line):
            cells = [c.strip() for c in _UNESCAPED_PIPE.split(line.strip())][1:-1]
            out.append(cells)
    return out


def _item(cell: str) -> str:
    """The item ID — the text before the em dash (e.g. 'V3-8', 'BUG 1', 'Finding-④')."""
    return cell.split("—")[0].strip()


def test_progress_rows_are_well_formed() -> None:
    rows = _rows()
    assert rows, "V3_PROGRESS.md has no data rows — the table was emptied?"
    for cells in rows:
        n = len(cells)
        assert n == 5, f"malformed progress row (expected 5 cells, got {n}): {cells[:2]}"
        assert cells[3], f"progress row for {_item(cells[1])!r} has an empty Outcome cell"


def test_no_shipped_row_silently_disappeared() -> None:
    ids = [_item(c[1]) for c in _rows()]
    missing = _SHIPPED - set(ids)
    assert not missing, (
        f"V3_PROGRESS.md is missing a row for {sorted(missing)} — a doc merge may have silently "
        "dropped it (cf. the V3-8 drop during the finding-④ rebase). Restore the row."
    )
    dupes = sorted(i for i in _SHIPPED if ids.count(i) > 1)
    assert not dupes, f"duplicate progress rows for {dupes} — a merge may have doubled a row"


def test_progress_rows_reference_real_blueprint_items() -> None:
    """Every V3-N / BUG-N row maps to an item that actually exists in the blueprint (no orphans)."""
    blueprint = _BLUEPRINT.read_text(encoding="utf-8")
    known = set(_ITEM_ID.findall(blueprint))
    for cells in _rows():
        item = _item(cells[1])
        if _ITEM_ID.fullmatch(item):  # skip non-blueprint items like 'Finding-④'
            assert item in known, f"progress row {item!r} is not a real blueprint item (mangled?)"
