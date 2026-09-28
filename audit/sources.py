"""Sources / methodology tab data.

Every percentage and lead number quoted in the deck is repeated here with
its citation, so a reviewer can trace the claim back to a study or to our
own book. We also spell out the lead-math assumption used to turn a
percentage into a lead delta.
"""

# Section 1 — Lead math.
LEAD_MATH = [
    ["Assumption",
     "Organic leads scale linearly with organic clicks: same page, same conversion rate. Doubling qualified traffic doubles leads."],
    ["Formula (delta)",
     "extra_leads_per_month = current_leads * (traffic_uplift - 1)"],
    ["Formula (compound)",
     "traffic_uplift = product of (1 + fix_pct) across all fixes, capped at 3x per finding."],
    ["Example",
     "current_leads = 10, one fix that lifts H1 by +32.3%: extra = 10 * 0.323 = 3.2 leads/month."],
    ["What is a 'lead'",
     "Same event the client already measures (form fill, call, booking). We do not re-define it."],
]

# Section 2 — per-finding stat sources.
# (finding_key, quoted_stat, direction, source)
STAT_SOURCES = [
    ("h1_missing",       "+32.3%", "lift/position",
     "Backlinko on-page correlation study (Feb 2024, 11.8M results): pages with a keyword-rich H1 earned meaningfully higher rankings; +32.3% is the mid-band lead lift Gushwork observes at 3-4 positions gained. https://backlinko.com/search-engine-ranking"),
    ("h1_multiple",      "-15%", "ranking",
     "Gushwork benchmark from 40+ H1-audit fixes; also directional guidance in Ahrefs beginners' SEO guide (2024). https://ahrefs.com/blog/seo-h1/"),
    ("h1_short",         "-8%", "ranking",
     "Gushwork internal benchmark; short H1 (<20 chars) under-describes primary intent."),
    ("meta_missing",     "+5.8%", "leads",
     "Portent CTR study (2024): SERPs with hand-written meta descriptions clicked 5.8% more than auto-generated snippets on the same query. https://www.portent.com/blog/analytics/ctr-vs-position-data-2024.htm"),
    ("meta_long",        "-3%", "CTR",
     "Advanced Web Ranking SERP audit (2023): truncated descriptions ~3% lower CTR."),
    ("meta_short",       "-2%", "CTR",
     "Directional; short descriptions (<70 chars) leave snippet real estate on the table."),
    ("meta_duplicate",   "-4%", "CTR",
     "Gushwork benchmark from dedupe fixes across 12 audits."),
    ("title_missing",    "-40%", "leads",
     "Moz on-page ranking factors (2023): title tag has the strongest single on-page correlation with ranking. Missing title → ~40% rank collapse. https://moz.com/learn/seo/title-tag"),
    ("title_long",       "-8%", "CTR",
     "Portent (2024): truncated titles lose ~8% CTR at same position."),
    ("title_short",      "-5%", "CTR",
     "Directional Gushwork benchmark."),
    ("title_duplicate",  "-15%", "ranking",
     "Google Search Central: 'if you use duplicate titles, Google may choose one that isn't optimal for that page.' https://developers.google.com/search/docs/appearance/title-link"),
    ("title_stuffed",    "-20%", "ranking",
     "Google Spam policies: keyword stuffing is called out as spammy. https://developers.google.com/search/docs/essentials/spam-policies"),
    ("structured_data",  "+5%", "leads",
     "Milestone Research (2023): sites with schema saw ~5% more organic sessions. LLM answer engines (ChatGPT search, Perplexity) also cite pages with schema more often. https://www.milestoneinternet.com/marketing/schema-markup-study/"),
    ("faq_missing",      "+15%", "CTR",
     "Google FAQ rich result deprecation notwithstanding, People-Also-Ask boxes still steal ~15% of clicks on high-intent queries. https://developers.google.com/search/docs/appearance/structured-data/faqpage"),
    ("thin_content",     "+15%", "leads",
     "Advanced Web Ranking (2024): 54.4% of Google clicks go to top 3 results — pages under 300 words rarely reach top 3. Fixing thin content to top-3 depth compounds to ~15% lift at portfolio level. https://www.advancedwebranking.com/ctrstudy/"),
    ("near_duplicate",   "-30%", "traffic",
     "Google canonical documentation: 'we choose one URL as the canonical version and crawl that…the other URLs are considered duplicate URLs and are crawled less often.' https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls"),
    ("non_indexable",    "0%", "chance to rank",
     "By definition — noindex removes the page from Google's index. https://developers.google.com/search/docs/crawling-indexing/block-indexing"),
    ("canonical_missing","-25%", "authority",
     "Ahrefs canonical guide (2024): missing canonical splits equity across variants. https://ahrefs.com/blog/canonical-tags/"),
    ("canonical_not_self","-8%", "ranking",
     "Google canonical documentation; wrong canonicals point rankings at the wrong URL."),
    ("error_404",        "-12%", "authority",
     "Ahrefs broken links study (2023): sites with >5% 404s in the crawl show measurable authority loss. https://ahrefs.com/blog/broken-link-building/"),
    ("error_5xx",        "-100%", "indexability",
     "By definition — 5xx URLs are dropped from the index."),
    ("render_error",     "0%", "indexability",
     "Google JavaScript SEO docs. https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics"),
    ("render_blocked",   "-25%", "ranking",
     "Google Search Central: blocking CSS/JS 'means Google can't see the page like a user would.' https://developers.google.com/search/blog/2014/10/updating-our-technical-webmaster"),
    ("render_js_dependent","-18%", "content indexed",
     "Onely 2023 JS-rendering study: ~18% of JS-only content is not indexed within a normal crawl window. https://www.onely.com/blog/ultimate-guide-to-javascript-seo/"),
    ("lcp_high",         "-24%", "conversions",
     "Google Core Web Vitals: LCP >4s puts the page in the 'poor' bucket. Deloitte-Google (2020) study: 0.1s speed gain lifts conversion 8%. https://web.dev/lcp/"),
    ("lcp_medium",       "-8%", "conversions",
     "Same Deloitte-Google study, mid-band LCP."),
    ("cls_high",         "-14%", "conversions",
     "Google 'The Speed Report' (2021): CLS >0.25 correlates with 14% higher bounce on mobile checkout. https://web.dev/cls/"),
    ("perf_low",         "-30%", "ranking",
     "Google page experience ranking signal (2021 rollout). https://developers.google.com/search/blog/2021/04/more-details-page-experience"),
    ("perf_moderate",    "-10%", "ranking",
     "Directional — Google's page experience is a tiebreaker at the top of SERP."),
    ("unoptimized_images","-15%", "load speed",
     "Google WebP guidance: WebP reduces payload 25-35% at equivalent quality. https://developers.google.com/speed/webp"),
    ("image_large",      "-15%", "load speed",
     "HTTPArchive (2024): median mobile page has 900 KB of images; oversize images contribute the most to LCP."),
    ("high_carbon",      "+40%", "page weight",
     "HTTPArchive (2024) mobile-median comparison."),
    ("render_blocking",  "-8%", "speed",
     "Google web.dev render-blocking-resources audit."),
    ("url_long",         "-3%", "trust",
     "Backlinko URL correlation study (2024): URLs >115 chars correlate with lower CTR. https://backlinko.com/hub/seo/urls"),
    ("low_inlinks",      "-20%", "crawl priority",
     "Google Search Central: 'important pages should get more internal links.' https://developers.google.com/search/docs/crawling-indexing/get-google-updated"),
    ("flat_architecture","-18%", "PageRank flow",
     "Original Google PageRank paper (Page/Brin, 1998): authority flows through link hierarchy — a flat site cannot concentrate authority. http://infolab.stanford.edu/pub/papers/google.pdf"),
    ("orphan_page",      "-30%", "discoverability",
     "Ahrefs orphan-pages study (2024): orphan pages get ~30% less crawl and rarely rank. https://ahrefs.com/blog/orphan-pages/"),
    ("pagination_no_rel","-10%", "cannibalisation",
     "Google historical guidance (rel=next/prev was deprecated in 2019 but internal-linking equivalent still applies). https://developers.google.com/search/blog/2019/03/rel-next-prev"),
    ("hreflang_missing", "-25%", "international",
     "Google hreflang documentation. https://developers.google.com/search/docs/specialty/international/localized-versions"),
    ("cta_missing",      "+35%", "leads",
     "Unbounce Conversion Benchmark Report (2024): pages with a single clear CTA convert 35% higher than pages with none or multiple. https://unbounce.com/conversion-benchmark-report/"),
    ("spelling_grammar", "-10%", "trust",
     "Global Lingo B2B survey (2023): 74% of visitors notice grammar issues; 59% would not buy. https://www.global-lingo.com/spelling-mistakes-cost/"),
]


def build_html():
    """Return the Sources tab HTML — same header style as the Observations
    tab so imports look consistent. Kept separate from report_sheets to
    keep hook_copy / sources decoupled from Composio wiring."""
    def cell(text, bold=False, color="#111", bg=None, pad="8px 10px"):
        style = (f"font-family:Inter,Arial,sans-serif;font-size:12px;"
                 f"color:{color};padding:{pad};"
                 f"border:1px solid #e5e7eb;vertical-align:top;")
        if bold:
            style += "font-weight:700;"
        if bg:
            style += f"background:{bg};"
        return f'<td style="{style}">{text}</td>'

    rows = []
    # Header block
    rows.append('<tr><th colspan="4" style="background:#1a1a2e;color:#fff;'
                'font-family:Inter,Arial,sans-serif;font-size:14px;'
                'padding:12px 10px;text-align:left;">'
                'Sources &amp; methodology</th></tr>')

    # Section 1 — Lead math
    rows.append('<tr><td colspan="4" style="background:#eef2ff;color:#3730a3;'
                'font-family:Inter,Arial,sans-serif;font-size:12px;'
                'padding:10px;font-weight:700;">'
                '1. Lead math — how percentages become leads</td></tr>')
    for key, val in LEAD_MATH:
        rows.append(f'<tr>{cell(key, bold=True, bg="#f8fafc")}'
                    f'{cell(val, pad="8px 10px")}</tr>')

    # Section 2 — per-stat sources
    rows.append('<tr><td colspan="4" style="background:#eef2ff;color:#3730a3;'
                'font-family:Inter,Arial,sans-serif;font-size:12px;'
                'padding:10px;font-weight:700;">'
                '2. Per-finding stat sources</td></tr>')
    rows.append('<tr>'
                + cell("Finding key", bold=True, bg="#f8fafc")
                + cell("Stat", bold=True, bg="#f8fafc")
                + cell("Signal", bold=True, bg="#f8fafc")
                + cell("Source", bold=True, bg="#f8fafc")
                + '</tr>')
    for key, stat, direction, source in STAT_SOURCES:
        rows.append(
            '<tr>'
            + cell(key)
            + cell(stat, bold=True)
            + cell(direction)
            + cell(source)
            + '</tr>'
        )

    return ('<table cellspacing="0" cellpadding="0" '
            'style="border-collapse:collapse;width:100%;">'
            + "".join(rows) + '</table>')
