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


def load(csv_path, exclude_patterns):
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    addr = _col(df, "Address")
    # Drop feeds / excluded paths from the *observation* scope.
    if exclude_patterns:
        mask = pd.Series([True] * len(df), index=df.index)
        for pat in exclude_patterns:
            mask &= ~addr.str.contains(re.escape(pat), case=False, regex=True)
        df = df[mask].reset_index(drop=True)
    return df


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


def representative_pages(df_full):
    """One representative URL per page type, lowest crawl depth first.

    df_full = the UN-excluded dataframe (we still want a blog representative to
    characterise that template, even though feeds are out of observation scope).
    """
    html = df_full[is_html(df_full)].copy()
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

    # Non-indexable (HTML only)
    nonidx = html_mask & (indexable == "non-indexable")
    findings.append(_finding("non_indexable", addr[nonidx].tolist(),
                             evidence=("Non-Indexable", ["Address", "Indexability Status"],
                                       df.loc[nonidx, ["Address", "Indexability Status"]].values.tolist()
                                       if "Indexability Status" in df.columns else
                                       [[u, ""] for u in addr[nonidx]])))

    # Indexable HTML 200s — the scope for content/meta checks
    ok = html_mask & (status == 200) & (indexable != "non-indexable")

    # Titles
    title = _col(df, "Title 1")
    tlen = _num(df, "Title 1 Length").fillna(0)
    long_title = ok & (tlen > 60)
    findings.append(_finding("title_long",
                             [f"{u}: {t}" for u, t in zip(addr[long_title], title[long_title])],
                             evidence=("Long Titles", ["Address", "Title 1", "Title 1 Length"],
                                       df.loc[long_title, ["Address", "Title 1", "Title 1 Length"]].values.tolist())))
    findings.append(_finding("title_missing", addr[ok & (title.str.strip() == "")].tolist()))
    # keyword-stuffed: 3+ pipe separators OR a token repeated 3+ times
    def stuffed(t):
        if t.count("|") >= 3:
            return True
        toks = [w for w in re.findall(r"[a-z]{4,}", t.lower())]
        return any(c >= 3 for c in Counter(toks).values())
    ks = ok & title.map(stuffed)
    findings.append(_finding("title_stuffed",
                             [f"{u}: {t}" for u, t in zip(addr[ks], title[ks])]))
    # duplicate titles
    dup_titles = []
    tnorm = title.where(ok, "")
    counts = Counter(t for t in tnorm if t.strip())
    dupset = {t for t, c in counts.items() if c > 1}
    if dupset:
        dup_titles = addr[tnorm.isin(dupset)].tolist()
    findings.append(_finding("title_duplicate", dup_titles))

    # Meta description
    md = _col(df, "Meta Description 1")
    mdlen = _num(df, "Meta Description 1 Length").fillna(0)
    findings.append(_finding("meta_long", addr[ok & (mdlen > 160)].tolist()))
    findings.append(_finding("meta_missing", addr[ok & (md.str.strip() == "")].tolist()))

    # H1
    h1 = _col(df, "H1-1")
    miss_h1 = ok & (h1.str.strip() == "")
    findings.append(_finding("h1_missing", addr[miss_h1].tolist(),
                             evidence=("Missing H1", ["Address"], [[u] for u in addr[miss_h1]])))
    h12 = _col(df, "H1-2")
    findings.append(_finding("h1_multiple", addr[ok & (h12.str.strip() != "")].tolist()))

    # Thin content
    wc = _num(df, "Word Count").fillna(0)
    thin = ok & (wc < 300)
    findings.append(_finding("thin_content", addr[thin].tolist(),
                             evidence=("Thin Content", ["Address", "Word Count"],
                                       df.loc[thin, ["Address", "Word Count"]].values.tolist())))
    very_thin = ok & (wc < 120)
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

    # Missing alt text — only derivable from a dedicated Images export
    if not has_images_csv:
        findings.append({"key": "alt_text_skipped", "count": 0, "examples": [], "evidence": None, "detail": None})

    # Response time
    rt = _num(df, "Response Time").fillna(0)
    slow = ok & (rt > 1.0)
    findings.append(_finding("slow_response",
                             [f"{u}: {r:.2f}s" for u, r in zip(addr[slow], rt[slow])]))

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

    # Readability
    fre = _num(df, "Flesch Reading Ease Score")
    poor_read = ok & (fre < 30) & fre.notna()
    findings.append(_finding("poor_readability", addr[poor_read].tolist()))

    return [f for f in findings if f and (f["count"] > 0 or f["key"] == "alt_text_skipped")]
