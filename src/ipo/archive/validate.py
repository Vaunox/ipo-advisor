"""Validate a transitions drop before it is allowed into the durable archive (v3 V3-2).

The archive's integrity must not depend on the app's drop being well-formed — a malformed or
truncated rendezvous file is REJECTED, never merged (the "don't trust a 200" discipline from the
V3-1 VM client, applied to the pull side). Only content that fully parses AND validates against
the shipped ``VerdictTransition`` model is admitted (so the archive can't drift from the app).

A leading UTF-8 BOM (a Windows tool may re-save one) is benign and stripped at the READ boundary
(``utf-8-sig`` in store.py / pull.py), so this validator only ever sees clean text.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from ipo.service.transitions import VerdictTransition


class ArchiveRejected(Exception):
    """The drop is malformed / truncated — reject it whole; the archive is left untouched."""


def load_validated(text: str) -> list[VerdictTransition]:
    """Parse + validate a transitions drop; raise :class:`ArchiveRejected` on anything not valid.

    Truncation manifests as a JSON parse error (a cut-off array); a bad row fails model validation.
    A *valid-but-shorter* drop is NOT an error here — it is admitted, because the append-only union
    merge makes an incomplete drop harmless (it can only add, never delete). So this guards
    CORRUPTION; incompleteness is handled structurally by the union merge (see merge.py).
    """
    try:
        raw = json.loads(text)
    except ValueError as exc:  # truncated / not JSON (JSONDecodeError is a ValueError)
        raise ArchiveRejected(f"drop is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ArchiveRejected(f"drop must be a JSON array, got {type(raw).__name__}")
    try:
        return [VerdictTransition.model_validate(row) for row in raw]
    except ValidationError as exc:
        raise ArchiveRejected(f"drop has a malformed transition: {exc}") from exc
