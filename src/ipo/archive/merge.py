"""Append-only union merge for the durable transitions archive (v3 V3-2).

A verdict transition is immutable: the app records "at ``asof``, IPO X changed to verdict V" once
and never rewrites it. So two transitions are "the same" iff every field matches, and merging is a
**set-union keyed on the whole record**. That makes the pull provably safe under every timing:

* **idempotent** — re-merging an already-merged drop changes nothing (a double pull is a no-op);
* **order-independent** — ``merge(a, b)`` and ``merge(b, a)`` give the same archive (an
  out-of-order or missed-then-caught-up pull converges to the same state);
* **loss-proof** — nothing is ever deleted, so losing the local copy loses nothing durable, and a
  partial drop can only add rows, never remove archived ones.
"""

from __future__ import annotations

from ipo.service.transitions import VerdictTransition


def merge_transitions(
    existing: list[VerdictTransition], incoming: list[VerdictTransition]
) -> list[VerdictTransition]:
    """Union ``existing`` + ``incoming`` deduped by full-record identity, in a deterministic order.

    Identity is the transition's canonical JSON (every field), so only byte-identical transitions
    collapse and any genuine difference is preserved. Output is sorted by (``asof``, ``ipo_id``,
    identity) so the archive file is stable across pulls — a clean diff, no churn.
    """
    by_identity: dict[str, VerdictTransition] = {}
    for transition in (*existing, *incoming):
        by_identity.setdefault(transition.model_dump_json(), transition)
    return sorted(
        by_identity.values(),
        key=lambda t: (t.asof, t.ipo_id, t.model_dump_json()),
    )
