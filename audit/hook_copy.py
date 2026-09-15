"""PDF-matched Hook Stat / Hook Context / What It Costs You copy per finding.

Structure mirrors the Arizona Home Grants reference deck:
  hook_stat:  a big number (e.g. "+32.3%", "54.4%", "0%")
  hook_ctx:   short subtitle stating what the number MEANS
  costs:      1-sentence business consequence
  support:    optional supporting stat that reinforces the loss

Keyed by the observation `key` from observations.py CATALOG.
"""

HOOK_COPY = {
    # ── H1 tags ────────────────────────────────────────────────────────────
    "h1_missing": {
        "hook_stat": "+32.3%",
        "hook_ctx":  "more leads per position climbed. Pages with no H1 give Google no topic to rank for.",
        "costs":     "Your top pages give Google nothing to rank. Missing H1s remove the primary on-page relevance signal — directly hurting rankings and leads.",
        "support":   "79% of visitors scan, not read. No headline, no reason to stay.",
    },
    "h1_multiple": {
        "hook_stat": "-15%",
        "hook_ctx":  "ranking dilution when multiple H1s compete on one page.",
        "costs":     "Competing H1s blur which topic the page is about — Google picks the weaker one.",
        "support":   "",
    },
    "h1_short": {
        "hook_stat": "-8%",
        "hook_ctx":  "CTR loss when H1s are too short to describe the page.",
        "costs":     "Short H1s under-describe the page and weaken relevance signals.",
        "support":   "",
    },
    "h1_long": {
        "hook_stat": "-6%",
        "hook_ctx":  "H1 dilution when the headline over-reaches.",
        "costs":     "Overly long H1s dilute the primary topic signal.",
        "support":   "",
    },
    "h1_duplicate": {
        "hook_stat": "-12%",
        "hook_ctx":  "cannibalisation risk from duplicate H1s across pages.",
        "costs":     "Duplicate H1s blur which page is most relevant for a topic.",
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
        "hook_stat": "-40%",
        "hook_ctx":  "ranking loss when the title tag is missing — Google's #1 on-page signal.",
        "costs":     "Missing titles severely weaken relevance signals and rankings.",
        "support":   "",
    },
    "title_long": {
        "hook_stat": "-8%",
        "hook_ctx":  "CTR loss when titles get truncated in the SERP.",
        "costs":     "Truncated titles in search reduce click-through and rankings.",
        "support":   "",
    },
    "title_short": {
        "hook_stat": "-5%",
        "hook_ctx":  "SERP space wasted on titles under 30 chars.",
        "costs":     "Short titles under-describe the page and waste SERP space.",
        "support":   "",
    },
    "title_duplicate": {
        "hook_stat": "-15%",
        "hook_ctx":  "cannibalisation from duplicate title tags.",
        "costs":     "Duplicate titles confuse search engines about which page to rank.",
        "support":   "",
    },
    "title_stuffed": {
        "hook_stat": "-20%",
        "hook_ctx":  "trust loss from keyword-stuffed titles.",
        "costs":     "Keyword stuffing looks spammy and can hurt rankings.",
        "support":   "",
    },
    # ── Schema / structured data ─────────────────────────────────────────
    "structured_data": {
        "hook_stat": "+25%",
        "hook_ctx":  "more leads with structured data. You have none.",
        "costs":     "No rich results, no local signal. Searchers pick someone else.",
        "support":   "+82% CTR for rich results. +35% more visits with search features on.",
    },
    "faq_missing": {
        "hook_stat": "+15%",
        "hook_ctx":  "click-through when FAQ answers show under your listing.",
        "costs":     "You lose People-Also-Ask real estate to competitors who mark up their answers.",
        "support":   "",
    },
    # ── Content depth ────────────────────────────────────────────────────
    "thin_content": {
        "hook_stat": "54.4%",
        "hook_ctx":  "of clicks go to the top 3 results. Thin pages don't get there.",
        "costs":     "Money-decision pages don't earn enough trust to rank if they're thin.",
        "support":   "",
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
        "hook_stat": "-10%",
        "hook_ctx":  "authority leaked when there is no canonical tag.",
        "costs":     "Google may index the wrong URL variant and split link equity.",
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
        "hook_ctx":  "conversions when LCP is above 4 seconds.",
        "costs":     "Slow load kills the click before the page ever loads.",
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
    "pagination_no_rel": {
        "hook_stat": "-10%",
        "hook_ctx":  "cannibalisation risk on paginated content.",
        "costs":     "Without pagination signals, page 2 competes with page 1 for the same query.",
        "support":   "",
    },
    # ── OG / hreflang / CTA ──────────────────────────────────────────────
    "og_missing": {
        "hook_stat": "-20%",
        "hook_ctx":  "social CTR when shared links lack a rich preview.",
        "costs":     "Missing OG tags mean shares look bare — trust drops before the click.",
        "support":   "",
    },
    "hreflang_missing": {
        "hook_stat": "-25%",
        "hook_ctx":  "international traffic when Google can't map language variants.",
        "costs":     "Wrong-language pages show up for wrong-country searchers.",
        "support":   "",
    },
    "cta_missing": {
        "hook_stat": "-35%",
        "hook_ctx":  "conversion loss on pages without a clear CTA.",
        "costs":     "Visitors arrive but there's nothing for them to do.",
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


def for_row(key, default_obs="", default_costs=""):
    """Return dict for a given observation key, or best-effort defaults."""
    if key and key in HOOK_COPY:
        return HOOK_COPY[key]
    return {
        "hook_stat": "",
        "hook_ctx":  default_obs or "",
        "costs":     default_costs or "",
        "support":   "",
    }
