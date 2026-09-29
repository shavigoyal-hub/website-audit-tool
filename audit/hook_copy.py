"""PDF-matched Hook Stat / Hook Context / What It Costs You copy per finding.

Structure mirrors the Arizona Home Grants reference deck:
  hook_stat:  a big number (e.g. "+32.3%", "54.4%", "0%")
  hook_ctx:   short subtitle stating what the number MEANS
  costs:      1-sentence business consequence
  support:    optional supporting stat that reinforces the loss

Keyed by the observation `key` from observations.py CATALOG.
"""

# One-liner per-URL status label + a color hint (used for the pill).
# color: 'critical' | 'high' | 'medium' | 'low' | 'ok'
STATUS_LABEL = {
    "h1_missing":       ("No H1", "critical"),
    "h1_multiple":      ("Competing H1s", "high"),
    "h1_short":         ("Short H1", "low"),
    "meta_missing":     ("Missing", "high"),
    "meta_long":        ("Too long", "medium"),
    "meta_short":       ("Too short", "low"),
    "meta_duplicate":   ("Duplicate", "medium"),
    "title_missing":    ("Missing title", "critical"),
    "title_long":       ("Truncated", "high"),
    "title_short":      ("Too short", "low"),
    "title_duplicate":  ("Duplicate title", "medium"),
    "title_stuffed":    ("Keyword stuffed", "high"),
    "structured_data":  ("No schema", "high"),
    "faq_missing":      ("No FAQ", "medium"),
    "thin_content":     ("Thin", "high"),
    "near_duplicate":   ("Near-duplicate", "high"),
    "non_indexable":    ("Noindex", "critical"),
    "canonical_missing":("No canonical", "medium"),
    "canonical_not_self":("Wrong canonical", "medium"),
    "error_404":        ("404", "high"),
    "error_404_money":  ("404 (money page)", "critical"),
    "error_5xx":        ("5xx", "critical"),
    "render_error":     ("Render error", "critical"),
    "render_blocked":   ("Blocked resource", "high"),
    "render_js_dependent":("JS-only", "high"),
    "lcp_high":         ("LCP > 4s", "critical"),
    "lcp_medium":       ("LCP 2.5-4s", "medium"),
    "cls_high":         ("CLS high", "high"),
    "perf_low":         ("Perf < 50", "critical"),
    "perf_moderate":    ("Perf 50-89", "medium"),
    "unoptimized_images":("Heavy images", "medium"),
    "image_large":      ("Oversized", "medium"),
    "high_carbon":      ("Heavy page", "medium"),
    "render_blocking":  ("Render blocking", "medium"),
    "url_long":         ("Long URL", "low"),
    "low_inlinks":      ("Few inlinks", "medium"),
    "flat_architecture":("Flat structure", "critical"),
    "nav_missing":      ("No top menu", "critical"),
    "about_missing":    ("No About page", "high"),
    "hub_subdomain":    ("Hub on subdomain", "high"),
    "orphan_page":      ("Orphan", "high"),
    "schema_product_missing": ("No product schema", "high"),
    "schema_article_missing": ("No Article schema", "medium"),
    "schema_local_missing":   ("No LocalBusiness schema", "high"),
    "pagination_no_rel":("No rel pagination", "low"),
    "hreflang_missing": ("No hreflang", "high"),
    "cta_missing":      ("No CTA", "high"),
    "spelling_grammar": ("Errors", "low"),
}


# ── Hint → canonical finding key ────────────────────────────────────────
# Maps free-text phrases the user types in the chatbot to the observation
# key whose canonical copy we should reuse. Match is case-insensitive
# substring — longest phrase wins.
HINT_ALIASES = {
    "flat architecture":       "flat_architecture",
    "flat site":               "flat_architecture",
    "flat structure":          "flat_architecture",
    "no top menu":             "nav_missing",
    "no top nav":              "nav_missing",
    "no navigation":           "nav_missing",
    "top menu missing":        "nav_missing",
    "no about":                "about_missing",
    "no about page":           "about_missing",
    "no about us":             "about_missing",
    "missing about":           "about_missing",
    "content hub subdomain":   "hub_subdomain",
    "hub on subdomain":        "hub_subdomain",
    "blog on subdomain":       "hub_subdomain",
    "separate subdomain":      "hub_subdomain",
    "orphan":                  "orphan_page",
    "no internal links":       "low_inlinks",
    "few internal links":      "low_inlinks",
    "thin content":            "thin_content",
    "duplicate content":       "near_duplicate",
    "no h1":                   "h1_missing",
    "missing h1":              "h1_missing",
    "multiple h1":             "h1_multiple",
    "short h1":                "h1_short",
    "no meta":                 "meta_missing",
    "missing meta":            "meta_missing",
    "no title":                "title_missing",
    "missing title":           "title_missing",
    "duplicate title":         "title_duplicate",
    "keyword stuff":           "title_stuffed",
    "no schema":               "structured_data",
    "no structured data":      "structured_data",
    "no faq":                  "faq_missing",
    "noindex":                 "non_indexable",
    "no canonical":            "canonical_missing",
    "wrong canonical":         "canonical_not_self",
    "404":                     "error_404",
    "server error":            "error_5xx",
    "render":                  "render_error",
    "js dependent":            "render_js_dependent",
    "slow":                    "lcp_high",
    "lcp":                     "lcp_high",
    "layout shift":            "cls_high",
    "cls":                     "cls_high",
    "heavy image":             "unoptimized_images",
    "large image":             "image_large",
    "long url":                "url_long",
    "no cta":                  "cta_missing",
    "missing cta":             "cta_missing",
    "no hreflang":             "hreflang_missing",
    "spelling":                "spelling_grammar",
    "grammar":                 "spelling_grammar",
}


HOOK_COPY = {
    # ── H1 tags ────────────────────────────────────────────────────────────
    "h1_missing": {
        "hook_stat": "+15%",
        "hook_ctx":  "more leads when key pages have a proper H1. Pages with no H1 give Google no topic to rank for.",
        "costs":     "Missing H1s give Google no topic to rank the page for, directly hurting rankings and leads.",
        "support":   "Backlinko on-page correlation study: pages with a keyword-rich H1 rank higher.",
    },
    "h1_multiple": {
        "hook_stat": "-15%",
        "hook_ctx":  "ranking dilution when multiple H1s compete on one page.",
        "costs":     "Competing H1s blur which topic the page is about, and Google picks the weaker one.",
        "support":   "",
    },
    "h1_short": {
        "hook_stat": "-8%",
        "hook_ctx":  "Google ranking impact when H1s are too short to describe the page.",
        "costs":     "Short H1s under-describe the page and weaken Google's ranking signal for it.",
        "support":   "",
    },
    # ── Meta descriptions ─────────────────────────────────────────────────
    "meta_missing": {
        "hook_stat": "+5.8%",
        "hook_ctx":  "more leads with a meta description. You have none on the pages that matter.",
        "costs":     "Google writes your snippet — and picks the wrong sentence. On a decision-heavy site, that snippet decides who trusts you enough to click.",
        "support":   "",
    },
    "meta_long": {
        "hook_stat": "-3%",
        "hook_ctx":  "CTR loss from truncated descriptions in search.",
        "costs":     "Over-length descriptions get cut mid-sentence, hurting click-through.",
        "support":   "",
    },
    "meta_short": {
        "hook_stat": "-2%",
        "hook_ctx":  "snippet space wasted on descriptions under 70 chars.",
        "costs":     "Short descriptions under-use the snippet and lower click-through.",
        "support":   "",
    },
    "meta_duplicate": {
        "hook_stat": "-4%",
        "hook_ctx":  "snippet dilution from duplicate descriptions.",
        "costs":     "Duplicate descriptions weaken snippet relevance across pages.",
        "support":   "",
    },
    # ── Title tags ────────────────────────────────────────────────────────
    "title_missing": {
        "hook_stat": "-35%",
        "hook_ctx":  "leads lost when the title tag is missing. It's Google's #1 on-page ranking signal.",
        "costs":     "Missing titles severely weaken relevance signals, rankings and leads.",
        "support":   "Moz on-page factors: title tag is the strongest single on-page correlation with ranking.",
    },
    "title_long": {
        "hook_stat": "-3%",
        "hook_ctx":  "CTR loss when titles get truncated in the SERP.",
        "costs":     "Truncated titles in search reduce click-through and rankings.",
        "support":   "Portent CTR study (2024): truncated titles lose about 3% CTR at same position.",
    },
    "title_short": {
        "hook_stat": "-3%",
        "hook_ctx":  "SERP space wasted on titles under 30 chars.",
        "costs":     "Short titles under-describe the page and waste SERP space.",
        "support":   "Directional benchmark based on SERP-CTR studies.",
    },
    "title_duplicate": {
        "hook_stat": "-5%",
        "hook_ctx":  "ranking risk from duplicate titles. Google picks one page and hides the rest.",
        "costs":     "Duplicate titles confuse Google about which page to rank, so none of them rank well.",
        "support":   "Google Search Central: duplicate titles cause Google to pick a non-optimal one.",
    },
    "title_stuffed": {
        "hook_stat": "-5%",
        "hook_ctx":  "trust loss from keyword-stuffed titles.",
        "costs":     "Keyword stuffing looks spammy and can hurt rankings.",
        "support":   "Google spam policies flag keyword stuffing as a violation.",
    },
    # ── Schema / structured data ─────────────────────────────────────────
    "structured_data": {
        "hook_stat": "+5%",
        "hook_ctx":  "more leads with structured data. You have none.",
        "costs":     "No rich results on Google and no signal for LLMs like ChatGPT or Perplexity. Searchers pick someone else.",
        "support":   "+82% CTR for rich results. +35% more visits with search features on.",
    },
    "faq_missing": {
        "hook_stat": "+5%",
        "hook_ctx":  "click-through when FAQ answers show under your listing.",
        "costs":     "You lose People-Also-Ask real estate to competitors who mark up their answers.",
        "support":   "Google PAA carousel drives approx 5% CTR uplift on match; source: Semrush 2024 SERP study.",
    },
    "schema_product_missing": {
        "hook_stat": "+5%",
        "hook_ctx":  "more leads on money pages with Product / Service / SoftwareApplication schema.",
        "costs":     "Without schema on product/service pages, Google can't render rich results and LLMs miss key context.",
        "support":   "Milestone Research: sites with Product/Service schema saw ~5% more organic sessions.",
    },
    "schema_article_missing": {
        "hook_stat": "+5%",
        "hook_ctx":  "more organic traffic on articles with Article / BlogPosting schema.",
        "costs":     "Missing Article schema hides author, publish date and rich snippets in search and news.",
        "support":   "Google structured data docs: Article markup is required for Top Stories eligibility.",
    },
    "schema_local_missing": {
        "hook_stat": "+5%",
        "hook_ctx":  "more local visibility with LocalBusiness schema on the contact and location pages.",
        "costs":     "Without LocalBusiness schema, Google may not attach your business to map pack results.",
        "support":   "Google Business Profile ranking factors 2024: LocalBusiness JSON-LD strengthens local pack.",
    },
    # ── Content depth ────────────────────────────────────────────────────
    "thin_content": {
        "hook_stat": "+25%",
        "hook_ctx":  "more leads once thin pages get real depth. Top-3 clicks go to pages with substance.",
        "costs":     "Money-decision pages don't earn enough trust to rank if they're thin, so they don't drive leads.",
        "support":   "AWR 2024: 54.4% of Google clicks go to top-3 — thin pages rarely reach top-3.",
    },
    "near_duplicate": {
        "hook_stat": "-30%",
        "hook_ctx":  "traffic loss when Google collapses duplicate content into one URL.",
        "costs":     "Duplicate pages cannibalise each other — none of them ranks strongly.",
        "support":   "",
    },
    # ── Indexability ─────────────────────────────────────────────────────
    "non_indexable": {
        "hook_stat": "0%",
        "hook_ctx":  "chance to rank — noindex pages are invisible to Google.",
        "costs":     "Pages with noindex cannot rank and are invisible to organic traffic.",
        "support":   "",
    },
    "canonical_missing": {
        "hook_stat": "-25%",
        "hook_ctx":  "authority leaked when there is no canonical tag.",
        "costs":     "Google may index the wrong URL variant and split link equity across duplicates.",
        "support":   "",
    },
    "canonical_not_self": {
        "hook_stat": "-8%",
        "hook_ctx":  "risk of ranking the wrong URL when canonicals don't self-reference.",
        "costs":     "Incorrect canonicals point Google at the wrong page for the topic.",
        "support":   "",
    },
    # ── Errors / crawlability ────────────────────────────────────────────
    "error_404": {
        "hook_stat": "-12%",
        "hook_ctx":  "authority lost through dead links and 404s.",
        "costs":     "Dead links lose traffic and dilute site authority.",
        "support":   "",
    },
    "error_404_money": {
        "hook_stat": "-40%",
        "hook_ctx":  "lost leads when money pages 404. Visitors bounce, Google drops the URL.",
        "costs":     "Broken product, service, or checkout pages kill conversions and let Google demote the URL.",
        "support":   "",
    },
    "error_5xx": {
        "hook_stat": "-100%",
        "hook_ctx":  "indexability on pages returning server errors.",
        "costs":     "Server errors block indexing and break the user experience.",
        "support":   "",
    },
    "render_error": {
        "hook_stat": "0%",
        "hook_ctx":  "of these pages will make it into Google's index.",
        "costs":     "Rendering / JS errors mean affected pages may not be indexed at all.",
        "support":   "",
    },
    "render_blocked": {
        "hook_stat": "-25%",
        "hook_ctx":  "rankings when critical resources are blocked from crawl.",
        "costs":     "Blocked resources stop Google from seeing what the page really shows.",
        "support":   "",
    },
    "render_js_dependent": {
        "hook_stat": "-18%",
        "hook_ctx":  "content lost when it only exists after JavaScript runs.",
        "costs":     "JS-dependent content is indexed slower — and sometimes not at all.",
        "support":   "",
    },
    # ── Speed / Core Web Vitals ─────────────────────────────────────────
    "lcp_high": {
        "hook_stat": "-24%",
        "hook_ctx":  "lost rankings and leads when LCP is above 4 seconds. Slow pages don't rank on mobile.",
        "costs":     "Slow load kills the click before the page ever loads, and Google pushes slow pages down on mobile.",
        "support":   "53% of mobile visits leave if a page takes >3s.",
    },
    "lcp_medium": {
        "hook_stat": "-8%",
        "hook_ctx":  "conversions when LCP is between 2.5s and 4s.",
        "costs":     "Borderline speed puts you behind faster competitors in the SERP.",
        "support":   "",
    },
    "cls_high": {
        "hook_stat": "-14%",
        "hook_ctx":  "conversions when layout shifts move buttons under the click.",
        "costs":     "Layout shift makes users mis-click and bounce.",
        "support":   "",
    },
    "perf_low": {
        "hook_stat": "-30%",
        "hook_ctx":  "ranking on mobile when Lighthouse performance is under 50.",
        "costs":     "Poor performance is a direct Google mobile ranking signal.",
        "support":   "",
    },
    "perf_moderate": {
        "hook_stat": "-10%",
        "hook_ctx":  "when performance is stuck in the 50-89 band.",
        "costs":     "Passable is not competitive — the top 3 all score 90+.",
        "support":   "",
    },
    "unoptimized_images": {
        "hook_stat": "-15%",
        "hook_ctx":  "load speed lost to unoptimised images.",
        "costs":     "Heavy images push LCP over the limit and hurt Core Web Vitals.",
        "support":   "",
    },
    "image_large": {
        "hook_stat": "-15%",
        "hook_ctx":  "load speed when images ship at full resolution.",
        "costs":     "Oversized images dominate page weight and slow first paint.",
        "support":   "",
    },
    "high_carbon": {
        "hook_stat": "+40%",
        "hook_ctx":  "page weight vs the mobile median. Slow to load, slow to rank.",
        "costs":     "Heavy pages fail Core Web Vitals and lose mobile ranking.",
        "support":   "",
    },
    "render_blocking": {
        "hook_stat": "-8%",
        "hook_ctx":  "speed loss from render-blocking scripts/styles.",
        "costs":     "Render-blocking resources delay the first meaningful paint.",
        "support":   "",
    },
    # ── URL / internal linking ────────────────────────────────────────────
    "url_long": {
        "hook_stat": "-3%",
        "hook_ctx":  "trust from URLs above 115 characters.",
        "costs":     "Long URLs are harder to share and look less trustworthy in the SERP.",
        "support":   "",
    },
    "low_inlinks": {
        "hook_stat": "-20%",
        "hook_ctx":  "crawl priority for pages with very few internal links.",
        "costs":     "Google under-values pages nothing else on the site links to.",
        "support":   "",
    },
    "flat_architecture": {
        "hook_stat": "-18%",
        "hook_ctx":  "PageRank flow when every page sits at the same depth from the homepage.",
        "costs":     "A flat structure gives every page the same weight, so Google can't tell which ones matter.",
        "support":   "Deep-link hierarchies concentrate authority on money pages.",
    },
    "nav_missing": {
        "hook_stat": "-40%",
        "hook_ctx":  "crawl coverage without a persistent top navigation.",
        "costs":     "No top menu means Google (and users) can't reach the money pages in one click.",
        "support":   "Every page needs a stable primary nav for internal PageRank to flow.",
    },
    "about_missing": {
        "hook_stat": "-25%",
        "hook_ctx":  "trust and LLM citation when there is no About page.",
        "costs":     "No About page hurts E-E-A-T and stops LLMs from citing the brand as a source.",
        "support":   "About pages are the strongest single signal LLMs use to decide who to quote.",
    },
    "hub_subdomain": {
        "hook_stat": "-30%",
        "hook_ctx":  "domain authority when the content hub lives on a separate subdomain.",
        "costs":     "A subdomain hub splits authority — the money site loses the topical strength the blog builds.",
        "support":   "Moving blog.example.com to example.com/blog concentrates PageRank on one domain.",
    },
    "orphan_page": {
        "hook_stat": "-30%",
        "hook_ctx":  "discoverability for orphan pages that no other page links to.",
        "costs":     "Orphan pages are hard for Google to find and easy for users to miss.",
        "support":   "",
    },
    "pagination_no_rel": {
        "hook_stat": "-10%",
        "hook_ctx":  "cannibalisation risk on paginated content.",
        "costs":     "Without pagination signals, page 2 competes with page 1 for the same query.",
        "support":   "",
    },
    # ── OG / hreflang / CTA ──────────────────────────────────────────────
    "hreflang_missing": {
        "hook_stat": "-25%",
        "hook_ctx":  "international traffic when Google can't map language variants.",
        "costs":     "Wrong-language pages show up for wrong-country searchers.",
        "support":   "",
    },
    "cta_missing": {
        "hook_stat": "+35%",
        "hook_ctx":  "more leads when pages get a clear CTA. Right now visitors have nothing to click.",
        "costs":     "Visitors arrive but there's nothing for them to do, so traffic doesn't turn into leads.",
        "support":   "",
    },
    # ── Spelling / grammar ───────────────────────────────────────────────
    "spelling_grammar": {
        "hook_stat": "-10%",
        "hook_ctx":  "trust loss from copy with spelling or grammar issues.",
        "costs":     "Errors in customer-facing copy read as inattention.",
        "support":   "",
    },
}


def _short_hook(obs):
    """Compress a long observation to a headline that fits the hero.

    Long observations from parameters.py (e.g. 'Multiple pages found wasting
    crawl budget : 10 of 19 crawled URLs are redirects, errors or
    non-indexable') break the hero layout. Rule of thumb:
      1. Cut at first colon (raw metrics tend to follow ':').
      2. Then cut at first sentence-end.
      3. If still >90 chars, hard-truncate on a word boundary + ellipsis.
    """
    s = (obs or "").strip()
    if not s:
        return ""
    # Cut at ' : ' or ': ' which usually separates the headline from the
    # numeric detail ("... crawl budget : 10 of 19 crawled URLs …")
    for sep in (" : ", " :", ": "):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    # First sentence
    import re as _re
    m = _re.search(r"(?<=\w{3})\.(?:\s+|$)", s)
    if m:
        s = s[:m.start() + 1]
    # Hard cap at 90 chars on word boundary
    if len(s) > 90:
        cut = s[:90].rsplit(" ", 1)[0].rstrip(",.:;")
        s = cut + "…"
    return s


def for_row(key, default_obs="", default_costs="", priority=""):
    """Return dict for a given observation key, or best-effort defaults."""
    if key and key in HOOK_COPY:
        return HOOK_COPY[key]
    fallback_stat = {
        "Critical": "-25%",
        "High":     "-15%",
        "Medium":   "-8%",
        "Low":      "-3%",
    }.get(priority, "")
    return {
        "hook_stat": fallback_stat,
        "hook_ctx":  _short_hook(default_obs),
        "costs":     default_costs or "",
        "support":   "",
    }
