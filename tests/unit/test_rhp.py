"""RHP mandated-disclosure extraction (B6): correct parse, honest not-available, no invention."""

from __future__ import annotations

from ipo.service.rhp import extract_rhp_context

# A clean, well-OCR'd litigation summary (Vedant-style): 5 count columns + aggregate amount.
_CLEAN_SECTION = (
    "Summary of outstanding litigation proceedings involving our Company is provided below. "
    "Name of Entity Criminal Proceedings Tax Proceedings Statutory Regulatory Proceedings "
    "Disciplinary actions Material Civil Litigations Aggregate amount involved (in Rs million) "
    "Company By the Company Nil Nil Nil Nil 2 Nil "
    "Against the 3 10 5 Nil 4 240.53 Company "
    "Directors By the Directors Nil Nil Nil Nil Nil Nil"
)


def test_clean_section_parses_against_company() -> None:
    lit = extract_rhp_context(_CLEAN_SECTION).litigation
    assert lit.section_found
    assert lit.cases_against_company == 3 + 10 + 5 + 0 + 4  # Nil counts as zero
    assert lit.aggregate_amount_mn == 240.53
    assert lit.against_company_disclosed is True


def test_amount_unit_crore_normalized_to_million() -> None:
    section = _CLEAN_SECTION.replace("in Rs million", "in Rs crore")
    lit = extract_rhp_context(section).litigation
    assert lit.aggregate_amount_mn == round(240.53 * 10.0, 2)  # 1 crore = 10 million


def test_section_absent_is_not_available() -> None:
    lit = extract_rhp_context(
        "This prospectus has no litigation summary section at all."
    ).litigation
    assert lit.section_found is False
    assert lit.cases_against_company is None
    assert lit.aggregate_amount_mn is None
    assert lit.against_company_disclosed is None


def test_empty_text_is_all_none() -> None:
    ctx = extract_rhp_context("")
    assert ctx.litigation.section_found is False
    assert ctx.auditor_opinion is None
    assert ctx.related_party_disclosed is None


def test_garbled_row_reports_none_not_a_guess() -> None:
    # Section present (heading + Criminal marker + an entity row) but the against-company data row
    # is too mangled to yield >=4 count columns — the extractor must abstain, never invent.
    section = (
        "Summary of outstanding litigation is provided below. Criminal Proceedings. "
        "By the Company Nil Nil. Against the Company — figures illegible in the filing."
    )
    lit = extract_rhp_context(section).litigation
    assert lit.section_found is True
    assert lit.cases_against_company is None  # no fabricated number


def test_auditor_opinion_ranks_most_cautionary_first() -> None:
    assert extract_rhp_context("The auditors expressed a qualified opinion.").auditor_opinion == (
        "qualified"
    )
    assert extract_rhp_context("There is an Emphasis of Matter paragraph.").auditor_opinion == (
        "emphasis_of_matter"
    )
    both = "The report has an Emphasis of Matter and elsewhere a Qualified Opinion."
    assert extract_rhp_context(both).auditor_opinion == "qualified"  # qualified outranks EoM
    assert extract_rhp_context("Unmodified opinion issued.").auditor_opinion == "unqualified"
    assert extract_rhp_context("no opinion phrasing here").auditor_opinion is None


def test_related_party_presence() -> None:
    assert extract_rhp_context(
        "See Related Party Transactions in Annexure."
    ).related_party_disclosed
    assert extract_rhp_context("nothing relevant").related_party_disclosed is None
