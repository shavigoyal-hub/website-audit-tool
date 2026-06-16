"""Map raw findings -> Observation rows (Observation | Priority | Impact | Reference).

Copy is neutral and SEO-focused (pure problem list). Every observation is phrased
as "Multiple ... found" per house style, even for a single instance.
"""

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# Short 2-3 word header/category for each observation (shown as the first column).
CATEGORY = {
    "render_error": "Rendering",
    "error_404": "Broken Links",
    "error_5xx": "Server Errors",
    "redirects": "Redirects",
    "non_indexable": "Indexability",
    "title_long": "Title Length",
    "title_missing": "Missing Titles",
    "title_stuffed": "Keyword Stuffing",
    "title_duplicate": "Duplicate Titles",
    "title_short": "Title Length",
    "meta_long": "Meta Description",
    "meta_missing": "Meta Description",
    "meta_short": "Meta Description",
    "meta_duplicate": "Meta Description",
    "h1_missing": "Missing H1",
    "h1_multiple": "Multiple H1",
    "h1_long": "H1 Tags",
    "h1_short": "H1 Tags",
    "h1_duplicate": "H1 Tags",
    "url_long": "URL Length",
    "thin_content": "Thin Content",
    "content_depth": "Content Depth",
    "near_duplicate": "Duplicate Content",
    "image_large": "Image Size",
    "high_carbon": "Page Weight",
    "deep_crawl": "Crawl Depth",
    "canonical_missing": "Canonical Tags",
    "spelling_grammar": "Spelling & Grammar",
    "poor_readability": "Readability",
    "lcp_high": "Page Speed",
    "lcp_medium": "Page Speed",
    "cls_high": "Layout Shift",
    "perf_low": "Page Speed",
    "perf_moderate": "Page Speed",
    "render_blocking": "Page Speed",
    "unoptimized_images": "Image Optimization",
    "structured_data": "Schema Markup",
    "render_blocked": "Rendering",
}

# key -> (priority, observation_template, impact)
# {ex} is replaced with the first example ("Eg: ...").
CATALOG = {
    "render_error": ("Critical",
        "Multiple pages found with rendering / JavaScript errors",
        "Pages may not get indexed."),
    "error_404": ("High",
        "Multiple pages found with 404 errors",
        "Dead links lose traffic and trust."),
    "error_5xx": ("High",
        "Multiple pages found returning server (5xx) errors",
        "Broken pages can't be indexed."),
    "redirects": ("Medium",
        "Multiple pages found served via redirects",
        "Extra hops slow the site and leak link equity."),
    "non_indexable": ("Medium",
        "Multiple pages found that are non-indexable",
        "These pages can't rank."),
    "title_long": ("High",
        "Multiple pages found with title tags that are too long",
        "Titles get cut off in search, lowering clicks."),
    "title_missing": ("High",
        "Multiple pages found with missing title tags",
        "No title means weak rankings."),
    "title_stuffed": ("High",
        "Multiple pages found with keyword-stuffed titles",
        "Looks spammy to Google."),
    "title_duplicate": ("Medium",
        "Multiple pages found sharing duplicate title tags",
        "Google can't tell which page to rank."),
    "title_short": ("Low",
        "Multiple pages found with very short title tags (under 30 characters)",
        "Title too thin to describe the page."),
    "meta_short": ("Low",
        "Multiple pages found with very short meta descriptions (under 70 characters)",
        "Snippet under-used, fewer clicks."),
    "meta_duplicate": ("Medium",
        "Multiple pages found sharing duplicate meta descriptions",
        "Pages look identical in search."),
    "h1_long": ("Low",
        "Multiple pages found with overly long H1 tags (over 70 characters)",
        "Weakens the main heading signal."),
    "h1_short": ("Low",
        "Multiple pages found with very short H1 tags (under 20 characters)",
        "Heading too vague to signal the topic."),
    "h1_duplicate": ("Medium",
        "Multiple pages found sharing duplicate H1 tags",
        "Blurs which page is most relevant."),
    "url_long": ("Low",
        "Multiple pages found with overly long URLs (over 115 characters)",
        "Hard to share and looks untrustworthy."),
    "meta_long": ("High",
        "Multiple pages found with meta descriptions that are too long",
        "Descriptions get cut off in search."),
    "meta_missing": ("High",
        "Multiple pages found with missing meta descriptions",
        "Google writes a weak snippet, lowering clicks."),
    "h1_missing": ("High",
        "Multiple pages found with missing H1 tags",
        "Google can't read the page topic."),
    "h1_multiple": ("Low",
        "Multiple pages found with more than one H1 tag",
        "Dilutes the page's main topic."),
    "thin_content": ("High",
        "Multiple pages found that are thin or low-value (under 300 words)",
        "Too little content to rank or convert."),
    "content_depth": ("High",
        "Multiple pages found with limited content depth, missing key informational sections",
        "Too shallow to rank or convert."),
    "near_duplicate": ("Medium",
        "Multiple pages found with near-duplicate content",
        "Duplicate content suppresses rankings."),
    "image_large": ("Medium",
        "Multiple pages found serving images over 100 KB",
        "Heavy images slow the page down."),
    "slow_response": ("Medium",
        "Multiple pages found with slow server response times",
        "Slow server makes the whole site feel slow."),
    "high_carbon": ("Low",
        "Multiple pages found with heavy page weight / poor carbon rating",
        "Heavy pages load slowly on mobile."),
    "deep_crawl": ("Low",
        "Multiple pages found buried deep in the site structure",
        "Buried pages get crawled less."),
    "canonical_missing": ("Medium",
        "Multiple pages found with missing canonical tags",
        "Google may index the wrong URL."),
    "spelling_grammar": ("Low",
        "Multiple pages found with spelling or grammar errors",
        "Errors lower perceived quality."),
    "poor_readability": ("Low",
        "Multiple pages found with poor readability scores",
        "Hard-to-read copy loses readers."),
    # PageSpeed-derived
    "lcp_high": ("High",
        "Multiple pages found with high Largest Contentful Paint (LCP)",
        "Slow load drops rankings and conversions."),
    "lcp_medium": ("Medium",
        "Multiple pages found with elevated Largest Contentful Paint (LCP)",
        "Slow load hurts user experience."),
    "cls_high": ("Medium",
        "Multiple pages found with high Cumulative Layout Shift (CLS)",
        "Page jumps as it loads, annoying users."),
    "perf_low": ("High",
        "Multiple pages found with low overall performance scores",
        "Slow pages rank lower and bounce more."),
    "perf_moderate": ("Medium",
        "Multiple pages found scoring below Google's recommended performance threshold (90)",
        "Below-target speed holds back rankings."),
    "render_blocking": ("Medium",
        "Multiple pages found with render-blocking resources",
        "Scripts delay the first paint."),
    "unoptimized_images": ("Medium",
        "Multiple pages found serving unoptimized / non-next-gen images",
        "Bloated images slow load times."),
    # Render-time (raw HTML / fetch-and-render)
    "structured_data": ("Medium",
        "Multiple pages found with no structured data (schema markup)",
        "Misses rich results in search."),
    "render_blocked": ("Critical",
        "Multiple pages found that do not render content without JavaScript",
        "Google may index an empty page."),
    # CRO (qualitative, benchmarked against the Gushwork build)
    "cro": ("High",
        None,  # observation text supplied per-item
        None),
}


# Friendly labels for the PageSpeed + render-time checks (Checks Passed tab).
PSI_CHECK_LABELS = {
    "lcp": "Largest Contentful Paint within target (PageSpeed)",
    "cls": "Cumulative Layout Shift within target — <0.25 (PageSpeed)",
    "perf": "Overall performance score at or above target — 90+ (PageSpeed)",
    "render_blocking": "No render-blocking resources (PageSpeed)",
    "unoptimized_images": "Images served in optimized / next-gen formats (PageSpeed)",
}
RENDER_CHECK_LABELS = {
    "structured_data": "Structured data (schema markup) present",
    "render_blocked": "Content renders for crawlers without JavaScript",
}


def build_rows(findings, psi_observations, extra_rows):
    rows = []
    notes = []
    for f in findings:
        key = f["key"]
        spec = CATALOG.get(key)
        if not spec or spec[0] is None:
            continue
        priority, obs, impact = spec
        rows.append(_row(obs, priority, impact, f))

    rows.extend(psi_observations)
    rows.extend(extra_rows or [])   # pre-built rows: render-time + CRO

    rows.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 9))
    return rows, notes


def render_rows(html_result):
    """Turn the html_checks result into observation rows + the keys that passed."""
    rows, passed = [], []
    if html_result.get("structured_data_absent"):
        spec = CATALOG["structured_data"]
        ex = next((p["url"] for p in html_result["pages"] if p.get("ok")), "")
        rows.append({"category": CATEGORY["structured_data"],
                     "observation": f"{spec[1]}\nEg: {ex}" if ex else spec[1],
                     "priority": spec[0], "impact": spec[2],
                     "reference": "Verify on validator.schema.org"})
    else:
        passed.append("structured_data")
    if html_result.get("render_blocked"):
        spec = CATALOG["render_blocked"]
        ex = html_result["render_blocked"][0]["url"]
        rows.append({"category": CATEGORY["render_blocked"],
                     "observation": f"{spec[1]}\nEg: {ex}", "priority": spec[0],
                     "impact": spec[2], "reference": "Verify on technicalseo.com/tools/fetch-render/"})
    elif html_result.get("render_ok"):
        passed.append("render_blocked")
    return rows, passed


def cro_rows(cro_items):
    """cro_items = list of {observation, impact}. All High priority CRO findings."""
    out = []
    for it in cro_items or []:
        out.append({"category": it.get("category", "CRO"), "observation": it["observation"],
                    "priority": "High", "impact": it["impact"], "reference": it.get("reference", "-")})
    return out


def build_passed_tab(fired_csv_keys, psi_passed, render_passed):
    """Compile the 'Checks Passed' tab: every parameter tested that came back clean."""
    from audit.sf_csv import CSV_CHECK_LABELS
    rows = []
    for key, label in CSV_CHECK_LABELS.items():
        if key not in fired_csv_keys:
            rows.append([label])
    for key in psi_passed:
        rows.append([PSI_CHECK_LABELS[key]])
    for key in render_passed:
        rows.append([RENDER_CHECK_LABELS[key]])
    return rows


def psi_status(psi_live):
    """Return (failed_keys, passed_keys) for the five PageSpeed checks."""
    failed = set()
    for r in psi_live.values():
        if not r or r.get("error"):
            continue
        if r.get("lcp_s") is not None and r["lcp_s"] >= 2.5:
            failed.add("lcp")
        if r.get("cls") is not None and r["cls"] > 0.25:
            failed.add("cls")
        if r.get("performance_score") is not None and r["performance_score"] < 90:
            failed.add("perf")
        opp = [t.lower() for t, _ in r.get("opportunities", [])]
        if any("render-block" in t or "render block" in t for t in opp):
            failed.add("render_blocking")
        if any("image" in t for t in opp):
            failed.add("unoptimized_images")
    ran = bool([r for r in psi_live.values() if r and not r.get("error")])
    passed = [k for k in PSI_CHECK_LABELS if ran and k not in failed]
    return failed, passed


def _row(obs, priority, impact, f):
    ex = f["examples"][0] if f.get("examples") else ""
    text = obs
    if ex:
        text = f"{obs}\nEg: {ex}"
    ref = "-"
    if f.get("evidence"):
        ref = f["evidence"][0]  # evidence tab name
    elif f.get("examples"):
        ref = "\n".join(f["examples"])
    return {"category": CATEGORY.get(f["key"], "General"), "observation": text,
            "priority": priority, "impact": impact, "reference": ref}


# ---- PageSpeed -> observations (deduped across page types) ----
def psi_to_observations(psi_live):
    """psi_live = {page_type: result}. Build observation rows, citing the worst page."""
    rows = []
    lcp, cls, perf, rb, img = [], [], [], [], []
    for r in psi_live.values():
        if not r or r.get("error"):
            continue
        url = r["url"]
        if r.get("lcp_s") is not None and r["lcp_s"] >= 2.5:
            lcp.append((url, r["lcp_s"]))
        if r.get("cls") is not None and r["cls"] > 0.25:
            cls.append((url, round(r["cls"], 2)))
        if r.get("performance_score") is not None and r["performance_score"] < 90:
            perf.append((url, r["performance_score"]))
        opp_titles = [t.lower() for t, _ in r.get("opportunities", [])]
        if any("render-block" in t or "render block" in t for t in opp_titles):
            rb.append(url)
        if any("image" in t for t in opp_titles):
            img.append(url)

    def add(key, ex):
        spec = CATALOG[key]
        rows.append({"category": CATEGORY.get(key, "Page Speed"),
                     "observation": f"{spec[1]}\nEg: {ex}" if ex else spec[1],
                     "priority": spec[0], "impact": spec[2], "reference": "-"})

    if lcp:
        u, v = max(lcp, key=lambda x: x[1])
        add("lcp_high" if v >= 4 else "lcp_medium", f"{u} ({v}s)")
    if cls:
        u, v = max(cls, key=lambda x: x[1])
        add("cls_high", f"{u} (CLS {v})")
    if perf:
        u, v = min(perf, key=lambda x: x[1])
        add("perf_low" if v < 50 else "perf_moderate", f"{u} (score {v}/100)")
    if rb:
        add("render_blocking", rb[0])
    if img:
        add("unoptimized_images", img[0])
    return rows
