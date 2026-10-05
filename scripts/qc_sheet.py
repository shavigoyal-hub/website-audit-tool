"""QC every audit sheet before we ship a deck.

Checks:
  1. Intro row's Lead-sum terms match each individual finding row's E stat
     (to the nearest 0.1%) — so 'Increase your leads by 35.1%' equals the sum
     of the component boxes shown next to it.
  2. Category text is a real chat-style name (not the generic 'Pages',
     'URLs', 'Homepage' when a more specific label exists like 'Thin Pages').
  3. No leaked Sheets error sentinels (#ERROR!, #REF!, #NAME?, #NUM!).
  4. No 'Site-wide' text (should be 'Sitewide' or a real URL).
  5. No leftover source citations ('Google 2020 field study:', 'Backlinko …:',
     'AWR 2024:', 'Web.dev …:', 'Moz on-page factors:').
  6. Supporting Stats (col I) leads with a stat, or is empty.
  7. Every E cell parses as a percentage or Nx.
  8. What We Found (G) has at least one URL, or 'Sitewide | …' for the
     site-wide finding keys.

Usage:
  python3 scripts/qc_sheet.py <spreadsheet-id-or-url> [...]
Exits non-zero when problems are found. Prints one line per issue.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.report_sheets import _composio_execute, _extract_first_range, _extract_sheet_id

_SITEWIDE_CAT = {
    "site architecture", "top navigation", "robots.txt file", "sitemap",
    "xml sitemap", "hub-subdomain", "crawl budget",
    "duplicate titles",  # every-page-same title is a sitewide finding
}

_GENERIC_CAT_TO_BETTER = {
    "pages": "Thin Pages",
    "urls":  "URL Length",
    "homepage": "Missing H1 / Homepage",
}

_SRC_RE = re.compile(
    r"\b(?:google\s+(?:20\d\d|search central|canonicalization|docs)|"
    r"backlinko(?:'s)?(?:\s+url\s+study|\s+on-page)|"
    r"moz on-page|semrush|awr\s+20\d\d|web\.dev|deloitte|"
    r"hubspot|nielsen|neil patel|search engine journal)\b[^.]{0,120}:",
    re.I,
)
_URL_RE = re.compile(r"https?://\S+")
# Google Sheets error sentinels: #ERROR!, #REF!, #NAME?, #NUM!, #NULL!,
# #DIV/0!, #N/A, #VALUE!. All start with # and are short-form.
_ERR_RE = re.compile(r"^#[A-Z/0-9]+[!?]?$")


def parse_pct(s):
    """Return abs pct from '+8.5%', '-12%', '0.25', 'N/A' etc. or None."""
    s = str(s or "").strip().lstrip("'")
    m = re.match(r"^([+\-]?)(\d+(?:\.\d+)?)%$", s)
    if m:
        return abs(float(m.group(2)))
    try:
        v = float(s)
        return abs(v * 100) if abs(v) <= 1.5 else abs(v)
    except ValueError:
        return None


def qc(sid):
    problems = []
    obs = _extract_first_range(_composio_execute("GOOGLESHEETS_BATCH_GET", {
        "spreadsheet_id": sid, "ranges": ["Observations!A1:I50"]})) or []
    sr = _extract_first_range(_composio_execute("GOOGLESHEETS_BATCH_GET", {
        "spreadsheet_id": sid, "ranges": ["Slide Review!A1:K10"]})) or []

    rows = []
    for i, r in enumerate(obs[1:], start=2):
        if not r or not any(str(c).strip() for c in r):
            continue
        get = lambda i2: str(r[i2] if i2 < len(r) else "").strip()
        rows.append({
            "row": i, "cat": get(0), "obs": get(1), "prio": get(2),
            "impact": get(3), "stat_e": get(4), "ctx_f": get(5),
            "found_g": get(6), "costs_h": get(7), "support_i": get(8),
        })

    # 1. Category checks
    for r in rows:
        low = r["cat"].strip().lower()
        if low in _GENERIC_CAT_TO_BETTER:
            problems.append((r["row"], "category",
                f"Category is generic '{r['cat']}' — use '{_GENERIC_CAT_TO_BETTER[low]}'"))
        if "duplicate title" in r["obs"].lower() and "sitewide" not in r["cat"].lower() and low not in ("duplicate titles",):
            # Only flag if the finding language suggests sitewide dup
            if "every page" in r["obs"].lower() or "sitewide" in r["obs"].lower():
                problems.append((r["row"], "category",
                    "Sitewide-dup-title finding but category isn't 'Duplicate Titles'"))

    # 2. Sheets error sentinels
    for r in rows:
        for col_label, val in [("D", r["impact"]), ("F", r["ctx_f"]),
                                ("G", r["found_g"]), ("H", r["costs_h"]),
                                ("I", r["support_i"])]:
            if _ERR_RE.match(val):
                problems.append((r["row"], f"col-{col_label}",
                    f"Sheets-error sentinel: {val!r}"))

    # 3. Site-wide leaks
    for r in rows:
        if "site-wide" in r["found_g"].lower():
            problems.append((r["row"], "col-G",
                "'Site-wide' text leaked into What We Found (should be 'Sitewide' or a real URL)"))

    # 4. Source citations
    for r in rows:
        for col_label, val in [("H", r["costs_h"]), ("I", r["support_i"])]:
            if _SRC_RE.search(val):
                problems.append((r["row"], f"col-{col_label}",
                    f"Source citation leaked: {_SRC_RE.search(val).group(0)!r}"))

    # 4b. Broken screenshot markers. IMG: GDRIVE_IMG:<id> or IMG: https://drive…
    # — these render as broken-image icons in the deck when the file isn't
    # publicly fetchable. User rule: no broken screenshots in deliverables.
    for r in rows:
        for col_label, val in [("H", r["costs_h"]), ("I", r["support_i"])]:
            if re.search(r"IMG:\s*(?:GDRIVE_IMG:|https?://)", val, re.I):
                problems.append((r["row"], f"col-{col_label}",
                    "contains IMG: marker — verify screenshot renders before shipping"))

    # 5. Support (I) leads with stat or is empty.
    # Strip any inline IMG: markers before checking — chatbot-attached
    # screenshots live in the same cell and shouldn't fail the stat-lead
    # rule when the actual prose does start with a stat.
    _img_re = re.compile(r"\s*IMG:\s*\S+\s*", re.I)
    for r in rows:
        v = _img_re.sub(" ", r["support_i"]).strip()
        if not v:
            continue
        starts_with_stat = bool(re.match(
            r"^\s*(?:[+\-]?\d+(?:[.,-]\d+)?\s*(?:%|x)|"        # 5%, -12%, 3-5%, 2-3x
            r"\d+\s+of\s+\d+|"                                  # 1 of 10
            r"only\s+\d+\s+of\s+\d+|"                          # Only 1 of N
            r"\d[\d,]{2,}|"                                     # 1,000+
            r"\d+\s+(?:seconds|sec|min|hours?|days?|ms|sites?|"
            r"users?|pages?|visitors?|clicks?|leads?|percent|out\s+of))",
            v, re.I))
        if not starts_with_stat:
            problems.append((r["row"], "col-I",
                f"Support doesn't lead with a stat: {v[:60]!r}"))

    # 6. E parses
    for r in rows:
        if r["stat_e"] and parse_pct(r["stat_e"]) is None:
            problems.append((r["row"], "col-E",
                f"Hook Stat doesn't parse: {r['stat_e']!r}"))

    # 6b. hook_ctx (col F) must say WHAT the stat measures — not just
    # restate the finding title. Catches rows like '-25% Generic H1 tag on
    # homepage' where the reader has no idea whether that's ranking, CTR,
    # leads, or traffic. hook_ctx should contain at least one metric word.
    _METRIC_WORDS = (
        "lead", "leads", "ranking", "rankings", "rank", "indexation",
        "crawl", "coverage", "visibility", "ctr", "click-through",
        "click", "clicks", "impression", "impressions", "snippet",
        "serp", "conversion", "conversions", "bounce", "traffic",
        "citation", "citations", "share", "equity", "authority",
    )
    for r in rows:
        ctx = (r["ctx_f"] or "").lower()
        # Strip the leading stat portion (produced by the F formula) before
        # checking — e.g. '-25% ranking loss when …' should pass the check
        # on 'ranking', not on the '%' from the stat.
        ctx_body = re.sub(r"^\s*[+\-]?\d+(?:[.,]\d+)?%\s*", "", ctx)
        if not ctx_body.strip():
            continue
        if not any(w in ctx_body for w in _METRIC_WORDS):
            problems.append((r["row"], "col-F",
                f"Hook Context doesn't name a metric (leads/ranking/CTR/…): "
                f"{(r['ctx_f'] or '')[:60]!r}"))

    # 7. What We Found: has URL or Sitewide
    for r in rows:
        g = r["found_g"]
        if not g:
            problems.append((r["row"], "col-G", "empty"))
            continue
        if not (_URL_RE.search(g) or g.lower().startswith("sitewide")
                or "→ 404" in g or "→ 40" in g):
            problems.append((r["row"], "col-G",
                f"No URL and not marked sitewide: {g[:60]!r}"))

    # 8. Intro sum vs individual E cells
    intro_row = None
    for i, r in enumerate(sr[1:], start=2):
        if r and str(r[0] if r else "").strip().lower() == "intro":
            intro_row = r; break
    if intro_row:
        # Slide Review layout: A=kind, B=packed, C..K=raw 9 fields
        # The 'What we found' line inside packed carries the intro formula.
        packed = str(intro_row[1] if len(intro_row) > 1 else "")
        wf_m = re.search(r"What we found:\s*(.+?)(?:\n|$)", packed)
        wf_line = wf_m.group(1) if wf_m else ""
        # Parse "+11.8% Homepage Content Quality  +  +9.5% Sitemap  ... = +35.1% More leads"
        m = re.findall(r"\+([\d.]+)%\s+([A-Za-z][^+=]*?)(?:\s{2,}\+|\s{2,}=|$)", wf_line)
        parsed_terms = [(float(pct), lbl.strip()) for pct, lbl in m if lbl.strip().lower() != "more leads"]
        total_m = re.search(r"=\s*\+?([\d.]+)%\s+More leads", wf_line)
        intro_total = float(total_m.group(1)) if total_m else None
        # Compare each term to its individual row E cell.
        # Fuzzy match: exact lower-case, else token-overlap >= 2 — a CS
        # reviewer who renames 'H1 Tags' → 'Missing H1' between runs
        # shouldn't trip the QC.
        def _match_row(label):
            lbl = label.strip().lower()
            toks_l = set(lbl.split())
            best = (0, None)
            for rr in rows:
                cat = rr["cat"].strip().lower()
                if not cat:
                    continue
                if cat == lbl:
                    return rr  # exact wins immediately
                score = 0
                if lbl in cat or cat in lbl:
                    score = max(len(lbl), 3)
                else:
                    toks_c = set(cat.split())
                    score = len(toks_l & toks_c)
                if score > best[0]:
                    best = (score, rr)
            return best[1] if best[0] >= 2 else None

        for pct, label in parsed_terms:
            match_row = _match_row(label)
            if not match_row:
                problems.append((0, "intro",
                    f"Intro term '{label}' has no matching row in Observations"))
                continue
            row_pct = parse_pct(match_row["stat_e"])
            if row_pct is None or abs(row_pct - pct) > 0.15:
                problems.append((match_row["row"], "intro-mismatch",
                    f"Intro says +{pct}% {label} but row's E = {match_row['stat_e']!r} ({row_pct})"))
        # Total = sum of components?
        # Only fair to check when the intro shows every component. When it
        # collapses N items into '(N more)' the visible sum is intentionally
        # smaller — skip the total check in that case.
        has_hidden = "more)" in wf_line
        if not has_hidden and intro_total is not None and parsed_terms:
            calc_total = round(sum(p for p, _ in parsed_terms), 1)
            if abs(intro_total - calc_total) > 0.2:
                problems.append((0, "intro-total",
                    f"Intro total = {intro_total}% but components sum to {calc_total}%"))
    else:
        problems.append((0, "intro", "no Intro row in Slide Review tab"))

    return problems


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    exit_code = 0
    for arg in sys.argv[1:]:
        sid = _extract_sheet_id(arg) or arg
        print(f"\n=== QC {sid} ===")
        try:
            problems = qc(sid)
        except Exception as exc:
            print(f"  ERROR reading sheet: {exc}")
            exit_code = 2
            continue
        if not problems:
            print("  ✅ clean")
            continue
        exit_code = 1
        for row, cat, msg in problems:
            loc = f"row {row:>2}" if row else "     "
            print(f"  {loc} [{cat:12}] {msg}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
