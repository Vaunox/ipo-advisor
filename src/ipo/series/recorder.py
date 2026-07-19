"""The DP-1 recorder (v3-DP) — banks the live demand book as the ingest cycle sees it.

ONE FETCH, TWO WRITES. The VM already asks NSE for each open IPO's subscription every 30 minutes in
order to score it (``ipo-ingest.service`` -> ``run_live_ingest.py`` -> ``refresh_from_nse``). Path A
overwrites current state as it always has; Path B — this — appends the same reading to an
append-only series. Zero extra NSE calls, zero extra timers, and the recorder's cadence *is* the
ingest cadence, so there is no keepalive collision to tune.

CAPTURE AND WRITE HAPPEN AT DIFFERENT POINTS, DELIBERATELY. The blueprint says to append "after the
current-state upsert", and the *write* does exactly that. But the data cannot be CAPTURED there:
by the time ``repo.upsert_many`` returns, the ``NseSubscription``, NSE's ``updateTime`` and the raw
response have all left scope, leaving only ``list[IPORecord]`` — a lossy projection that cannot
distinguish a real fetch from a replayed one. So capture happens at the fork, inside the fetch's
success branch; the flush still happens after current state is safely committed. Current state
keeps absolute priority: the series never delays, blocks, or endangers the scoring input.

THE FABRICATED-ROW HAZARD, and why capture sits in the ``try`` and not after it. On a fetch
failure ``_degrade_subscription`` SYNTHESISES an ``NseSubscription`` from the prior record and
stamps it with the prior ``captured_at``. Banking that would write a row that is, after the fact,
indistinguishable from a genuine reading — a fabricated sample in a store whose entire value is
being trustworthy months from now. Because ``observe`` is only ever called from the success branch,
a degraded reading is *structurally incapable* of reaching the series. A failed fetch banks
nothing: an honest gap, visible on the health row.

B1 WALL: see ``ipo/series/__init__.py``. This collects. It does not display and does not score.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime

from ipo.series.models import SCHEMA_VERSION, CategoryReading, SubscriptionSample

_log = logging.getLogger(__name__)

# NSE stamps its own "Updated as on 24-Nov-2023 19:00:00". Kept verbatim on the sample; this parse
# is a convenience column only, and a miss is a None, never an error.
_NSE_STAMP_PREFIX = "updated as on"
_NSE_STAMP_FORMAT = "%d-%b-%Y %H:%M:%S"


def parse_nse_update_time(value: str | None) -> datetime | None:
    """Best-effort parse of NSE's own stamp. Returns ``None`` rather than raising on drift."""
    text = (value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith(_NSE_STAMP_PREFIX):
        text = text[len(_NSE_STAMP_PREFIX) :].strip()
    try:
        return datetime.strptime(text.title(), _NSE_STAMP_FORMAT)
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def in_recording_window(open_date: date, close_date: date, today: date) -> bool:
    """Record from the day the book opens through the day it closes, inclusive.

    The whole live-book window (typically three days), not just the final day: before open there is
    no book, after close the number is settled, and the multi-day shape is exactly what DP-3's
    curve and DP-4's fill-curve analysis both need.
    """
    return open_date <= today <= close_date


def build_sample(
    *,
    ipo_id: str,
    symbol: str,
    captured_at: datetime,
    raw_content: bytes | str,
) -> SubscriptionSample:
    """Turn one genuine NSE subscription response into a bankable sample.

    Every field NSE returns is extracted into typed columns AND the complete response is retained
    in a directly-loadable form — belt and suspenders, because this store exists to answer
    questions nobody has asked yet and a field discarded now cannot be recovered later.
    """
    payload = raw_content.encode("utf-8") if isinstance(raw_content, str) else raw_content
    digest = hashlib.sha256(payload).hexdigest()
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("nse subscription response is not a JSON object")

    rows = document.get("dataList")
    rows = rows if isinstance(rows, list) else []
    categories: list[CategoryReading] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("category", "")).strip()
        if not label or label.lower() == "category":
            continue  # row 0 is a header row whose values ARE the column labels
        categories.append(
            CategoryReading(
                category=label,
                no_of_shares_offered=_as_float(row.get("noOfShareOffered")),
                no_of_shares_bid=_as_float(row.get("noOfSharesBid")),
                no_of_total_meant=_as_float(row.get("noOfTotalMeant")),
                sr_no=_as_int(row.get("srNo")),
            )
        )

    def multiple_for(predicate: object) -> float | None:
        for reading in categories:
            if predicate(reading.category):  # type: ignore[operator]
                return reading.no_of_total_meant
        return None

    stamp = document.get("updateTime")
    stamp_text = str(stamp).strip() if isinstance(stamp, str) else None

    return SubscriptionSample(
        schema_version=SCHEMA_VERSION,
        ipo_id=ipo_id,
        symbol=symbol,
        captured_at=captured_at,
        source_update_time=stamp_text,
        source_update_time_parsed=parse_nse_update_time(stamp_text),
        # Same predicates the live scoring path uses, so the banked headline multiples and the
        # scored ones can never silently diverge in meaning.
        qib_sub=multiple_for(lambda c: "Qualified Institutional Buyers" in c),
        nii_sub=multiple_for(lambda c: c == "Non Institutional Investors"),
        snii_sub=multiple_for(lambda c: "Two Lakh Rupees upto Ten Lakh" in c),
        bnii_sub=multiple_for(lambda c: "more than Ten Lakh Rupees" in c),
        retail_sub=multiple_for(lambda c: "Retail Individual Investors" in c),
        total_sub=multiple_for(lambda c: c == "Total"),
        categories=tuple(categories),
        raw_response=document,
        raw_response_hash=digest,
    )


class SeriesSink:
    """Accumulates samples during a cycle; the caller flushes AFTER the current-state upsert.

    Deliberately dumb and in-memory: it holds no file handle and performs no I/O until ``flush``,
    so nothing about the recorder can slow down or fail the scoring write it rides along with.
    """

    def __init__(self) -> None:
        """Start an empty, in-memory accumulation for one ingest cycle."""
        self._samples: list[SubscriptionSample] = []
        self._in_window = 0

    @property
    def in_window(self) -> int:
        """How many IPOs were inside their recording window this cycle (0 = correctly idle)."""
        return self._in_window

    @property
    def samples(self) -> list[SubscriptionSample]:
        """Everything accepted this cycle, in observation order."""
        return list(self._samples)

    def observe(
        self,
        *,
        ipo_id: str,
        symbol: str,
        captured_at: datetime,
        raw_content: bytes | str,
        open_date: date,
        close_date: date,
        today: date,
    ) -> bool:
        """Offer one GENUINE reading to the series. Returns whether it was accepted.

        MUST only ever be called from the fetch's success branch — see the module docstring on the
        fabricated-row hazard. Never raises: a malformed response is logged and dropped, because a
        recorder problem must not become an ingest problem.
        """
        if not in_recording_window(open_date, close_date, today):
            return False
        self._in_window += 1
        try:
            self._samples.append(
                build_sample(
                    ipo_id=ipo_id,
                    symbol=symbol,
                    captured_at=captured_at,
                    raw_content=raw_content,
                )
            )
        except (ValueError, TypeError) as exc:
            _log.warning("series_sample_build_failed", extra={"ipo_id": ipo_id, "error": str(exc)})
            return False
        return True
