"""Chittorgarh adapter — a real live source, scoped to its stable structured data.

Chittorgarh is the convenient aggregator but NOT authoritative: its figures are a
fast path that must be cross-checked against official NSE/BSE before entering a
label or backtest (Deep Dive #1). Its pages are heavy, JS-rendered HTML, so this
adapter deliberately parses only the **schema.org microdata listing table** —
stable, well-typed markup carrying (name, segment, issue price, listing-day close,
listing gain%) for many IPOs at once. Free-text page fields are intentionally out
of scope (too brittle to ship); the curated seed/official sources carry those.

Schema-validate on parse -> fail loud: if the expected microdata header or row
shape is absent, raise ``SourceError`` (the source-drift tripwire).
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ipo.core.constants import SEGMENT_MAINBOARD, SEGMENT_SME
from ipo.core.types import PartialRecord, RawResponse
from ipo.data.sources.base import PoliteClient, RawCache, SourceError

SOURCE_NAME = "chittorgarh"

# The microdata summary table exposes these columns, in this order, per row.
_EXPECTED_HEADERS = ("Issue Price", "Listing Day Close")
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _to_float(text: str) -> float | None:
    """Extract the first numeric token from a currency/percent string (commas stripped)."""
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    return float(match.group(0).replace(",", ""))


def _segment_of(text: str) -> str | None:
    norm = text.strip().lower()
    if "mainboard" in norm or "mainline" in norm:
        return SEGMENT_MAINBOARD
    if "sme" in norm:
        return SEGMENT_SME
    return None


class ChittorgarhSource:
    """A ``DataSource`` over Chittorgarh's schema.org IPO microdata table."""

    name = SOURCE_NAME

    def __init__(self, client: PoliteClient, cache: RawCache, *, base_url: str) -> None:
        """Wire the polite client and immutable cache; ``base_url`` is the site root."""
        self._client = client
        self._cache = cache
        self._base_url = base_url.rstrip("/")

    def fetch(self, ipo_id: str) -> RawResponse:
        """Fetch an IPO page (``ipo_id`` is the Chittorgarh URL path), cached immutably.

        Browser-like headers are required (the site 403s a bare client); the polite
        client supplies the configured User-Agent and the cache prevents re-fetching.
        """
        url = f"{self._base_url}/{ipo_id.strip('/')}/"
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        return self._client.get_or_fetch(self._cache, self.name, url, headers=headers)

    def parse(self, raw: RawResponse) -> PartialRecord:
        """Return the first microdata row as a ``PartialRecord`` (DataSource contract)."""
        rows = self.parse_listing(raw)
        if not rows:
            raise SourceError(f"{self.name}: no microdata rows found")
        return rows[0]

    def parse_listing(self, raw: RawResponse) -> list[PartialRecord]:
        """Parse every schema.org microdata row into partial records (pure).

        Each row yields ``name``, ``segment``, ``issue_size_cr``, ``price_band_high``
        (issue price = the as-of cut-off), ``listing_close``, and ``listing_gain_pct``.
        """
        soup = BeautifulSoup(raw.content, "html.parser")
        table = self._find_microdata_table(soup)
        if table is None:
            raise SourceError(f"{self.name}: microdata listing table not found (source drift?)")

        body = table.find("tbody")
        if not isinstance(body, Tag):
            raise SourceError(f"{self.name}: microdata table has no body")

        records: list[PartialRecord] = []
        for tr in body.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 6:
                raise SourceError(
                    f"{self.name}: unexpected row shape ({len(cells)} cells; source drift?)"
                )
            name = cells[0].get_text(strip=True)
            segment = _segment_of(cells[1].get_text())
            if not name or segment is None:
                raise SourceError(f"{self.name}: row missing name/segment (source drift?)")
            slug = self._slug_of(cells[0]) or name.lower().replace(" ", "-")
            fields: dict[str, object] = {
                "name": name,
                "segment": segment,
                "issue_size_cr": _to_float(cells[2].get_text()),
                "price_band_high": _to_float(cells[3].get_text()),
                "listing_close": _to_float(cells[4].get_text()),
                "listing_gain_pct": _to_float(cells[5].get_text()),
            }
            records.append(PartialRecord(source=self.name, ipo_id=slug, fields=fields))
        return records

    @staticmethod
    def _slug_of(cell: Tag) -> str | None:
        link = cell.find("a")
        if isinstance(link, Tag):
            href = link.get("href")
            if isinstance(href, str):
                parts = [p for p in href.split("/") if p]
                # .../ipo/<slug>/<id>/ -> use "<slug>-<id>" as a stable key
                if len(parts) >= 2:
                    return f"{parts[-2]}-{parts[-1]}"
        return None

    def _find_microdata_table(self, soup: BeautifulSoup) -> Tag | None:
        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue
            head_text = table.get_text(" ", strip=True)
            has_microdata = table.select_one('[itemprop="name"]') is not None
            if all(h in head_text for h in _EXPECTED_HEADERS) and has_microdata:
                return table
        return None
