"""NSE official source adapter (Deep Dive #1 — the authoritative exchange source).

NSE is the authoritative source the blueprint requires for the label and
subscription (an aggregator must never be both source and check). Its dynamic JSON
endpoints sit behind a browser-style cookie handshake (visit the homepage to obtain
cookies, then call the API with a ``Referer``) — the same browser-mimic that makes
the bhavcopy archive downloadable. Access is polite (rate-limited, cached, honest
UA), consistent with the operator's existing NSE usage.

What this adapter yields, all official/exact:
* the IPO master list (symbol, dates, price band, mainboard vs SME) — ``public-past-issues``;
* final QIB/NII/retail subscription — ``ipo-active-category`` (works for past issues);
* listing-day open/close (the label) — the daily bhavcopy archive.

Parsing is pure and schema-validated (fail loud on drift); fetching is isolated so
the parsers are tested against captured fixtures without network.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ipo.core.calendar import now_ist
from ipo.core.constants import SEGMENT_MAINBOARD, SEGMENT_SME
from ipo.core.types import RawResponse
from ipo.data.sources.base import PoliteClient, RawCache, SourceError, compute_hash

NSE_BASE = "https://www.nseindia.com"
NSE_HOMEPAGE = f"{NSE_BASE}/market-data/all-upcoming-issues-ipo"
PAST_ISSUES_URL = f"{NSE_BASE}/api/public-past-issues?index=equities"
CURRENT_ISSUES_URL = f"{NSE_BASE}/api/ipo-current-issue"
SUBSCRIPTION_URL = f"{NSE_BASE}/api/ipo-active-category"
BHAVCOPY_OLD = "https://archives.nseindia.com/content/historical/EQUITIES/{y}/{mon}/cm{d:02d}{mon}{y}bhav.csv.zip"
BHAVCOPY_UDIFF = (
    "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
)

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

# NSE replaced the legacy bhavcopy with the UDiFF format in mid-2024.
_BHAVCOPY_CUTOVER = date(2024, 7, 8)


@dataclass(frozen=True)
class NsePastIssue:
    """One row of the NSE past-issues master list (mainboard flag derived from series)."""

    symbol: str
    company: str
    segment: str  # "mainboard" | "sme"
    price_band_low: float | None
    price_band_high: float | None
    open_date: date | None
    close_date: date | None
    listing_date: date | None


@dataclass(frozen=True)
class NseCurrentIssue:
    """One live/active issue from ``ipo-current-issue`` (open or just-closed, pre-listing)."""

    symbol: str
    company: str
    segment: str  # "mainboard" | "sme"
    price_band_low: float | None
    price_band_high: float | None
    open_date: date | None
    close_date: date | None


@dataclass(frozen=True)
class NseSubscription:
    """Final/live oversubscription multiples (closing or in-progress) from NSE bid-details."""

    qib: float | None
    nii: float | None
    retail: float | None
    total: float | None
    nii_small: float | None = None  # sNII: bid > ₹2L up to ₹10L
    nii_big: float | None = None  # bNII: bid > ₹10L


# --- pure parsing helpers ---------------------------------------------------


def _parse_nse_date(value: str | None) -> date | None:
    text = (value or "").strip()
    if not text or text == "-":
        return None
    try:
        return datetime.strptime(text.title(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _parse_money(value: str | None) -> float | None:
    """Parse 'Rs.500', 'rs.500.00', '500' -> 500.0; blank/'-'/None -> None (case-insensitive)."""
    text = re.sub(r"(?i)rs\.?", "", value or "").replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_band(
    price_range: str | None, issue_price: str | None
) -> tuple[float | None, float | None]:
    """Parse 'Rs.475 to Rs.500' -> (475, 500); fall back to a single issue price."""
    parts = re.split(r"\bto\b", price_range or "", flags=re.IGNORECASE)
    if len(parts) == 2:
        low = _parse_money(parts[0])
        high = _parse_money(parts[1])
        if low is not None and high is not None:
            return low, high
    single = _parse_money(issue_price) or _parse_money(price_range)
    return single, single


def _segment_of_series(series: str) -> str:
    return SEGMENT_SME if series.strip().upper() == "SME" else SEGMENT_MAINBOARD


def parse_past_issues(raw: RawResponse) -> list[NsePastIssue]:
    """Parse the past-issues JSON into typed rows (fail loud on shape drift)."""
    try:
        data = json.loads(raw.content)
    except json.JSONDecodeError as exc:
        raise SourceError("nse: past-issues is not valid JSON") from exc
    if not isinstance(data, list):
        raise SourceError("nse: past-issues JSON is not a list (source drift?)")

    issues: list[NsePastIssue] = []
    for row in data:
        if "symbol" not in row or "securityType" not in row:
            raise SourceError("nse: past-issues row missing symbol/securityType (drift?)")
        low, high = _parse_band(row.get("priceRange", ""), row.get("issuePrice", ""))
        issues.append(
            NsePastIssue(
                symbol=row["symbol"].strip(),
                company=row.get("company", "").strip(),
                segment=_segment_of_series(row["securityType"]),
                price_band_low=low,
                price_band_high=high,
                open_date=_parse_nse_date(row.get("ipoStartDate", "")),
                close_date=_parse_nse_date(row.get("ipoEndDate", "")),
                listing_date=_parse_nse_date(row.get("listingDate", "")),
            )
        )
    return issues


def parse_subscription(raw: RawResponse) -> NseSubscription:
    """Parse NSE bid-details into final QIB/NII/retail/total multiples (fail loud)."""
    try:
        data = json.loads(raw.content)
    except json.JSONDecodeError as exc:
        raise SourceError("nse: subscription is not valid JSON") from exc
    rows = data.get("dataList")
    if not isinstance(rows, list):
        raise SourceError("nse: subscription has no dataList (drift?)")

    def value_for(predicate: object) -> float | None:
        for row in rows:
            category = str(row.get("category", "")).strip()
            if predicate(category):  # type: ignore[operator]
                raw_val = str(row.get("noOfTotalMeant", "")).strip()
                try:
                    return float(raw_val) if raw_val else None
                except ValueError:
                    return None
        return None

    return NseSubscription(
        qib=value_for(lambda c: "Qualified Institutional Buyers" in c),
        nii=value_for(lambda c: c == "Non Institutional Investors"),
        retail=value_for(lambda c: "Retail Individual Investors" in c),
        total=value_for(lambda c: c == "Total"),
        nii_small=value_for(lambda c: "Two Lakh Rupees upto Ten Lakh" in c),
        nii_big=value_for(lambda c: "more than Ten Lakh Rupees" in c),
    )


def parse_current_issues(raw: RawResponse) -> list[NseCurrentIssue]:
    """Parse the ``ipo-current-issue`` JSON (live/active issues) into typed rows (fail loud)."""
    try:
        data = json.loads(raw.content)
    except json.JSONDecodeError as exc:
        raise SourceError("nse: current-issue is not valid JSON") from exc
    if not isinstance(data, list):
        raise SourceError("nse: current-issue JSON is not a list (source drift?)")

    issues: list[NseCurrentIssue] = []
    for row in data:
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            raise SourceError("nse: current-issue row missing symbol (drift?)")
        low, high = _parse_band(row.get("issuePrice", ""), row.get("issuePrice", ""))
        issues.append(
            NseCurrentIssue(
                symbol=symbol,
                company=str(row.get("companyName", "")).strip(),
                segment=_segment_of_series(str(row.get("series", ""))),
                price_band_low=low,
                price_band_high=high,
                open_date=_parse_nse_date(row.get("issueStartDate", "")),
                close_date=_parse_nse_date(row.get("issueEndDate", "")),
            )
        )
    return issues


def parse_listing_prices(raw_csv: str, symbol: str) -> tuple[float, float] | None:
    """Extract (open, close) for ``symbol`` from a bhavcopy CSV (old or UDiFF format).

    Returns ``None`` if the symbol's EQ row is absent (e.g. listed only on BSE).
    """
    reader = csv.DictReader(io.StringIO(raw_csv))
    fields = {f.strip() for f in (reader.fieldnames or [])}
    # Old format: SYMBOL/SERIES/OPEN/CLOSE; UDiFF: TckrSymb/SctySrs/OpnPric/ClsPric.
    if {"SYMBOL", "OPEN", "CLOSE"} <= fields:
        sym_c, ser_c, open_c, close_c = "SYMBOL", "SERIES", "OPEN", "CLOSE"
    elif {"TckrSymb", "OpnPric", "ClsPric"} <= fields:
        sym_c, ser_c, open_c, close_c = "TckrSymb", "SctySrs", "OpnPric", "ClsPric"
    else:
        raise SourceError("nse: unrecognized bhavcopy columns (source drift?)")

    for row in reader:
        if row.get(sym_c, "").strip() == symbol and row.get(ser_c, "").strip() == "EQ":
            try:
                return float(row[open_c]), float(row[close_c])
            except (ValueError, KeyError) as exc:
                raise SourceError(f"nse: bad bhavcopy OHLC for {symbol}") from exc
    return None


def _unzip_single_csv(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise SourceError("nse: bhavcopy zip has no CSV")
        return zf.read(names[0]).decode("utf-8")


# --- network client (cookie handshake) --------------------------------------


class NseClient:
    """Cookie-priming, caching client for NSE's official endpoints (polite access)."""

    def __init__(self, client: PoliteClient, cache: RawCache) -> None:
        """Wire a (robots-disabled) polite client and the immutable raw cache."""
        self._client = client
        self._cache = cache
        self._primed = False

    def _ensure_cookies(self) -> None:
        if self._primed:
            return
        # Prime the session with NSE's anti-bot cookies (a browser does this implicitly).
        self._client.fetch("nse", NSE_HOMEPAGE)
        self._primed = True

    def _get_json(self, source: str, url: str, *, referer: str) -> RawResponse:
        cached = self._cache.get(source, url)
        if cached is not None:
            return cached
        self._ensure_cookies()
        resp = self._client.fetch(
            source, url, headers={"Accept": "application/json", "Referer": referer}
        )
        self._cache.store(resp, request_id=url)
        return resp

    def past_issues(self, *, force: bool = False) -> list[NsePastIssue]:
        """Fetch + parse the past-issues master list (``force`` re-fetches for new listings)."""
        if force:
            self._ensure_cookies()
            resp = self._client.fetch(
                "nse_past",
                PAST_ISSUES_URL,
                headers={"Accept": "application/json", "Referer": NSE_HOMEPAGE},
            )
            return parse_past_issues(resp)
        return parse_past_issues(self._get_json("nse_past", PAST_ISSUES_URL, referer=NSE_HOMEPAGE))

    def current_issues(self, *, force: bool = True) -> list[NseCurrentIssue]:
        """Fetch and parse the live/active issues (open or just-closed, pre-listing).

        ``force`` bypasses the immutable raw cache — current issues change intraday, so a live
        refresh must re-fetch rather than serve a stale snapshot (unlike the immutable past data).
        """
        if force:
            self._ensure_cookies()
            resp = self._client.fetch(
                "nse_current",
                CURRENT_ISSUES_URL,
                headers={"Accept": "application/json", "Referer": NSE_HOMEPAGE},
            )
            return parse_current_issues(resp)
        return parse_current_issues(
            self._get_json("nse_current", CURRENT_ISSUES_URL, referer=NSE_HOMEPAGE)
        )

    def subscription(self, symbol: str, *, force: bool = False) -> NseSubscription:
        """Fetch + parse subscription for one symbol (``force`` re-fetches live, skipping cache)."""
        url = f"{SUBSCRIPTION_URL}?symbol={symbol}"
        if force:
            self._ensure_cookies()
            resp = self._client.fetch(
                "nse_sub", url, headers={"Accept": "application/json", "Referer": NSE_HOMEPAGE}
            )
            return parse_subscription(resp)
        return parse_subscription(self._get_json("nse_sub", url, referer=NSE_HOMEPAGE))

    def listing_prices(self, symbol: str, listing_day: date) -> tuple[float, float] | None:
        """Fetch (cached) the bhavcopy for ``listing_day`` and return (open, close).

        NSE switched from the legacy ``cmDDMONYYYYbhav`` format to UDiFF in mid-2024,
        so the URL is chosen by date to avoid a guaranteed-404 round-trip (the 404 path
        is not cached). Both caches are checked first so a warm run never hits network.
        """
        mon = _MONTHS[listing_day.month - 1]
        old_url = BHAVCOPY_OLD.format(y=listing_day.year, mon=mon, d=listing_day.day)
        udiff_url = BHAVCOPY_UDIFF.format(ymd=listing_day.strftime("%Y%m%d"))

        for url in (old_url, udiff_url):
            cached = self._cache.get("nse_bhav", url)
            if cached is not None:
                return parse_listing_prices(cached.content, symbol)

        # Neither cached: fetch the format that actually exists for this date first.
        ordered = (old_url, udiff_url) if listing_day < _BHAVCOPY_CUTOVER else (udiff_url, old_url)
        for url in ordered:
            try:
                payload = self._client.fetch_bytes(url, headers={"Referer": NSE_BASE})
            except SourceError:
                continue
            csv_text = _unzip_single_csv(payload)
            resp = RawResponse(
                source="nse_bhav",
                url=url,
                fetched_at=now_ist(),
                content=csv_text,
                content_hash=compute_hash(csv_text),
            )
            self._cache.store(resp, request_id=url)
            return parse_listing_prices(csv_text, symbol)
        raise SourceError(f"nse: no bhavcopy available for {listing_day.isoformat()}")


def mainboard_since(issues: Sequence[NsePastIssue], start: date) -> list[NsePastIssue]:
    """Filter to mainboard issues that listed on or after ``start`` (the backfill window)."""
    return [
        i
        for i in issues
        if i.segment == SEGMENT_MAINBOARD and i.listing_date is not None and i.listing_date >= start
    ]
