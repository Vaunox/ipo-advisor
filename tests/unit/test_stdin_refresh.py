"""OP-2: the manual-refresh outcome classifier keeps the button-cases DISTINCT.

A manual refresh is a VM RE-PULL, not an NSE re-scrape: ``record_success`` sets ``last_success`` to
the VM's stamp, so an unchanged clock is CORRECT when the VM has nothing newer. That makes
``advanced`` alone ambiguous — Phase 2's "Refresh feels dead" diagnosis needs ``source`` +
``refreshed_at`` too, to split "VM had nothing newer (working)" from "VM returned newer but the chip
didn't re-read (display bug)" from "VM down, local scrape ran". This locks that the classifier
surfaces those fields and never flattens the cases. Pure logic; the stdin loop that logs it is a
runtime entrypoint, but the classification it emits is tested here.
"""

from __future__ import annotations

from datetime import datetime

from ipo.core.constants import IST
from ipo.data.ingest.state import IngestState
from ipo.service.runner import classify_refresh_outcome

_T0 = datetime(2026, 7, 20, 12, 30, tzinfo=IST)  # the VM's stamp before a manual refresh
_T1 = datetime(2026, 7, 20, 12, 45, tzinfo=IST)  # a newer stamp


def _state(
    *, success: datetime | None, attempt: datetime | None, ok: bool | None, source: str | None
) -> IngestState:
    return IngestState(
        last_success=success, last_attempt=attempt, last_attempt_ok=ok, source=source
    )


def test_vm_nothing_newer_reads_as_working_not_stuck() -> None:
    # The likely real case: a VM re-pull that returns the same refreshed_at. last_success (the VM's
    # stamp) does not move — CORRECT, not a bug. source=vm + refreshed_at prove it.
    before = _state(success=_T0, attempt=_T0, ok=True, source="vm")
    after = _state(success=_T0, attempt=_T0, ok=True, source="vm")
    out = classify_refresh_outcome(before, after)
    assert out["source"] == "vm"
    assert out["advanced"] is False
    assert out["attempted"] is False
    assert out["attempt_ok"] is True
    assert out["refreshed_at"] == _T0.isoformat()  # the VM's unchanged stamp, read off directly


def test_vm_returned_newer_data_advances() -> None:
    # The VM had newer data → last_success moves to it. If the chip still shows _T0, THAT is a
    # display bug — but the engine side (advanced=true, refreshed_at=_T1) is correct.
    before = _state(success=_T0, attempt=_T0, ok=True, source="vm")
    after = _state(success=_T1, attempt=_T1, ok=True, source="vm")
    out = classify_refresh_outcome(before, after)
    assert out["source"] == "vm"
    assert out["advanced"] is True
    assert out["refreshed_at"] == _T1.isoformat()
    assert out["refreshed_at_before"] == _T0.isoformat()


def test_local_scrape_when_vm_was_unreachable() -> None:
    # VM down → a real local NSE scrape ran; source flips to local and the clock advances.
    before = _state(success=_T0, attempt=_T0, ok=True, source="vm")
    after = _state(success=_T1, attempt=_T1, ok=True, source="local")
    out = classify_refresh_outcome(before, after)
    assert out["source"] == "local"
    assert out["advanced"] is True


def test_fetch_failure_is_distinct_from_a_working_no_op() -> None:
    # The pull attempted but FAILED (last_attempt moved, ok False), degrading silently — NOT a
    # working "nothing newer" no-op (where attempt_ok stays True).
    before = _state(success=_T0, attempt=_T0, ok=True, source="vm")
    after = _state(success=_T0, attempt=_T1, ok=False, source="vm")
    out = classify_refresh_outcome(before, after)
    assert out["advanced"] is False
    assert out["attempted"] is True
    assert out["attempt_ok"] is False


def test_the_cases_have_distinct_signatures() -> None:
    # The whole diagnostic value: (source, advanced, attempt_ok) must separate the outcomes so the
    # Phase-2 console reading is unambiguous — never collapsed to a flat changed/didn't-change.
    vm_noop = classify_refresh_outcome(
        _state(success=_T0, attempt=_T0, ok=True, source="vm"),
        _state(success=_T0, attempt=_T0, ok=True, source="vm"),
    )
    vm_newer = classify_refresh_outcome(
        _state(success=_T0, attempt=_T0, ok=True, source="vm"),
        _state(success=_T1, attempt=_T1, ok=True, source="vm"),
    )
    local = classify_refresh_outcome(
        _state(success=_T0, attempt=_T0, ok=True, source="vm"),
        _state(success=_T1, attempt=_T1, ok=True, source="local"),
    )
    failed = classify_refresh_outcome(
        _state(success=_T0, attempt=_T0, ok=True, source="vm"),
        _state(success=_T0, attempt=_T1, ok=False, source="vm"),
    )
    signatures = {
        (o["source"], o["advanced"], o["attempt_ok"]) for o in (vm_noop, vm_newer, local, failed)
    }
    assert len(signatures) == 4  # all four outcomes genuinely distinguishable
