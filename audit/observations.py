"""Map raw findings -> Observation rows (Observation | Priority | Impact | Reference).

Copy is neutral and SEO-focused (pure problem list). Every observation is phrased
as "Multiple ... found" per house style, even for a single instance.
"""

PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# Short 2-3 word header/category for each observation (shown as the first column).
CATEGORY = {
    "render_error": "Rendering",
    "error_404": "Broken Links",
    "error_404_money": "404s on Money Pages",
    "error_5xx": "Server Errors",
    "non_indexable": "Indexability",
    "title_long": "Title Length",
    "title_missing": "Missing Titles",
    "title_stuffed": "Keyword Stuffing",
    "title_duplicate": "Duplicate Titles",
    "title_short": "Title Length",
    "meta_long": "Meta Description",
    "meta_missing": "Meta Description",
    "meta_short": "Meta Description",
    "meta_fragment": "Meta Description",
    "placeholder_urls": "Indexability",
    "http_www_redirect_missing": "Site Infrastructure",
    "viewport_pinch_zoom_blocked": "Mobile UX",
    "dead_nav_links": "Navigation",
    "meta_duplicate": "Meta Description",
    "h1_missing": "Missing H1",
    "h1_multiple": "Multiple H1",
    "h1_long": "H1 Tags",
    "h1_short": "H1 Tags",
    "h1_duplicate": "H1 Tags",
    "url_long": "URL Length",
    "thin_content": "Thin Content",
    "near_duplicate": "Duplicate Content",
    "image_large": "Image Size",
    "high_carbon": "Page Weight",
    "canonical_missing": "Canonical Tags",
    "canonical_not_self": "Canonical Tags",
    "spelling_grammar": "Spelling & Grammar",
    "lcp_high": "Page Speed",
    "lcp_medium": "Page Speed",
    "cls_high": "Layout Shift",
    "perf_low": "Page Speed",
    "perf_moderate": "Page Speed",
    "render_blocking": "Page Speed",
    "unoptimized_images": "Image Optimization",
    "structured_data": "Schema Markup",
    "render_blocked": "Rendering",
    "render_js_dependent": "Rendering",
    "title_multiple_tags": "Multiple Titles",
    "meta_multiple_tags": "Multiple Meta",
    "pagination_no_rel": "Pagination",
    "low_inlinks": "Internal Linking",
    "og_missing": "Social / OG Tags",
    "hreflang_missing": "Hreflang",
    "faq_missing": "FAQ / Schema",
    "cta_missing": "CRO / CTA",
}

# key -> (priority, observation_template, impact)
# {ex} is replaced with the first example ("Eg: ...").
CATALOG = {
    "render_error": ("Critical",
        "Render / JavaScript errors on these pages — Google can't see them",
        "Broken pages drop out of the index. No index, no traffic, no leads."),
    "error_404": ("High",
        "These URLs return 404",
        "Dead links leak authority and cost the traffic those pages used to send."),
    "error_404_money": ("High",
        "Money pages returning 404 — visitors hit these and bounce",
        "Broken commercial pages kill conversions and Google drops the URL from search."),
    "error_5xx": ("High",
        "Server (5xx) errors on these URLs",
        "Google skips 5xx pages and users see a broken site."),
    "redirects": ("Medium",
        "These URLs served via redirects",
        "Redirect hops waste crawl budget and leak link equity."),
    "non_indexable": ("High",
        "These pages have a noindex directive — invisible to Google",
        "Noindex pages can't rank. If they should rank, this is a straight lead loss."),
    "title_long": ("High",
        "Title tags run past the ~65-char SERP limit and get truncated",
        "Truncated titles lose the tail keyword and read incomplete in search — click-through drops."),
    "title_missing": ("Critical",
        "These pages have no title tag",
        "No title = Google picks the H1 or filename. The strongest ranking signal on the page is empty."),
    "title_stuffed": ("High",
        "Titles stuffed with keywords / separators",
        "Keyword-stuffed titles look spammy in the SERP and Google can flag them as manipulative."),
    "title_duplicate": ("Medium",
        "These pages share duplicate title tags",
        "Duplicate titles confuse Google about which page to rank — usually only one of them wins."),
    "title_duplicate_sitewide": ("Critical",
        "Every page carries the same title as the homepage",
        "Only the homepage can rank — every other page competes with itself for the same title, so About / Services / Contact never win non-branded search."),
    "title_short": ("Low",
        "Titles under 30 characters — under-using SERP space",
        "Short titles miss keyword real estate and read as generic."),
    "meta_short": ("Low",
        "Meta descriptions between 30-70 chars — under-using the snippet",
        "Short descriptions waste snippet space and drop click-through."),
    "meta_fragment": ("Medium",
        "Meta descriptions under 30 chars — essentially a stub",
        "Fragment metas leave the snippet empty and Google auto-generates a poor one."),
    "placeholder_urls": ("Medium",
        "Placeholder URL slugs live in the sitemap (WordPress /12345-2/, /sample-page/, /uncategorized/)",
        "Unedited slugs live in the index and dilute topical authority."),
    "meta_duplicate": ("Medium",
        "These pages share duplicate meta descriptions",
        "Same snippet across multiple pages — Google picks one and hides the rest."),
    "h1_long": ("Low",
        "H1 tags over 70 characters",
        "Overly long H1s dilute the primary heading signal."),
    "h1_short": ("Low",
        "H1 tags under 20 characters",
        "Very short H1s under-describe the page and weaken on-page relevance."),
    "h1_duplicate": ("Medium",
        "These pages share duplicate H1 tags",
        "Duplicate H1s blur which page owns which topic."),
    "url_long": ("Low",
        "URLs over 115 characters — truncated in SERP",
        "Long URLs read as spammy and lose click-through."),
    "meta_long": ("High",
        "Meta descriptions over 200 characters — truncated in the SERP",
        "The end of your snippet gets cut off, dropping click-through."),
    "meta_missing": ("High",
        "These pages have no meta description",
        "No meta = Google writes its own snippet, usually a weaker one. Click-through drops."),
    "h1_missing": ("Critical",
        "These pages have no H1 tag",
        "No H1 = Google has no primary heading to read the page's topic from. Rankings drop and leads with them."),
    "h1_multiple": ("Low",
        "These pages have more than one H1 tag",
        "Competing H1s dilute the page's primary topic signal."),
    "thin_content": ("Critical",
        "These pages have under 300 words",
        "Thin pages struggle to rank for target keywords and rarely reach top-3 — where the clicks live."),
    "content_depth": ("High",
        "Multiple pages found with limited content depth, missing key informational sections",
        "Shallow pages struggle to rank for target keywords and convert visitors."),
    "near_duplicate": ("Medium",
        "Multiple pages found with near-duplicate content",
        "Duplicate content dilutes authority and can suppress rankings."),
    "image_large": ("Medium",
        "Multiple pages found serving images over 100 KB",
        "Large images slow page speed and hurt Core Web Vitals."),
    "slow_response": ("Medium",
        "Multiple pages found with slow server response times",
        "Slow responses degrade page speed and user experience."),
    "high_carbon": ("Low",
        "Multiple pages found with heavy page weight / poor carbon rating",
        "Heavy pages load slowly and hurt Core Web Vitals on mobile."),
    "deep_crawl": ("Low",
        "Multiple pages found buried deep in the site structure",
        "Deeply nested pages are crawled less often and pass less authority."),
    "canonical_missing": ("Medium",
        "These pages have no canonical tag",
        "Without a canonical, Google may index the wrong URL or split ranking between duplicates."),
    "canonical_not_self": ("High",
        "Canonical tag points to a different URL — page is signalling 'don't index me'",
        "A non-self-referencing canonical tells Google to ignore this page and rank the target instead — effectively de-indexes it."),
    "spelling_grammar": ("Low",
        "Multiple pages found with spelling or grammar errors",
        "Errors reduce perceived quality and trust."),
    "poor_readability": ("Low",
        "Multiple pages found with poor readability scores",
        "Hard-to-read copy lowers engagement and dwell time."),
    # PageSpeed-derived
    "lcp_high": ("Critical",
        "Largest Contentful Paint over 4s on these pages",
        "Slow LCP tanks user experience and Google demotes slow pages on mobile."),
    "lcp_medium": ("Medium",
        "LCP between 2.5s and 4s — needs improvement",
        "Borderline speed puts you behind faster competitors in the mobile SERP."),
    "cls_high": ("High",
        "Cumulative Layout Shift above 0.1 — buttons move under the click",
        "Layout shifts cause mis-clicks and bounce, and Google demotes pages with high CLS."),
    "perf_low": ("High",
        "Lighthouse performance under 50 on these pages",
        "Poor performance is a direct Google mobile ranking signal — users bounce before conversion."),
    "perf_moderate": ("Medium",
        "Performance in the 50-89 band — below Google's recommended 90+",
        "Below-target page speed holds rankings back."),
    "render_blocking": ("Critical",
        "Render-blocking resources on these pages — first paint is delayed",
        "Every 200ms of blocked render is a percentage of visitors leaving before the page loads."),
    "unoptimized_images": ("Medium",
        "Multiple pages found serving unoptimized / non-next-gen images",
        "Unoptimized images inflate page weight and slow load times."),
    # Render-time (raw HTML / fetch-and-render)
    "structured_data": ("High",
        "These pages ship no schema markup",
        "No schema = no rich results in Google and no context for LLMs (ChatGPT / Perplexity). Searchers pick someone else."),
    "render_blocked": ("Critical",
        "These pages don't render without JavaScript — critical resources blocked",
        "Blocked resources leave Google looking at an empty page. Rankings drop, leads with them."),
    "render_js_dependent": ("Critical",
        "Page content only builds when JavaScript runs — no server-rendered HTML",
        "Google's crawlers see an empty page and skip it. If the JS fails to execute, the page vanishes from search."),
    "title_multiple_tags": ("Medium",
        "Multiple pages found with more than one <title> tag",
        "Multiple title tags confuse search engines about the page title."),
    "meta_multiple_tags": ("Low",
        "Multiple pages found with more than one meta description tag",
        "Duplicate meta tags send mixed signals about the snippet."),
    "pagination_no_rel": ("Medium",
        "Multiple paginated pages found missing rel=prev/next signals",
        "Without rel pagination signals, search engines may not correctly consolidate paginated series."),
    "low_inlinks": ("Medium",
        "Multiple pages found with very few internal links pointing to them",
        "Pages with 0-1 inlinks are effectively orphaned — search engines rarely discover or prioritise them."),
    "og_missing": ("Medium",
        "Multiple pages found missing Open Graph tags (og:image, og:title, og:description)",
        "Missing OG tags cause social shares to appear with no image or preview, reducing click-through from social media."),
    "hreflang_missing": ("High",
        "Multiple language variants found without hreflang tags",
        "Without hreflang, Google cannot serve the correct language version to users, diluting rankings across locales."),
    "faq_missing": ("Medium",
        "Multiple service / product pages found without an FAQ section or FAQPage schema",
        "FAQ sections with schema markup unlock FAQ rich results in search, increasing click-through and answering buyer objections."),
    "cta_missing": ("Critical",
        "Multiple pages found with no CTA above the fold on mobile",
        "No visible call-to-action in the mobile hero means visitors leaving without enquiring — the single biggest CRO loss for a lead-gen site."),
    # CRO (qualitative, benchmarked against the Gushwork build)
    "cro": ("High",
        None,  # observation text supplied per-item
        None),
}


# Friendly labels for the PageSpeed + render-time checks (Checks Passed tab).
PSI_CHECK_LABELS = {
    "lcp": "Largest Contentful Paint within target (PageSpeed)",
    "cls": "Cumulative Layout Shift within target : <0.25 (PageSpeed)",
    "perf": "Overall performance score at or above target : 90+ (PageSpeed)",
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
        if f.get("suppress"):
            continue  # evidence-only (e.g. redirects), not raised as observation
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
    gaps = html_result.get("schema_gaps") or []
    if gaps:
        spec = CATALOG["structured_data"]
        # one example per page type, naming the schema that type should have
        ex_lines = [f"{g['type']}: {g['url']} (missing {g['expected']} schema)" for g in gaps]
        rows.append({"category": CATEGORY["structured_data"],
                     "observation": f"{spec[1]}\nEg: {ex_lines[0]}",
                     "priority": spec[0], "impact": spec[2],
                     "reference": "Validate: https://validator.schema.org/\n" + "\n".join(ex_lines)})
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


def psi_all_errored(psi_live):
    """True if every PSI response contains an error (rate limit, timeout)."""
    if not psi_live:
        return True
    return all((not r) or r.get("error") for r in psi_live.values())


def psi_status(psi_live):
    """Return (failed_keys, passed_keys) for the five PageSpeed checks."""
    failed = set()
    for r in psi_live.values():
        if not r or r.get("error"):
            continue
        if r.get("lcp_s") is not None and r["lcp_s"] >= 2.5:
            failed.add("lcp")
        if r.get("cls") is not None and r["cls"] > 0.1:
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
    return {"key": f["key"], "count": f.get("count", 0),
            "category": CATEGORY.get(f["key"], "General"), "observation": text,
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
        if r.get("cls") is not None and r["cls"] > 0.1:
            cls.append((url, round(r["cls"], 2)))
        if r.get("performance_score") is not None and r["performance_score"] < 90:
            perf.append((url, r["performance_score"]))
        opp_titles = [t.lower() for t, _ in r.get("opportunities", [])]
        if any("render-block" in t or "render block" in t for t in opp_titles):
            rb.append(url)
        if any("image" in t for t in opp_titles):
            img.append(url)

    def add(key, ex, urls=None):
        spec = CATALOG[key]
        ref = "\n".join(urls) if urls else "-"
        rows.append({"key": key,
                     "category": CATEGORY.get(key, "Page Speed"),
                     "observation": f"{spec[1]}\nEg: {ex}" if ex else spec[1],
                     "priority": spec[0], "impact": spec[2],
                     "reference": ref})

    if lcp:
        # Split into two disjoint buckets — high (>=4s) vs medium (2.5-4s) —
        # and emit each as its own finding so a page with LCP 3.0s never
        # lands under a 'LCP > 4s' slide. Sort worst-first within each bucket.
        high_bucket   = sorted([(u, v) for u, v in lcp if v >= 4],   key=lambda x: -x[1])
        medium_bucket = sorted([(u, v) for u, v in lcp if v < 4],    key=lambda x: -x[1])
        if high_bucket:
            u, v = high_bucket[0]
            urls_with_stat = [f"{url}||LABEL=LCP {sec}s" for url, sec in high_bucket]
            add("lcp_high", f"{u} ({v}s)", urls=urls_with_stat)
        if medium_bucket:
            u, v = medium_bucket[0]
            urls_with_stat = [f"{url}||LABEL=LCP {sec}s" for url, sec in medium_bucket]
            add("lcp_medium", f"{u} ({v}s)", urls=urls_with_stat)
    if cls:
        u, v = max(cls, key=lambda x: x[1])
        add("cls_high", f"{u} (CLS {v})", urls=[x[0] for x in cls])
    if perf:
        u, v = min(perf, key=lambda x: x[1])
        add("perf_low" if v < 50 else "perf_moderate",
            f"{u} (score {v}/100)", urls=[x[0] for x in perf])
    if rb:
        add("render_blocking", rb[0], urls=rb)
    if img:
        add("unoptimized_images", img[0], urls=img)
    return rows
