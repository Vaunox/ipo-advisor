"""Typed rows for the forward subscription series (v3-DP DP-1).

Superset of the retired v2-A1 ``DaywiseSubscriptionRow`` (11 columns, commit ``40e9230``), which
this deliberately reuses the shape of — including ``source_update_time``, whose value the code
review identified as the authoritative per-IPO provenance stamp (*when that reading was actually
true*, as opposed to when we happened to ask).

Two shape decisions worth their reasoning, both taken from the live NSE payload rather than from
the blueprint's prose:

* **The category set VARIES per IPO.** The two committed fixtures carry 25 and 22 rows — an IPO
  with a shareholder or employee reservation reports categories another IPO simply does not have.
  A fixed column-per-category schema would therefore drift and break. Hence ``categories`` is a
  variable-length list of typed readings, not a wide row.
* **``no_of_shares_offered`` / ``no_of_shares_bid`` are retained for every category.** They are the
  raw numerator and denominator behind every multiple and NSE returns them today; the live path
  discards them. DP-4's fill-curve analysis wants them, and they cannot be recovered later.

``schema_version`` is present from row one on purpose: this store runs unattended for months and
will outlive its own schema, and stamping the version now is far cheaper than inferring it later
from row shape.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Bump when the sample shape changes in a way a reader must branch on. Never reuse a number.
SCHEMA_VERSION = 1


class _Frozen(BaseModel):
    """Base for immutable, strictly-validated value objects (mirrors ``core.types._Frozen``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CategoryReading(_Frozen):
    """One row of NSE's demand book, verbatim in structure, typed in content.

    ``category`` is NSE's own label, unnormalised — normalising here would quietly lose the
    distinction between categories that differ only in wording, and a future reader can always
    normalise, whereas it can never un-normalise.
    """

    category: str
    no_of_shares_offered: float | None = None
    no_of_shares_bid: float | None = None
    no_of_total_meant: float | None = None  # the oversubscription multiple NSE reports
    sr_no: int | None = None


class SubscriptionSample(_Frozen):
    """One timestamped observation of an IPO's live demand book.

    APPENDED ONLY on a genuine fetch. A degraded/preserved reading (see ``_degrade_subscription``
    in ``data/ingest/live.py``, which synthesises a replay of the PRIOR record stamped with the
    prior ``captured_at``) must never reach this type — that would bank a fabricated row that is
    indistinguishable from a real one after the fact. An honest gap is the correct output of a
    failed fetch.
    """

    schema_version: int = SCHEMA_VERSION

    ipo_id: str
    symbol: str

    # OUR stamp: when we asked. Point-in-time anchor and half the natural key.
    captured_at: datetime
    # NSE's OWN stamp: when the reading was true. Retained VERBATIM and unparsed, exactly as the
    # retired recorder did, so a format tweak upstream can never silently drop it.
    source_update_time: str | None = None
    # Best-effort parse of the above, for querying. Never a substitute for the verbatim string.
    source_update_time_parsed: datetime | None = None

    # Headline multiples — stable across every IPO, so these stay flat typed columns.
    qib_sub: float | None = Field(default=None, ge=0)
    nii_sub: float | None = Field(default=None, ge=0)
    snii_sub: float | None = Field(default=None, ge=0)  # sNII: bid > ₹2L up to ₹10L
    bnii_sub: float | None = Field(default=None, ge=0)  # bNII: bid > ₹10L
    retail_sub: float | None = Field(default=None, ge=0)
    total_sub: float | None = Field(default=None, ge=0)

    # The complete demand book, every row NSE returned, every field typed.
    categories: tuple[CategoryReading, ...] = ()
    # The complete response, retained in a DIRECTLY-LOADABLE form (a mapping, never an escaped
    # JSON string a future reader must re-parse). Belt and suspenders alongside `categories`.
    raw_response: dict[str, object] = Field(default_factory=dict)
    # Drift tripwire over the raw bytes.
    raw_response_hash: str

    @property
    def key(self) -> tuple[str, str]:
        """Natural key — an observation at a given instant is immutable and never rewritten."""
        return (self.ipo_id, self.captured_at.isoformat())
