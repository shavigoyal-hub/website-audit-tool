"""Parse a Screaming Frog `internal_all` export and run technical checks.

Each check returns a Finding (or None). A Finding is a plain dict:
    {
      "key": str,                 # stable id, mapped to copy in observations.py
      "count": int,               # how many instances (always reported as "multiple")
      "examples": [str, ...],     # example URLs (optionally "url: detail")
      "evidence": (tab_name, [headers], [rows]) | None,
    }
Only checks with count > 0 are returned.
"""
import re
from collections import Counter

import pandas as pd


def _col(df, name):
    """Return a column as a string Series, or an all-empty Series if absent."""
    if name in df.columns:
        return df[name].astype("string").fillna("")
    return pd.Series([""] * len(df), index=df.index, dtype="string")


def _num(df, name):
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series([pd.NA] * len(df), index=df.index)


# Always dropped : crawler/system URLs that are never real pages.
SYSTEM_EXCLUDE = ["/cdn-cgi/"]

# Pages that exist but are NOT organic-SEO landing pages. Excluded from
# content-quality checks (thin content, content depth, readability) and from
# the PageSpeed representative selection so we never report on, e.g., a staff
# bio or a client-login page as if it were a money page.
NON_SEO_PATTERNS = [
    "/team-member", "/team/", "/staff", "/author", "/client-login", "/client-logins",
    "/login", "/log-in", "/my-account", "/account", "/cart", "/checkout",
    "/privacy", "/terms", "/disclosure", "/disclaimer", "/legal", "/sitemap",
    "/search", "/thank-you", "/thank_you", "/404", "/wp-",
]


def _matches_any(addr_series, patterns):
    mask = pd.Series([False] * len(addr_series), index=addr_series.index)
    for pat in patterns:
        mask |= addr_series.str.contains(re.escape(pat), case=False, regex=True)
    return mask


def load(csv_path, exclude_patterns):
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    addr = _col(df, "Address")
    # Always drop crawler/system URLs (e.g. Cloudflare /cdn-cgi/), then drop
    # client-specific feeds paths from the *observation* scope.
    drop = (exclude_patterns or []) + SYSTEM_EXCLUDE
    if drop:
        df = df[~_matches_any(addr, drop)].reset_index(drop=True)
    return df


def is_non_seo(df):
    """Mask of pages that are not organic-SEO landing pages (bios, logins, etc.)."""
    return _matches_any(_col(df, "Address"), NON_SEO_PATTERNS)


def is_html(df):
    return _col(df, "Content Type").str.contains("text/html", case=False)


def is_image(df):
    return _col(df, "Content Type").str.contains("image/", case=False)


# ---------------------------------------------------------------------------
# Page-type classification (for PageSpeed representative selection)
# ---------------------------------------------------------------------------
PAGE_TYPE_RULES = [
    ("Homepage", lambda p: p in ("", "/")),
    ("Contact", lambda p: "contact" in p),
    ("About / Process", lambda p: any(k in p for k in ("about", "our-process", "process", "team", "who-we-are"))),
    ("Service / Product", lambda p: any(k in p for k in ("service", "product", "pricing", "solutions", "plans"))),
    ("Article / Blog", lambda p: any(k in p for k in ("blog", "article", "/category", "news", "post"))),
]


def _path(url):
    m = re.match(r"https?://[^/]+(/.*)?$", url.strip())
    return (m.group(1) or "/").lower() if m else "/"


def classify_page_type(url):
    p = _path(url).strip("/")
    for name, fn in PAGE_TYPE_RULES:
        if fn(p):
            return name
    return "Other / Landing"


def representative_pages(df_scoped):
    """One representative URL per page type, lowest crawl depth first.

    df_scoped = the observation-scoped dataframe (feeds + system URLs already
    removed). We additionally drop non-SEO pages (bios, logins) so PageSpeed
    is only ever reported on real organic landing pages, never a feeds/category
    or utility page.
    """
    html = df_scoped[is_html(df_scoped) & ~is_non_seo(df_scoped)].copy()
    html = html[_num(html, "Status Code").fillna(0).astype(int) == 200]
    if html.empty:
        return {}
    html["__type"] = _col(html, "Address").map(classify_page_type)
    html["__depth"] = _num(html, "Crawl Depth").fillna(99)
    reps = {}
    for ptype, grp in html.groupby("__type"):
        grp = grp.sort_values("__depth")
        reps[ptype] = grp.iloc[0]["Address"]
    return reps


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _finding(key, urls, evidence=None, detail=None):
    urls = list(dict.fromkeys(urls))  # dedupe, keep order
    if not urls:
        return None
    examples = urls[:8]
    return {"key": key, "count": len(urls), "examples": examples, "evidence": evidence, "detail": detail}


def run_checks(df, df_full, has_images_csv):
    findings = []
    addr = _col(df, "Address")
    html_mask = is_html(df)
    status = _num(df, "Status Code").fillna(0).astype(int)
    indexable = _col(df, "Indexability").str.lower()

    # JS / render errors ("JS Error" is a per-page error COUNT, not a flag)
    js_err = _num(df, "JS Error").fillna(0)
    m = html_mask & (js_err > 0)
    findings.append(_finding("render_error", addr[m].tolist()))

    # 4xx / 5xx
    findings.append(_finding("error_404", addr[status.between(400, 499)].tolist(),
                             evidence=("404 Pages", ["Address", "Status Code"],
                                       df.loc[status.between(400, 499), ["Address", "Status Code"]].values.tolist())))
    findings.append(_finding("error_5xx", addr[status.between(500, 599)].tolist()))

    # Redirects
    redir = status.between(300, 399)
    findings.append(_finding("redirects", addr[redir].tolist(),
                             evidence=("Redirects", ["Address", "Status Code", "Redirect URL"],
                                       df.loc[redir, ["Address", "Status Code", "Redirect URL"]].values.tolist()
                                       if "Redirect URL" in df.columns else
                                       df.loc[redir, ["Address", "Status Code"]].values.tolist())))

    # Non-indexable : ONLY pages explicitly blocked with a `noindex` directive.
    # (Pages that are "non-indexable" merely because they redirect or are
    #  canonicalised are NOT a problem and are deliberately excluded.)
    robots = _col(df, "Meta Robots 1").str.lower()
    ix_status = _col(df, "Indexability Status").str.lower()
    xrobots = _col(df, "X-Robots-Tag 1").str.lower()
    noindexed = html_mask & (
        robots.str.contains("noindex") | ix_status.str.contains("noindex") | xrobots.str.contains("noindex")
    )
    findings.append(_finding("non_indexable", addr[noindexed].tolist(),
                             evidence=("Non-Indexable", ["Address", "Meta Robots 1", "Indexability Status"],
                                       df.loc[noindexed, ["Address", "Meta Robots 1", "Indexability Status"]].values.tolist()
                                       if "Indexability Status" in df.columns else
                                       [[u, "", ""] for u in addr[noindexed]])))

    # Indexable HTML 200s : the scope for content/meta checks
    ok = html_mask & (status == 200) & (indexable != "non-indexable")
    # SEO-page scope = indexable pages that are real organic landing pages
    # (excludes staff bios, client-login, legal/utility pages). Used for the
    # content-quality checks where a thin bio page would be a false positive.
    seo = ok & ~is_non_seo(df)

    # Titles
    title = _col(df, "Title 1")
    tlen = _num(df, "Title 1 Length").fillna(0)
    long_title = ok & (tlen > 80)
    findings.append(_finding("title_long",
                             [f"{u}: {t}" for u, t in zip(addr[long_title], title[long_title])],
                             evidence=("Long Titles", ["Address", "Title 1", "Title 1 Length"],
                                       df.loc[long_title, ["Address", "Title 1", "Title 1 Length"]].values.tolist())))
    findings.append(_finding("title_missing", addr[ok & (title.str.strip() == "")].tolist()))
    # short title (<30 chars, excluding empty) on SEO pages
    findings.append(_finding("title_short", addr[seo & (tlen > 0) & (tlen < 30)].tolist()))
    # keyword-stuffed: 3+ pipe separators OR a token repeated 3+ times
    def stuffed(t):
        if t.count("|") >= 3:
            return True
        toks = [w for w in re.findall(r"[a-z]{4,}", t.lower())]
        return any(c >= 3 for c in Counter(toks).values())
    ks = ok & title.map(stuffed)
    findings.append(_finding("title_stuffed",
                             [f"{u}: {t}" for u, t in zip(addr[ks], title[ks])]))
    # duplicate titles : two+ distinct URLs sharing the exact same <title>
    tnorm = title.where(ok, "")
    counts = Counter(t for t in tnorm if t.strip())
    dupset = {t for t, c in counts.items() if c > 1}
    dup_mask = tnorm.isin(dupset) if dupset else pd.Series([False] * len(df), index=df.index)
    findings.append(_finding("title_duplicate", addr[dup_mask].tolist(),
                             evidence=("Duplicate Titles", ["Address", "Title 1"],
                                       df.loc[dup_mask, ["Address", "Title 1"]].sort_values("Title 1").values.tolist())))

    # Meta description
    md = _col(df, "Meta Description 1")
    mdlen = _num(df, "Meta Description 1 Length").fillna(0)
    findings.append(_finding("meta_long", addr[ok & (mdlen > 200)].tolist()))
    findings.append(_finding("meta_missing", addr[ok & (md.str.strip() == "")].tolist()))
    # short meta description (<70 chars, excluding empty) on SEO pages
    findings.append(_finding("meta_short", addr[seo & (mdlen > 0) & (mdlen < 70)].tolist()))
    # duplicate meta descriptions across pages
    mdnorm = md.where(ok & (mdlen > 0), "")
    md_counts = Counter(m for m in mdnorm if m.strip())
    md_dupset = {m for m, c in md_counts.items() if c > 1}
    md_dup_mask = mdnorm.isin(md_dupset) if md_dupset else pd.Series([False] * len(df), index=df.index)
    findings.append(_finding("meta_duplicate", addr[md_dup_mask].tolist()))

    # H1
    h1 = _col(df, "H1-1")
    miss_h1 = ok & (h1.str.strip() == "")
    findings.append(_finding("h1_missing", addr[miss_h1].tolist(),
                             evidence=("Missing H1", ["Address"], [[u] for u in addr[miss_h1]])))
    h12 = _col(df, "H1-2")
    findings.append(_finding("h1_multiple", addr[ok & (h12.str.strip() != "")].tolist()))
    # H1 length + duplicate H1 (SEO pages)
    h1len = _num(df, "H1-1 Length").fillna(0)
    findings.append(_finding("h1_long", addr[seo & (h1len > 70)].tolist()))
    findings.append(_finding("h1_short", addr[seo & (h1len > 0) & (h1len < 20)].tolist()))
    h1norm = h1.where(seo & (h1.str.strip() != ""), "")
    h1_counts = Counter(x for x in h1norm if x.strip())
    h1_dupset = {x for x, c in h1_counts.items() if c > 1}
    h1_dup_mask = h1norm.isin(h1_dupset) if h1_dupset else pd.Series([False] * len(df), index=df.index)
    findings.append(_finding("h1_duplicate", addr[h1_dup_mask].tolist()))

    # URL length (overly long URLs on SEO pages)
    findings.append(_finding("url_long",
                             [f"{u}: {len(u)} chars" for u in addr[seo & (addr.str.len() > 115)]]))

    # Thin content (SEO landing pages only : bios/logins excluded)
    wc = _num(df, "Word Count").fillna(0)
    thin = seo & (wc < 300)
    findings.append(_finding("thin_content", addr[thin].tolist(),
                             evidence=("Thin Content", ["Address", "Word Count"],
                                       df.loc[thin, ["Address", "Word Count"]].values.tolist())))
    very_thin = seo & (wc < 120)
    findings.append(_finding("content_depth", addr[very_thin].tolist()))

    # Near duplicates
    nd = _num(df, "No. Near Duplicates").fillna(0)
    near = ok & (nd > 0)
    findings.append(_finding("near_duplicate", addr[near].tolist(),
                             evidence=("Near Duplicates", ["Address", "No. Near Duplicates", "Closest Near Duplicate Match"],
                                       df.loc[near, ["Address", "No. Near Duplicates", "Closest Near Duplicate Match"]].values.tolist()
                                       if "Closest Near Duplicate Match" in df.columns else
                                       df.loc[near, ["Address", "No. Near Duplicates"]].values.tolist())))

    # Images > 100 KB (from internal_all when no dedicated images export)
    img_mask = is_image(df)
    size = _num(df, "Size (Bytes)").fillna(0)
    big = img_mask & (size > 100_000)
    findings.append(_finding("image_large",
                             [f"{u}: {int(s/1024)} KB" for u, s in zip(addr[big], size[big])],
                             evidence=("Images > 100 Kb", ["Address", "Size (Bytes)"],
                                       df.loc[big, ["Address", "Size (Bytes)"]].values.tolist())))

    # Carbon
    carbon = _col(df, "Carbon Rating").str.upper()
    findings.append(_finding("high_carbon", addr[ok & carbon.isin(["E", "F"])].tolist()))

    # Crawl depth
    depth = _num(df, "Crawl Depth").fillna(0)
    findings.append(_finding("deep_crawl", addr[ok & (depth > 4)].tolist()))

    # Missing canonical
    canon = _col(df, "Canonical Link Element 1")
    findings.append(_finding("canonical_missing", addr[ok & (canon.str.strip() == "")].tolist()))

    # Spelling / grammar
    sp = _num(df, "Spelling Errors").fillna(0)
    gr = _num(df, "Grammar Errors").fillna(0)
    findings.append(_finding("spelling_grammar", addr[ok & ((sp > 0) | (gr > 0))].tolist()))

    # Readability (SEO landing pages only)
    fre = _num(df, "Flesch Reading Ease Score")
    poor_read = seo & (fre < 30) & fre.notna()
    findings.append(_finding("poor_readability", addr[poor_read].tolist()))

    return [f for f in findings if f and f["count"] > 0]


# Master list of every CSV check that runs, with a friendly label, for the
# "Checks Passed" tab. A check is "passed" when it produced no finding.
CSV_CHECK_LABELS = {
    "render_error": "No JavaScript / rendering errors",
    "error_404": "No broken pages (404 errors)",
    "error_5xx": "No server errors (5xx)",
    "redirects": "No internal redirects",
    "non_indexable": "No pages blocked by a noindex directive",
    "title_long": "Title tag lengths within limit (≤80 chars)",
    "title_short": "Title tags not too short (≥30 chars)",
    "title_missing": "All pages have a title tag",
    "title_stuffed": "No keyword-stuffed titles",
    "title_duplicate": "No duplicate title tags",
    "meta_long": "Meta description lengths within limit (≤200 chars)",
    "meta_short": "Meta descriptions not too short (≥70 chars)",
    "meta_missing": "All pages have a meta description",
    "meta_duplicate": "No duplicate meta descriptions",
    "h1_missing": "All pages have an H1 tag",
    "h1_multiple": "Single H1 per page",
    "h1_long": "H1 tag lengths within limit (≤70 chars)",
    "h1_short": "H1 tags not too short (≥20 chars)",
    "h1_duplicate": "No duplicate H1 tags",
    "url_long": "URL lengths healthy (≤115 chars)",
    "thin_content": "Content depth healthy (≥300 words on SEO pages)",
    "content_depth": "Key informational sections present",
    "near_duplicate": "No near-duplicate content",
    "image_large": "Images within weight budget (≤100 KB)",
    "high_carbon": "Acceptable page weight / carbon rating",
    "deep_crawl": "Healthy crawl depth (≤4 clicks)",
    "canonical_missing": "Canonical tags present",
    "spelling_grammar": "No spelling / grammar errors",
    "poor_readability": "Readable copy (Flesch ≥30)",
}
