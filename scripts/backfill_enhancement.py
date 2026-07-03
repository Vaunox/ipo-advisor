"""Backfill the three enhancement features (OFS / valuation / anchor) from Chittorgarh.

Research-only, operator-directed historical pull (analogous to the IPOMatrix GMP trial):
one-time, rate-limited, cached immutably. It exists to run the enhancement re-calibration
gate (docs/ENHANCEMENT_GATE.md), NOT as a sanctioned ongoing source. robots.txt allows the
generic UA on /ipo/ pages; the named AI-bot blocks (GPTBot, CCBot, …) are respected by not
using those agents. Data is Chittorgarh's, not redistributed.

For each of the 293 OOS-eligible mainboard IPOs it:
  1. resolves the Chittorgarh page (exact slug / hand-verified brand override / token match),
  2. fetches + caches the page, and VERIFIES the IPO name on the page matches the backfill
     name — a wrong join can't silently corrupt the gate,
  3. parses:
       * ofs_fraction  — OFS ÷ total issue (clean; pure-OFS=1.0, pure-fresh=0.0),
       * issue_pe      — post-issue P/E ("-ve"/blank ⇒ None + loss_making flag),
       * peer tables   — captured verbatim for the hand-QA pass (peer P/E is brittle),
  4. writes enhancement_main.csv + a coverage summary.

Never fabricates: a field that isn't cleanly present is left blank and flagged.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parents[1]
_STORE = _ROOT / "data_store" / "_enhancement"
_PAGES = _STORE / "pages"
_CSV = _ROOT / "data" / "backfill" / "mainboard_ipos.csv"
_SLUGMAP = _STORE / "chittorgarh_ipo_urls.json"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"  # noqa: E501
_HDRS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_RATE_S = 1.3

# Hand-verified brand overrides (legal name ≠ Chittorgarh slug), keyed by normalized name.
_OVERRIDES: dict[str, str] = {
    "antony-waste-handling-cell": "antony-waste-ipo/1078",
    "easy-trip-planners": "easemytrip-ipo/1089",
    "barbeque-nation-hospitality": "barbeque-nation-ipo/1102",
    "macrotech-developers": "lodha-developers-ipo/1107",
    "computer-age-management-services": "cams-ipo/1055",
    "sona-blw-precision-forgings": "sona-comstar-ipo/1112",
    "krishna-institute-of-medical-sciences": "kims-ipo/1115",
    "pb-fintech": "policybazaar-ipo/1172",
    "star-health-and-allied-insurance-company": "star-health-ipo/1184",
    "rategain-travel-technologies": "rategain-ipo/1189",
    "medplus-health-services": "medplus-health-ipo/1195",
    "ags-transact-technologies": "ags-transact-ipo/1209",
    "syrma-sgs-technology": "syrma-ipo/1276",
    "bikaji-foods-international": "bikaji-foods-ipo/1332",
    "yatharth-hospital-and-trauma-care-services": "yatharth-hospital-ipo/1464",
    "honasa-consumer": "mamaearth-ipo/1551",
    "india-shelter-finance-corporation": "india-shelter-ipo/1477",
    "credo-brands-marketing": "mufti-ipo/1595",
    "gopal-snacks": "gopal-namkeen-ipo/1667",
    "le-travenues-technology": "ixigo-ipo/1742",
    "dee-development-engineers": "dee-piping-systems-ipo/1746",
    "allied-blenders-and-distillers": "allied-blenders-ipo/1580",
    "ecos-india-mobility-and-hospitality": "eco-mobility-ipo/1820",
    "zinka-logistics-solutions": "blackbuck-ipo/1904",
    "one-mobikwik-systems": "mobikwik-ipo/1928",
    "unimech-aerospace-and-manufacturing": "unimech-aerospace-ipo/1942",
    "quality-power-electrical-equipments": "quality-power-ipo/1988",
    "schloss-bangalore": "leela-hotels-ipo/2182",
    "shanti-gold-international": "shanti-gold-ipo/2008",
    "bluestone-jewellery-and-lifestyle": "bluestone-jewellery-ipo/2059",
    "euro-pratik-sales": "euro-pratik-ipo/2015",
    "ganesh-consumer-products": "ganesh-consumer-ipo/2045",
    "solarworld-energy-solutions": "solarworld-energy-ipo/2174",
    "jaro-institute-of-technology-management-and-research": "jaro-education-ipo/2075",
    "canara-robeco-asset-management-company": "canara-robeco-ipo/2428",
    "billionbrains-garage-ventures": "groww-ipo/2453",
    "tenneco-clean-air-india": "tenneco-clean-ipo/2509",
    "nephrocare-health-services": "nephrocare-health-ipo/2548",
    "icici-prudential-asset-management-company": "icici-prudential-amc-ipo/2525",
    "pngs-reva-diamond-jewellery": "pngs-reva-ipo/2475",
    "gsp-crop-science": "gsp-crop-ipo/2031",
}

_STOP = {"limited", "ltd", "the", "of", "and", "india", "company", "corporation", "co"}


def norm(name: str) -> str:
    n = name.lower().replace("&", " and ")
    n = re.sub(r"\b(limited|ltd\.?)\b", "", n)
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-")


def toks(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and t not in _STOP}


def _cr(cell: str) -> float | None:
    """The Rs-crore aggregate in a details cell (ignores face value like 'Rs 1')."""
    m = re.findall(r"₹\s*([\d,]+(?:\.\d+)?)\s*(?:cr|crore)", cell, re.I)
    return float(m[-1].replace(",", "")) if m else None


def _norm_escapes(s: str) -> str:
    """Unescape single- and double-escaped Next.js HTML so script-embedded tables parse."""
    for a, b in (
        ("\\\\u003c", "<"),
        ("\\\\u003e", ">"),
        ("\\\\u0026", "&"),
        ('\\\\"', '"'),
        ("\\u003c", "<"),
        ("\\u003e", ">"),
        ("\\u0026", "&"),
        ('\\"', '"'),
    ):
        s = s.replace(a, b)
    return s


def peer_median_pe(html: str) -> tuple[float | None, int, int, list[tuple[str, float | None]]]:
    """Median P/E of the *peer* rows in the RHP peer-comparison table (issuer row excluded).

    The peer table is embedded as escaped HTML inside the Next.js JSON, so it is unescaped and
    parsed as a fragment (BeautifulSoup won't parse inside <script>). Returns
    (median, n_clean_peers, n_peers_total, rows). ``None`` when there is no peer table or no peer
    has a positive P/E (loss-making / no listed peer) — flagged, never forced.
    """
    txt = _norm_escapes(html)
    for m in re.finditer(r"Company Name", txt):  # bounded window around the peer-table header
        i = m.start()
        start = txt.rfind("<table", max(0, i - 2500), i)
        end = txt.find("</table>", i)
        if start < 0 or end < 0:
            continue
        block = txt[start : end + 8]
        if "P/E" not in block:
            continue
        frag = BeautifulSoup(block, "html.parser")
        rows = [
            [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            for tr in frag.find_all("tr")
        ]
        if not rows:
            continue
        hdr = [h.lower().strip() for h in rows[0]]
        pe_i = next((i for i, h in enumerate(hdr) if h in ("p/e (x)", "p/e")), None)
        if pe_i is None:
            continue
        data = [r for r in rows[1:] if len(r) > pe_i and r[0]]
        peers: list[tuple[str, float | None]] = []
        for r in data[1:]:  # data[0] is the issuer's own row — excluded from the peer median
            v = r[pe_i].strip().replace(",", "")
            peers.append((r[0][:40], float(v) if re.match(r"^\d+(?:\.\d+)?$", v) else None))
        clean = [v for _, v in peers if v and v > 0]
        med = round(statistics.median(clean), 2) if clean else None
        return med, len(clean), len(peers), peers
    return None, 0, 0, []


def resolve(rows: list[dict[str, str]], slugmap: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    """ipo_id -> (chittorgarh_slug, id, confidence). id-override > name-override > exact > token."""
    # Per-ipo_id overrides (brand renames / normalization edge cases resolved by verified search).
    extra_path = _STORE / "overrides_extra.json"
    extra: dict[str, str] = (
        json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.is_file() else {}
    )
    bases: dict[str, str] = {}
    for slug, i in slugmap.items():
        base = slug[:-4] if slug.endswith("-ipo") else slug
        bases.setdefault(base, slug + "|" + i if not slug.endswith("-ipo") else slug + "|" + i)
    base_tokens = {b: toks(b) for b in bases}
    out: dict[str, tuple[str, str, str]] = {}
    for r in rows:
        if r["ipo_id"] in extra:
            slug, i = extra[r["ipo_id"]].split("/")
            out[r["ipo_id"]] = (slug, i, "id_override")
            continue
        key = norm(r["name"])
        if key in _OVERRIDES:
            slug, i = _OVERRIDES[key].split("/")
            out[r["ipo_id"]] = (slug, i, "override")
            continue
        full = key + "-ipo"
        if full in slugmap:
            out[r["ipo_id"]] = (full, slugmap[full], "exact")
            continue
        mt = toks(r["name"])
        best = None
        for b, bt in base_tokens.items():
            if not mt:
                continue
            inter = mt & bt
            contain = len(inter) / len(mt)
            jac = len(inter) / len(mt | bt)
            if contain >= 0.99 or (contain >= 0.75 and jac >= 0.5):
                score = (contain, jac)
                if best is None or score > best[0]:
                    best = (score, b)
        if best is not None:
            b = best[1]
            slug = b + "-ipo" if (b + "-ipo") in slugmap else b
            out[r["ipo_id"]] = (
                slug,
                slugmap.get(slug, slugmap.get(b + "-ipo", "?")),
                f"token{best[0][0]:.2f}",
            )
    return out


def fetch(slug: str, cid: str, ipo_id: str) -> str | None:
    fp = _PAGES / f"{ipo_id}.html"
    if fp.is_file():
        return fp.read_text(encoding="utf-8")
    url = f"https://www.chittorgarh.com/ipo/{slug}/{cid}/"
    try:
        r = requests.get(url, headers=_HDRS, timeout=25)
        if r.status_code != 200:
            return None
        fp.write_text(r.text, encoding="utf-8")
        time.sleep(_RATE_S)
        return r.text
    except requests.RequestException:
        return None


def page_name(soup: BeautifulSoup) -> str:
    t = soup.find("title")
    txt = t.get_text(strip=True) if t else ""
    return re.split(r"\bIPO\b", txt)[0].strip()


def details_kv(soup: BeautifulSoup) -> dict[str, str]:
    kv: dict[str, str] = {}
    for tbl in soup.find_all("table"):
        for tr in tbl.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) == 2 and cells[0]:
                kv.setdefault(cells[0].lower().strip(), cells[1])
    return kv


def parse_page(html: str) -> dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    kv = details_kv(soup)

    def find(*keys: str) -> str | None:
        for k, v in kv.items():
            if all(t in k for t in keys):
                return v
        return None

    fresh = find("fresh", "issue")
    ofs = find("offer for sale") or find("offer", "sale")
    total = find("total issue")
    fresh_cr = _cr(fresh) if fresh else None
    ofs_cr = _cr(ofs) if ofs else None
    total_cr = _cr(total) if total else None
    if total_cr is None and (fresh_cr is not None or ofs_cr is not None):
        total_cr = (fresh_cr or 0) + (ofs_cr or 0)
    ofs_fraction = None
    if total_cr and total_cr > 0:
        ofs_fraction = round((ofs_cr or 0.0) / total_cr, 4)

    # Issue P/E from the issuer valuation table (pre/post-IPO). Prefer POST-issue (the standard
    # IPO P/E at cap price, fully diluted); a "-ve"/blank post = loss-making ⇒ issue_pe None.
    issue_pe_pre = issue_pe_post = None
    for tbl in soup.find_all("table"):
        head = tbl.get_text(" ", strip=True).lower()
        if "p/e" in head and ("pre ipo" in head or "post ipo" in head):
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                if cells and re.match(r"p\s*/\s*e", cells[0].strip(), re.I):
                    vals = [c.strip().replace(",", "") for c in cells[1:]]
                    if vals and re.match(r"^\d+(?:\.\d+)?$", vals[0]):
                        issue_pe_pre = float(vals[0])
                    if len(vals) >= 2 and re.match(r"^\d+(?:\.\d+)?$", vals[-1]):
                        issue_pe_post = float(vals[-1])
                    break
            break
    issue_pe = issue_pe_post if (issue_pe_post and issue_pe_post > 0) else None
    pe_flag = "" if issue_pe is not None else "no_post_pe_or_loss_making"

    peer_med, n_clean_peers, n_peers, peer_rows = peer_median_pe(html)
    # relative_valuation is CLEAN only when BOTH the issuer post-issue P/E and a clean peer
    # median exist. Loss-making issuer or no clean peer ⇒ None (neutral-with-flag, Deep Dive #2).
    rel_val = round(issue_pe / peer_med, 4) if (issue_pe and peer_med) else None
    if rel_val is not None:
        val_flag = "clean"
    elif issue_pe is None and peer_med is None:
        val_flag = "no_issue_pe_and_no_peer"
    elif issue_pe is None:
        val_flag = "issuer_loss_making_no_post_pe"
    else:
        val_flag = "no_clean_peer_pe"

    return {
        "fresh_cr": fresh_cr,
        "ofs_cr": ofs_cr,
        "total_cr": total_cr,
        "ofs_fraction": ofs_fraction,
        "issue_pe": issue_pe,
        "issue_pe_pre": issue_pe_pre,
        "issue_pe_post": issue_pe_post,
        "pe_flag": pe_flag,
        "peer_median_pe": peer_med,
        "n_clean_peers": n_clean_peers,
        "n_peers": n_peers,
        "peer_rows": peer_rows,
        "relative_valuation": rel_val,
        "val_flag": val_flag,
        "page_name": page_name(soup),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    _PAGES.mkdir(parents=True, exist_ok=True)
    slugmap = json.loads(_SLUGMAP.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(open(_CSV, encoding="utf-8")))

    def ne(v: object) -> bool:
        return bool(v) and str(v).strip() not in ("", "None", "nan")

    elig = [r for r in rows if ne(r.get("qib_sub")) and ne(r.get("listing_open"))]
    res = resolve(elig, slugmap)
    print(f"eligible {len(elig)} | resolved URL for {len(res)}")

    out_rows = []
    peer_dump = {}
    n_fetch = n_ofs = n_pe = n_namebad = n_nourl = n_peer = n_val = 0
    for r in elig:
        rid = r["ipo_id"]
        if rid not in res:
            n_nourl += 1
            out_rows.append({"ipo_id": rid, "name": r["name"], "status": "no_url"})
            continue
        slug, i, conf = res[rid]
        html = fetch(slug, i, rid)
        if html is None:
            out_rows.append(
                {"ipo_id": rid, "name": r["name"], "status": "fetch_failed", "slug": slug}
            )
            continue
        n_fetch += 1
        p = parse_page(html)
        name_ok = len(toks(r["name"]) & toks(str(p["page_name"]))) >= 1 or conf == "override"
        if not name_ok:
            n_namebad += 1
        if p["ofs_fraction"] is not None:
            n_ofs += 1
        if p["issue_pe"] is not None:
            n_pe += 1
        if p["peer_median_pe"] is not None:
            n_peer += 1
        if p["relative_valuation"] is not None:
            n_val += 1
        peer_dump[rid] = {
            "name": r["name"],
            "page_name": p["page_name"],
            "issue_pe_post": p["issue_pe_post"],
            "issue_pe_pre": p["issue_pe_pre"],
            "peer_median_pe": p["peer_median_pe"],
            "peer_rows": p["peer_rows"],
            "relative_valuation": p["relative_valuation"],
            "val_flag": p["val_flag"],
        }
        out_rows.append(
            {
                "ipo_id": rid,
                "name": r["name"],
                "status": "ok",
                "conf": conf,
                "slug": slug,
                "page_name": p["page_name"],
                "name_ok": name_ok,
                "fresh_cr": p["fresh_cr"],
                "ofs_cr": p["ofs_cr"],
                "total_cr": p["total_cr"],
                "ofs_fraction": p["ofs_fraction"],
                "issue_pe": p["issue_pe"],
                "pe_flag": p["pe_flag"],
                "peer_median_pe": p["peer_median_pe"],
                "n_clean_peers": p["n_clean_peers"],
                "relative_valuation": p["relative_valuation"],
                "val_flag": p["val_flag"],
            }
        )

    fields = [
        "ipo_id",
        "name",
        "status",
        "conf",
        "slug",
        "page_name",
        "name_ok",
        "fresh_cr",
        "ofs_cr",
        "total_cr",
        "ofs_fraction",
        "issue_pe",
        "pe_flag",
        "peer_median_pe",
        "n_clean_peers",
        "relative_valuation",
        "val_flag",
    ]
    with open(_STORE / "enhancement_main.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)
    (_STORE / "peer_tables.json").write_text(
        json.dumps(peer_dump, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nCOVERAGE (of {len(elig)} eligible):")
    print(f"  fetched pages            : {n_fetch}")
    print(f"  no URL resolved          : {n_nourl}")
    print(f"  NAME MISMATCH (review)   : {n_namebad}")
    print(f"  ofs_fraction populated   : {n_ofs}")
    print(f"  issue_pe (post) populated: {n_pe}")
    print(f"  peer_median_pe populated : {n_peer}")
    print(f"  relative_valuation CLEAN : {n_val}")
    print("  wrote enhancement_main.csv + peer_tables.json")


if __name__ == "__main__":
    main()
