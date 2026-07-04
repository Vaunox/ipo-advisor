"""RHP mandated-disclosure extraction (v2 B6, Option B — informational context only).

Reads the SEBI-mandated disclosure sections of a Red Herring Prospectus and returns a
small, honest ``RhpContext`` of notable facts — the standardized *Summary of Outstanding
Litigation* table (Schedule VI / SEBI Master Circular), the auditor's opinion, and whether
related-party transactions are disclosed. It targets the fixed-format mandated sections, not
freeform prose.

**This never touches the score.** It is pure text extraction that produces display context;
nothing here feeds a feature, a kill-flag, or the calibrator. Every field is honestly
``None`` ("not available") when it cannot be reliably parsed — the module never guesses a
number. Whether the extraction is accurate *enough* to surface in the UI is an empirical
question answered by the probe (``research/rhp_probe.py`` → ``docs/B6_RHP_PROBE.md``), not by
this module; it is deliberately **unwired** until that evidence is in.

RHP text is OCR-extracted and noisy (reflowed table columns, garbled tokens), so the parser
prefers robust coarse signals (was the section found? is litigation disclosed against the
company?) over brittle exact values, and reports the latter only when confident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Litigation summary -----------------------------------------------------

# The mandated section heading (appears in the TOC and again at the real section).
_LITIGATION_HEADING = re.compile(r"summary of (?:the )?(?:outstanding )?litigation", re.I)
# Markers that a window is the real fixed-format table, not the table of contents.
_TABLE_MARKERS = re.compile(r"criminal", re.I)
_ENTITY_ROW = re.compile(r"\b(?:by|against)\s+(?:the|our)\b", re.I)
# The "Against [the|our] <digit>..." data row for the Company (a data row starts with a number
# right after the label; the descriptive column header does not).
_AGAINST_DATA_ROW = re.compile(r"[Aa]gainst\s+(?:the\s+|our\s+)?(?=\d)")
# One table token: a monetary amount (decimal, maybe grouped), a small integer count, or a
# Nil / N.A. spelling that means zero.
_TOKEN = re.compile(r"\d{1,3}(?:,\d{2,3})*\.\d+|\d{1,3}|nil|n\.?\s?a\.?l?|none", re.I)
_NIL_TOKEN = re.compile(r"nil|n\.?\s?a\.?l?|none", re.I)

# Amount unit → multiplier to ₹ million (1 crore = 10 mn, 1 lakh = 0.1 mn).
_UNIT_TO_MN = {"crore": 10.0, "cr": 10.0, "lakh": 0.1, "lac": 0.1, "million": 1.0, "mn": 1.0}
_UNIT = re.compile(r"\b(crore|cr|lakh|lac|million|mn)\b", re.I)


@dataclass(frozen=True)
class LitigationSummary:
    """Extracted facts from the mandated *Summary of Outstanding Litigation* table.

    Coarse signals (``section_found``, ``against_company_disclosed``) are robust to OCR noise;
    the structured values (``cases_against_company``, ``aggregate_amount_mn``) are best-effort
    and ``None`` when the reflowed table can't be parsed confidently — never a guess.
    """

    section_found: bool
    against_company_disclosed: bool | None
    cases_against_company: int | None
    aggregate_amount_mn: float | None
    source_quote: str | None


@dataclass(frozen=True)
class RhpContext:
    """Notable, informational facts extracted from an RHP's mandated sections.

    Display context only — never a scoring input. Each field is ``None`` when the source
    section could not be reliably located/parsed, so the UI can honestly show "not available".
    """

    litigation: LitigationSummary
    auditor_opinion: str | None  # "unqualified" | "qualified" | "emphasis_of_matter"
    related_party_disclosed: bool | None


_NOT_AVAILABLE_LITIGATION = LitigationSummary(False, None, None, None, None)


def _find_section(text: str) -> str | None:
    """Return the real litigation-summary region (skipping the table-of-contents match)."""
    best: str | None = None
    for match in _LITIGATION_HEADING.finditer(text):
        window = text[match.start() : match.start() + 1600]
        # The real section carries the fixed-format table (a "Criminal ... Proceedings" header
        # and entity rows); the TOC entry is followed only by other section titles.
        if _TABLE_MARKERS.search(window) and _ENTITY_ROW.search(window):
            best = window  # prefer the last such occurrence (detail sections repeat the table)
    return best


def _row_values(window: str) -> tuple[list[int], float | None]:
    """Parse a reflowed entity row into (count columns, aggregate amount).

    The fixed table has five count columns (criminal / tax / regulatory / disciplinary / civil)
    then one monetary aggregate. We walk tokens in order: integers and Nil/N.A. are counts (capped
    at five); the first decimal token is the aggregate amount and ends the count run.
    """
    counts: list[int] = []
    amount: float | None = None
    for token in _TOKEN.finditer(window):
        s = token.group(0)
        if _NIL_TOKEN.fullmatch(s):  # Nil / N.A. is a zero count (check before the decimal test)
            counts.append(0)
        elif "." in s:  # a decimal is the monetary aggregate — counts end here
            amount = float(s.replace(",", ""))
            break
        else:
            counts.append(int(s))
        if len(counts) >= 5:  # count columns full; the aggregate is the next decimal
            nxt = re.search(r"\d{1,3}(?:,\d{2,3})*\.\d+", window[token.end() :])
            amount = float(nxt.group(0).replace(",", "")) if nxt else None
            break
    return counts, amount


def _against_company_row(section: str) -> str | None:
    """Isolate the 'Against ... the Company' data row within the section, if present."""
    for match in _AGAINST_DATA_ROW.finditer(section):
        window = section[match.start() : match.start() + 180]
        counts, _ = _row_values(window)
        if re.search(r"\bcompany\b", window, re.I) and len(counts) >= 3:
            return window
    return None


def _litigation(text: str) -> LitigationSummary:
    section = _find_section(text)
    if section is None:
        return _NOT_AVAILABLE_LITIGATION
    row = _against_company_row(section)
    if row is None:
        return LitigationSummary(True, None, None, None, _clean(section[:180]))
    counts, amount = _row_values(row)
    cases = sum(counts) if len(counts) >= 4 else None  # need most columns to be confident
    unit = _UNIT.search(section)
    mult = _UNIT_TO_MN.get(unit.group(1).lower(), 1.0) if unit else 1.0
    amount_mn = round(amount * mult, 2) if amount is not None else None
    disclosed = None if cases is None else cases > 0
    return LitigationSummary(True, disclosed, cases, amount_mn, _clean(row[:180]))


# --- Auditor opinion --------------------------------------------------------

_AUDITOR = [
    ("qualified", re.compile(r"qualified opinion", re.I)),
    ("emphasis_of_matter", re.compile(r"emphasis of matter", re.I)),
    ("unqualified", re.compile(r"unmodified opinion|unqualified opinion", re.I)),
]


def _auditor_opinion(text: str) -> str | None:
    """The auditor's opinion flavour, or None if no standard phrasing is present.

    A qualified opinion outranks an emphasis of matter, which outranks a clean opinion — the
    most cautionary disclosure that appears is the one worth surfacing.
    """
    for label, pattern in _AUDITOR:
        if pattern.search(text):
            return label
    return None


# --- Related-party ----------------------------------------------------------

_RELATED_PARTY = re.compile(r"related party transaction", re.I)


def _related_party_disclosed(text: str) -> bool | None:
    """True if a related-party-transactions disclosure is present; None if not detectable.

    Note: this is near-universal in RHPs (every issuer discloses RPTs), so on its own it barely
    discriminates — the probe reports its base rate so the UI doesn't surface a constant.
    """
    return True if _RELATED_PARTY.search(text) else None


def _clean(fragment: str) -> str:
    """Collapse OCR whitespace/newlines so a source quote reads on one line."""
    return re.sub(r"\s+", " ", fragment).strip()


def extract_rhp_context(text: str) -> RhpContext:
    """Extract the informational ``RhpContext`` from an RHP's full text.

    Pure and side-effect-free. Returns honest ``None`` / ``section_found=False`` for anything
    that can't be reliably parsed — never a fabricated figure. Not wired into scoring.
    """
    if not text:
        return RhpContext(_NOT_AVAILABLE_LITIGATION, None, None)
    return RhpContext(
        litigation=_litigation(text),
        auditor_opinion=_auditor_opinion(text),
        related_party_disclosed=_related_party_disclosed(text),
    )
