"""Map raw findings -> Observation rows (Observation | Priority | Impact | Reference).

Copy is neutral and SEO-focused (pure problem list). Every observation is phrased
as "Multiple ... found" per house style, even for a single instance.
"""

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# key -> (priority, observation_template, impact)
# {ex} is replaced with the first example ("Eg: ...").
CATALOG = {
    "render_error": ("Critical",
        "Multiple pages found with rendering / JavaScript errors",
        "Critical pages may not be indexed, causing severe traffic and ranking loss."),
    "error_404": ("High",
        "Multiple pages found with 404 errors",
        "Users and search engines hit dead ends, resulting in lost traffic and authority."),
    "error_5xx": ("High",
        "Multiple pages found returning server (5xx) errors",
        "Server errors block indexing and break the user experience."),
    "redirects": ("Medium",
        "Multiple pages found served via redirects",
        "Redirect hops waste crawl budget, slow the site, and can leak link equity."),
    "non_indexable": ("Medium",
        "Multiple pages found that are non-indexable",
        "Non-indexable pages cannot rank, limiting organic visibility."),
    "title_long": ("High",
        "Multiple pages found with title tags that are too long",
        "Truncated titles in search results can reduce click-through and ranking."),
    "title_missing": ("High",
        "Multiple pages found with missing title tags",
        "Missing titles severely weaken relevance signals and rankings."),
    "title_stuffed": ("High",
        "Multiple pages found with keyword-stuffed titles",
        "Keyword stuffing looks spammy and can negatively impact ranking."),
    "title_duplicate": ("Medium",
        "Multiple pages found sharing duplicate title tags",
        "Duplicate titles confuse search engines about which page to rank."),
    "meta_long": ("High",
        "Multiple pages found with meta descriptions that are too long",
        "Over-length descriptions get truncated, hurting click-through rates."),
    "meta_missing": ("High",
        "Multiple pages found with missing or auto-generated meta descriptions",
        "Missing descriptions let search engines pick weak snippets, lowering CTR."),
    "h1_missing": ("High",
        "Multiple pages found with missing H1 tags",
        "Makes it harder for search engines to understand page topics and can limit ranking."),
    "h1_multiple": ("Low",
        "Multiple pages found with more than one H1 tag",
        "Multiple H1s dilute the page's primary topic signal."),
    "thin_content": ("High",
        "Multiple pages found that are thin or low-value (under 300 words)",
        "Thin pages struggle to rank for target keywords and convert visitors."),
    "content_depth": ("High",
        "Multiple pages found with limited content depth, missing key informational sections",
        "Pages may struggle to rank for target keywords and convert visitors."),
    "near_duplicate": ("Medium",
        "Multiple pages found with near-duplicate content",
        "Duplicate content dilutes authority and can suppress organic rankings."),
    "image_large": ("Medium",
        "Multiple pages found serving images over 100 KB",
        "Large images slow page speed and negatively impact Core Web Vitals."),
    "alt_text_skipped": (None, None, None),  # handled specially -> informational note
    "slow_response": ("Medium",
        "Multiple pages found with slow server response times",
        "Slow responses degrade page speed, rankings, and user experience."),
    "high_carbon": ("Low",
        "Multiple pages found with heavy page weight / poor carbon rating",
        "Heavy pages load slowly and hurt Core Web Vitals on mobile."),
    "deep_crawl": ("Low",
        "Multiple pages found buried deep in the site structure",
        "Deeply nested pages are crawled less often and pass less authority."),
    "canonical_missing": ("Medium",
        "Multiple pages found with missing canonical tags",
        "Without canonicals, search engines may index the wrong URL variants."),
    "spelling_grammar": ("Low",
        "Multiple pages found with spelling or grammar errors",
        "Errors reduce perceived quality and trust signals."),
    "poor_readability": ("Low",
        "Multiple pages found with poor readability scores",
        "Hard-to-read copy lowers engagement and dwell time."),
    # PageSpeed-derived
    "lcp_high": ("High",
        "Multiple pages found with high Largest Contentful Paint (LCP)",
        "Poor page speed can significantly reduce rankings, engagement, and conversions."),
    "lcp_medium": ("Medium",
        "Multiple pages found with elevated Largest Contentful Paint (LCP)",
        "Slow loading hurts user experience and can affect rankings."),
    "cls_high": ("Medium",
        "Multiple pages found with high Cumulative Layout Shift (CLS)",
        "Layout shifts frustrate users and harm Core Web Vitals scores."),
    "perf_low": ("High",
        "Multiple pages found with low overall performance scores",
        "Poor performance suppresses rankings and increases bounce rates."),
    "render_blocking": ("Medium",
        "Multiple pages found with render-blocking resources",
        "Render-blocking scripts and styles delay first paint and slow the page."),
    "unoptimized_images": ("Medium",
        "Multiple pages found serving unoptimized / non-next-gen images",
        "Unoptimized images inflate page weight and slow load times."),
    # Sitewide heuristics
    "structured_data": ("Medium",
        "Structured data (schema markup) not detected sitewide",
        "Search engines miss critical context, reducing visibility and rich-result opportunities."),
}


def build_rows(findings, psi_observations, sitewide):
    rows = []
    notes = []
    for f in findings:
        key = f["key"]
        if key == "alt_text_skipped":
            notes.append("Alt-text check skipped: requires the Screaming Frog 'Images' export "
                         "(internal_all does not contain alt attributes).")
            continue
        spec = CATALOG.get(key)
        if not spec or spec[0] is None:
            continue
        priority, obs, impact = spec
        rows.append(_row(obs, priority, impact, f))

    rows.extend(psi_observations)

    for key in sitewide:
        spec = CATALOG.get(key)
        if spec:
            rows.append({"observation": spec[1], "priority": spec[0],
                         "impact": spec[2], "reference": "-"})

    rows.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 9))
    return rows, notes


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
    return {"observation": text, "priority": priority, "impact": impact, "reference": ref}


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
        if r.get("performance_score") is not None and r["performance_score"] < 50:
            perf.append((url, r["performance_score"]))
        opp_titles = [t.lower() for t, _ in r.get("opportunities", [])]
        if any("render-block" in t or "render block" in t for t in opp_titles):
            rb.append(url)
        if any("image" in t for t in opp_titles):
            img.append(url)

    def add(key, ex):
        spec = CATALOG[key]
        rows.append({"observation": f"{spec[1]}\nEg: {ex}" if ex else spec[1],
                     "priority": spec[0], "impact": spec[2], "reference": "-"})

    if lcp:
        u, v = max(lcp, key=lambda x: x[1])
        add("lcp_high" if v >= 4 else "lcp_medium", f"{u} ({v}s)")
    if cls:
        u, v = max(cls, key=lambda x: x[1])
        add("cls_high", f"{u} (CLS {v})")
    if perf:
        u, v = min(perf, key=lambda x: x[1])
        add("perf_low", f"{u} (score {v}/100)")
    if rb:
        add("render_blocking", rb[0])
    if img:
        add("unoptimized_images", img[0])
    return rows
