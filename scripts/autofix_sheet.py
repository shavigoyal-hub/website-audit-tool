"""QC + auto-correction layer. Runs the same checks as scripts/qc_sheet.py
but applies safe fixes in place for every issue the catalog can resolve.

Fixable classes:
  - Sheets error sentinel (#ERROR!, #REF!, #N/A, …) → blank the cell
  - 'Site-wide' leak in G → rewrite to 'Sitewide | <label>' for known site-wide
    keys, else to '{harvested URL from observation} | <label>'
  - Non-parseable Hook Stat (E) → _clean_stat_row (bare decimals → %, strips
    trailing text, etc.)
  - Hook Context missing a metric word → rebuild formula with catalog hook_ctx
    if the row's category maps to a known key, else prepend 'ranking loss when '
  - Support doesn't lead with a stat → replace from catalog if key known;
    otherwise blank it (deck already hides empty support cards)
  - Source citation in H or I → run the hook_copy scrubber regex
  - Duplicate category (case-insensitive) → suffix the later row with ' (N)'

Classes NOT fixed (needs human judgment, left as warnings):
  - 'What it costs you' too long (col-H > 220 chars / >2 sentences)
  - IMG: marker in cell (always warn — image may or may not be valid)
  - Intro-vs-components mismatch (v95 render-time recompute handles it)

Usage:
  COMPOSIO_API_KEY=... python3 scripts/autofix_sheet.py <sheet-id-or-url> [...]
Returns 0 even when it couldn't fix something — exit non-zero only on hard
error.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.hook_copy import HOOK_COPY, STATUS_LABEL
from audit.report_sheets import (
    _composio_execute, _extract_first_range, _extract_sheet_id,
    _clean_stat_row,
)
try:
    from audit.report_sheets import _SITEWIDE_KEYS
except ImportError:
    _SITEWIDE_KEYS = set()


# ─── category → canonical catalog key (same table the recompute uses) ────────
_CATEGORY_TO_KEY = {
    "page speed": "lcp_high", "page speed (lcp)": "lcp_high",
    "thin pages": "thin_content", "thin content": "thin_content",
    "homepage content quality": "thin_content", "pages": "thin_content",
    "above-fold cta": "cta_missing", "cta": "cta_missing",
    "missing cta": "cta_missing",
    "homepage title": "homepage_title_weak",
    "homepage title quality": "homepage_title_weak",
    "sitemap": "sitemap_missing", "xml sitemap": "sitemap_missing",
    "duplicate titles": "title_duplicate_sitewide",
    "title tags": "title_duplicate",
    "missing h1": "h1_missing", "h1 tags": "h1_missing",
    "meta descriptions": "meta_missing", "meta description": "meta_missing",
    "schema markup": "structured_data", "homepage schema": "structured_data",
    "content visibility": "content_visibility",
    "content visibility (render gap)": "content_visibility",
    "render blocked": "render_blocked",
    "missing title": "title_missing",
    "top navigation": "flat_architecture",
    "duplicate h1 across pages": "h1_duplicate",
    "multiple h1 on same page": "h1_multiple",
    "short titles": "title_short",
    "long urls": "url_long", "url length": "url_long",
    "canonical tags": "canonical_not_self",
    "canonical host mismatch": "canonical_not_self",
    "favicon": "favicon_missing",
    "about / company page": "about_missing",
    "contact page": "contact_missing",
}

_ERR_RE   = re.compile(r"^#[A-Z/0-9]+[!?]?$")
_URL_RE   = re.compile(r"https?://\S+")
_METRIC_WORDS = (
    "lead", "leads", "ranking", "rankings", "rank", "indexation",
    "crawl", "coverage", "visibility", "ctr", "click-through",
    "click", "clicks", "impression", "impressions", "snippet",
    "serp", "conversion", "conversions", "bounce", "traffic",
    "citation", "citations", "share", "equity", "authority",
)
_STAT_START_RE = re.compile(
    r"^\s*(?:[+\-]?\d+(?:[.,-]\d+)?\s*(?:%|x)|"
    r"\d+\s+of\s+\d+|only\s+\d+\s+of\s+\d+|"
    r"\d[\d,]{2,}|"
    r"\d+\s+(?:seconds|sec|min|hours?|days?|ms|sites?|users?|pages?|"
    r"visitors?|clicks?|leads?|percent|out\s+of))",
    re.I,
)
_IMG_RE = re.compile(r"\s*IMG:\s*\S+\s*", re.I)


def _retry(fn, *a, **k):
    for att in range(6):
        try: return fn(*a, **k)
        except Exception as e:
            if "429" in str(e) and att < 5: time.sleep(8 * (att + 1)); continue
            raise


def _write(sid, row, col, val, mode="USER_ENTERED"):
    _retry(_composio_execute, "GOOGLESHEETS_BATCH_UPDATE", {
        "spreadsheet_id": sid, "sheet_name": "Observations",
        "first_cell_location": f"{col}{row}",
        "valueInputOption": mode, "values": [[val]]})


def _formula(r, ctx):
    ctx = ctx.replace('"', '""')
    return (f'=IF(E{r}="","{ctx}",'
            f'IFERROR(TEXT(E{r},"+#.#%;-#.#%;0%")&" "&"{ctx}",'
            f'E{r}&" "&"{ctx}"))')


def _key_for(category):
    return _CATEGORY_TO_KEY.get((category or "").strip().lower())


def autofix(sid):
    """Returns (fixes_applied, warnings_left)."""
    v = _retry(_extract_first_range, _composio_execute("GOOGLESHEETS_BATCH_GET", {
        "spreadsheet_id": sid, "ranges": ["Observations!A1:I50"],
    })) or []
    rows = []
    for i, r in enumerate(v[1:], start=2):
        if not r or not any(str(c).strip() for c in r):
            continue
        get = lambda i2: str(r[i2] if i2 < len(r) else "").strip()
        rows.append({
            "row": i, "cat": get(0), "obs": get(1), "prio": get(2),
            "impact": get(3), "stat_e": get(4), "ctx_f": get(5),
            "found_g": get(6), "costs_h": get(7), "support_i": get(8),
        })

    fixes = []
    warnings = []

    # ─── Fix 1: #ERROR / #N/A sentinels in D,F,G,H,I → blank ────────────
    for r in rows:
        for col, val in [("D", r["impact"]), ("F", r["ctx_f"]),
                          ("G", r["found_g"]), ("H", r["costs_h"]),
                          ("I", r["support_i"])]:
            if _ERR_RE.match(val):
                _write(sid, r["row"], col, "")
                fixes.append(f"row {r['row']} {col}: blanked sentinel {val!r}")

    # ─── Fix 2: 'Site-wide' leak in G ────────────────────────────────────
    for r in rows:
        if "site-wide" not in r["found_g"].lower():
            continue
        key = _key_for(r["cat"])
        label = (STATUS_LABEL.get(key) or (r["cat"], ""))[0] or "Issue"
        if key in _SITEWIDE_KEYS:
            new_g = f"Sitewide | {label}"
        else:
            # Harvest URLs from observation
            urls = _URL_RE.findall(r["obs"])
            if urls:
                new_g = "\n".join(f"{u} | {label}" for u in urls[:5])
            else:
                new_g = f"Sitewide | {label}"
        _write(sid, r["row"], "G", new_g)
        fixes.append(f"row {r['row']} G: 'Site-wide' → {new_g[:40]!r}")

    # ─── Fix 3: Hook Stat (E) unparseable → _clean_stat_row ──────────────
    for r in rows:
        e = r["stat_e"]
        if not e or _clean_stat_row(e) == e.lstrip("'"):
            continue
        cleaned = _clean_stat_row(e)
        if cleaned != e:
            _write(sid, r["row"], "E", cleaned)
            fixes.append(f"row {r['row']} E: {e!r} → {cleaned!r}")

    # ─── Fix 4: Hook Context (F) missing a metric word ───────────────────
    for r in rows:
        ctx = (r["ctx_f"] or "").lower()
        ctx_body = re.sub(r"^\s*[+\-]?\d+(?:[.,]\d+)?%\s*", "", ctx)
        if not ctx_body.strip():
            continue
        if any(w in ctx_body for w in _METRIC_WORDS):
            continue
        # Try catalog
        key = _key_for(r["cat"])
        if key and HOOK_COPY.get(key, {}).get("hook_ctx"):
            new_ctx = HOOK_COPY[key]["hook_ctx"]
        else:
            # Generic fallback: prepend 'ranking loss when '
            raw = re.sub(r"^\s*[+\-]?\d+(?:[.,]\d+)?%\s*", "", r["ctx_f"]).strip()
            new_ctx = f"ranking loss when {raw[0].lower() + raw[1:]}" if raw else "ranking loss."
        _write(sid, r["row"], "F", _formula(r["row"], new_ctx))
        fixes.append(f"row {r['row']} F: metric-less ctx replaced")

    # ─── Fix 5: Support (I) doesn't lead with a stat ─────────────────────
    for r in rows:
        sup_wo_img = _IMG_RE.sub(" ", r["support_i"]).strip()
        if not sup_wo_img:
            continue
        if _STAT_START_RE.match(sup_wo_img):
            continue
        key = _key_for(r["cat"])
        if key and HOOK_COPY.get(key, {}).get("support"):
            cat_sup = HOOK_COPY[key]["support"]
            if _STAT_START_RE.match(cat_sup):
                # Preserve any IMG: markers from the original cell
                imgs = _IMG_RE.findall(r["support_i"])
                new_i = cat_sup
                if imgs:
                    new_i += "\n" + "\n".join(imgs)
                _write(sid, r["row"], "I", new_i)
                fixes.append(f"row {r['row']} I: non-stat support → catalog stat")
                continue
        # No usable catalog stat → warn, don't blank (preserve user content)
        warnings.append(f"row {r['row']} I: non-stat support, no catalog match "
                        f"({sup_wo_img[:50]!r})")

    # ─── Fix 6: Source citations in H / I ────────────────────────────────
    _SRC = (r"Google(?:\s+Search\s+Central)?", r"Moz", r"Backlinko", r"Ahrefs",
            r"Semrush", r"AWR", r"Web\.dev", r"Deloitte(?:/Google)?",
            r"HubSpot", r"Nielsen", r"Neil\s+Patel", r"Search\s+Engine\s+Journal",
            r"Wikipedia", r"Yoast", r"Chartbeat", r"Portent")
    src_alt = "|".join(_SRC)
    prefix_re = re.compile(r"^\s*(?:" + src_alt + r")\b[^:;—–.\n]{0,120}[:;—–]\s*",
                           re.I)
    for r in rows:
        for col, val in [("H", r["costs_h"]), ("I", r["support_i"])]:
            if prefix_re.search(val):
                stripped = prefix_re.sub("", val).strip()
                if stripped and stripped[0].islower():
                    stripped = stripped[0].upper() + stripped[1:]
                _write(sid, r["row"], col, stripped)
                fixes.append(f"row {r['row']} {col}: source citation stripped")

    # ─── Fix 7b: Category / observation topic mismatch ───────────────────
    # If category says 'Meta Descriptions' but obs+ctx talks about title
    # tags (and never mentions meta description), the LLM swapped topics.
    # Re-canonicalize category to match what the content actually describes.
    def _topic_of(text):
        t = (text or "").lower()
        # Order matters: check more-specific tokens first.
        if "meta description" in t or "meta descriptions" in t:
            return "meta"
        if "title tag" in t or "title tags" in t or "duplicate title" in t:
            return "title"
        if "h1" in t:
            return "h1"
        if "schema" in t or "structured data" in t:
            return "schema"
        if "sitemap" in t:
            return "sitemap"
        if "robots.txt" in t:
            return "robots"
        if "canonical" in t:
            return "canonical"
        if "lcp" in t or "page speed" in t or "load" in t and "slow" in t:
            return "speed"
        if "cls" in t or "layout shift" in t:
            return "cls"
        if "thin content" in t or "thin page" in t:
            return "thin"
        if "duplicate content" in t:
            return "dup_content"
        if "cta" in t or "above-fold" in t or "above the fold" in t:
            return "cta"
        return None

    _CAT_TOPIC = {
        "meta descriptions": "meta",
        "duplicate meta descriptions": "meta",
        "title tags": "title",
        "duplicate titles": "title",
        "missing h1": "h1",
        "schema markup": "schema",
        "homepage schema": "schema",
        "xml sitemap": "sitemap",
        "robots.txt": "robots",
        "robots.txt blocking": "robots",
        "canonical tags": "canonical",
        "page speed": "speed",
        "page speed (lcp)": "speed",
        "layout shift (cls)": "cls",
        "thin pages": "thin",
        "duplicate content": "dup_content",
        "above-fold cta": "cta",
    }
    _TOPIC_TO_CAT = {
        "meta": "Meta Descriptions",
        "title": "Title Tags",
        "h1": "Missing H1",
        "schema": "Schema Markup",
        "sitemap": "XML Sitemap",
        "robots": "Robots.txt",
        "canonical": "Canonical Tags",
        "speed": "Page Speed",
        "cls": "Layout Shift (CLS)",
        "thin": "Thin Pages",
        "dup_content": "Duplicate Content",
        "cta": "Above-Fold CTA",
    }
    for r in rows:
        cat_norm = r["cat"].strip().lower()
        cat_topic = _CAT_TOPIC.get(cat_norm)
        if not cat_topic:
            continue
        content_topic = _topic_of(f"{r['obs']} {r['ctx_f']}")
        if content_topic and content_topic != cat_topic:
            new_cat = _TOPIC_TO_CAT.get(content_topic)
            # Specialize: duplicate variant if obs says 'duplicate'
            obs_l = r["obs"].lower()
            if content_topic == "title" and "duplicate" in obs_l:
                new_cat = "Duplicate Titles"
            if content_topic == "meta" and "duplicate" in obs_l:
                new_cat = "Duplicate Meta Descriptions"
            if new_cat and new_cat.lower() != cat_norm:
                _write(sid, r["row"], "A", new_cat)
                fixes.append(f"row {r['row']} A: category {r['cat']!r} → {new_cat!r} "
                             f"(content topic '{content_topic}')")
                r["cat"] = new_cat  # so Fix 7 duplicate check uses updated value

    # ─── Fix 7: Duplicate category names (case-insensitive) ──────────────
    seen = {}
    for r in rows:
        cat = r["cat"].strip().lower()
        if not cat:
            continue
        if cat not in seen:
            seen[cat] = r["row"]
            continue
        # Later occurrence — suffix with ' (dup N)' so the deck slide
        # header is distinguishable but the data stays.
        n = sum(1 for v in seen.values() if v != r["row"]) + 1
        new_cat = f"{r['cat']} (dup {n})"
        _write(sid, r["row"], "A", new_cat)
        fixes.append(f"row {r['row']} A: duplicate category → {new_cat!r}")

    # ─── Fix 8: Costs (H) starts with a coordinating conjunction ─────────
    # "And picks the wrong sentence." / "But rankings suffer." — reads as a
    # fragment because the LLM paraphrased mid-paragraph and the opening
    # clause got dropped. Strip the conjunction and recase.
    _CONJ_RE = re.compile(r"^\s*(?:and|but|so|or|yet|also)\b[\s,]+", re.I)
    for r in rows:
        costs = r["costs_h"]
        if not costs or not _CONJ_RE.match(costs):
            continue
        stripped = _CONJ_RE.sub("", costs).strip()
        if stripped:
            stripped = stripped[0].upper() + stripped[1:]
            _write(sid, r["row"], "H", stripped)
            fixes.append(f"row {r['row']} H: dropped leading conjunction "
                         f"({costs[:30]!r} → {stripped[:30]!r})")
            r["costs_h"] = stripped

    # ─── Fix 9: hook_ctx asserts 'none/no' but Found column has URLs ─────
    # Ctx says 'You have none on the pages that matter' but col G lists
    # several URLs with real statuses — contradiction. Rebuild ctx from
    # catalog hook_ctx so the headline matches reality.
    _ABS_NONE_RE = re.compile(
        r"\b(?:you\s+have\s+none|none\s+of\s+your|no\s+pages\s+have|"
        r"zero\s+pages|not\s+a\s+single)\b", re.I)
    for r in rows:
        ctx = r["ctx_f"]
        if not ctx or not _ABS_NONE_RE.search(ctx):
            continue
        # Count URL lines in Found column
        found_lines = [l.strip() for l in (r["found_g"] or "").split("\n")
                        if l.strip()]
        url_lines = [l for l in found_lines if l.startswith(("http", "/"))
                     or "|" in l]
        if len(url_lines) < 2:
            continue  # 0-1 found lines, 'none' may be literally true
        key = _key_for(r["cat"])
        cat_ctx = (HOOK_COPY.get(key) or {}).get("hook_ctx")
        if not cat_ctx:
            warnings.append(f"row {r['row']} F: ctx says 'none' but found "
                            f"{len(url_lines)} URLs — no catalog ctx to rebuild")
            continue
        _write(sid, r["row"], "F", _formula(r["row"], cat_ctx))
        fixes.append(f"row {r['row']} F: 'none' claim contradicts {len(url_lines)} "
                     f"found URLs → catalog ctx")

    # ─── Fix 11: '(no URL supplied)' / 'no URL' in Found column ──────────
    # LLM sometimes writes a placeholder like '(no URL supplied)' into
    # col G when it can't find the evidence URL. The deck renders this
    # as a broken link ('https://website-audit-tool.../(no%20URL%20supplied)').
    # Replace with the sheet's homepage URL (Meta tab live_url) when the
    # category is a sitewide/homepage check, else blank it.
    _NO_URL_RE = re.compile(
        r"\(?\s*no\s+url\s+(?:supplied|provided|given|available)\s*\)?",
        re.I)
    # Pull live_url from Meta tab once
    _live_url = ""
    try:
        _meta = _retry(_extract_first_range, _composio_execute(
            "GOOGLESHEETS_BATCH_GET",
            {"spreadsheet_id": sid, "ranges": ["Meta!A1:B20"]})) or []
        for r_m in _meta:
            if r_m and len(r_m) >= 2 and str(r_m[0]).strip().lower() in ("live_url", "live url"):
                _live_url = str(r_m[1]).strip()
                break
    except Exception:
        pass
    for r in rows:
        g = r["found_g"]
        if not g or not _NO_URL_RE.search(g):
            continue
        # Replace placeholder with homepage URL + preserve any status label
        # after the placeholder on the same line.
        new_lines = []
        changed = False
        for ln in g.splitlines():
            if _NO_URL_RE.search(ln):
                changed = True
                tail = _NO_URL_RE.sub("", ln).strip(" |")
                if _live_url:
                    new_lines.append(f"{_live_url} | {tail}" if tail else _live_url)
                # If no live_url, drop the line
            else:
                new_lines.append(ln)
        if changed:
            new_g = "\n".join(new_lines).strip()
            if new_g:
                _write(sid, r["row"], "G", new_g)
                fixes.append(f"row {r['row']} G: '(no URL supplied)' → homepage")
            else:
                warnings.append(f"row {r['row']} G: '(no URL supplied)' and no live_url to substitute")

    # ─── Fix 10: LLM safety-speak hook_ctx / costs → catalog ─────────────
    # Patterns the LLM reaches for when paraphrasing: 'may lower', 'can
    # lead to', 'resulting in', 'impacting visibility', 'due to
    # insufficient', 'decreased trust', 'ensure that', 'leverage'.
    # These produce vague corporate copy ('Google may lower your ranking
    # due to insufficient content, impacting visibility and leads.')
    # instead of the catalog's punchy line. Replace from catalog whenever
    # the row's category maps to a known key.
    _LLM_SPEAK_RE = re.compile(
        r"\b(?:may\s+lower|can\s+lead\s+to|lead\s+to\s+decreased|"
        r"resulting\s+in|impacting\s+visibility|impacting\s+leads|"
        r"due\s+to\s+insufficient|decreased\s+trust|"
        r"ensure\s+that|leverag(?:e|ing)|utiliz(?:e|ing)|"
        r"it\s+is\s+important\s+to|in\s+order\s+to\s+improve)\b",
        re.I)
    for r in rows:
        key = _key_for(r["cat"])
        if not key or key not in HOOK_COPY:
            continue
        cat = HOOK_COPY[key]
        # Fix hook_ctx
        ctx_wo_stat = re.sub(r"^\s*[+\-]?\d+(?:[.,]\d+)?%\s*", "", r["ctx_f"])
        if _LLM_SPEAK_RE.search(ctx_wo_stat) and cat.get("hook_ctx"):
            _write(sid, r["row"], "F", _formula(r["row"], cat["hook_ctx"]))
            fixes.append(f"row {r['row']} F: LLM-speak ctx → catalog "
                         f"({ctx_wo_stat[:40]!r})")
        # Fix costs
        if _LLM_SPEAK_RE.search(r["costs_h"]) and cat.get("costs"):
            _write(sid, r["row"], "H", cat["costs"])
            fixes.append(f"row {r['row']} H: LLM-speak costs → catalog "
                         f"({r['costs_h'][:40]!r})")

    # ─── Non-fixable warnings (needs human) ──────────────────────────────
    for r in rows:
        costs = r["costs_h"].strip()
        if not costs: continue
        _sentences = [s for s in re.split(r"[.!?](?:\s|$)", costs) if s.strip()]
        if len(costs) > 220 or len(_sentences) > 2:
            warnings.append(f"row {r['row']} H: too long "
                            f"({len(costs)} chars, {len(_sentences)} sentences) — human edit required")
        for col, val in [("H", r["costs_h"]), ("I", r["support_i"])]:
            if re.search(r"IMG:\s*(?:GDRIVE_IMG:|https?://)", val, re.I):
                warnings.append(f"row {r['row']} {col}: IMG: marker present — "
                                "verify screenshot renders before shipping")

    return fixes, warnings


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for arg in sys.argv[1:]:
        sid = _extract_sheet_id(arg) or arg
        print(f"\n=== autofix {sid} ===")
        try:
            fixes, warnings = autofix(sid)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue
        print(f"  applied {len(fixes)} fix(es):")
        for line in fixes:
            print(f"    ✓ {line}")
        if warnings:
            print(f"  {len(warnings)} warning(s) left for human review:")
            for line in warnings:
                print(f"    ⚠ {line}")
        else:
            print("  no warnings left")


if __name__ == "__main__":
    main()
