"""Render-time checks that the Screaming Frog CSV can't answer on its own.

We fetch the raw HTML of the representative pages (no JavaScript, i.e. what a
crawler sees) and check two things:

  1. Structured data (schema.org) : is there any JSON-LD or microdata at all?
     Mirrors what https://validator.schema.org/ reports. Absence is an SEO gap
     (no rich-result eligibility).

  2. Rendering : does meaningful content appear WITHOUT JavaScript? This is the
     same question the fetch-and-render tools answer
     (https://technicalseo.com/tools/fetch-render/ , https://page-replica.com).
     If a page is an empty shell without JS, crawlers may index nothing.
"""
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; GushworkAuditBot/1.0; +https://gushwork.ai)"}
# Below this many characters of no-JS body text, a page is effectively blank to
# a crawler that doesn't execute JavaScript.
RENDER_MIN_CHARS = 500


def fetch(url, timeout=30):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        return r.status_code, r.text
    except requests.RequestException as e:
        return None, str(e)


def _visible_text(html):
    body = re.sub(r"(?is)<(script|style|noscript|template).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", text).strip()


# What schema.org type(s) each PAGE TYPE should carry. A page passes if it has
# ANY of the listed types. `label` is shown in the observation example.
EXPECTED_SCHEMA = {
    "Homepage":          {"types": ["organization", "website", "localbusiness"], "label": "Organization / WebSite"},
    "Service / Product": {"types": ["service", "product", "offer"],              "label": "Service / Product"},
    "Industry":          {"types": ["service", "localbusiness", "professionalservice", "webpage"], "label": "Service / LocalBusiness"},
    "About / Process":   {"types": ["organization", "aboutpage", "professionalservice"], "label": "Organization / AboutPage"},
    "Contact":           {"types": ["localbusiness", "contactpage", "contactpoint", "organization"], "label": "LocalBusiness / ContactPoint"},
    "Article / Blog":    {"types": ["article", "blogposting", "newsarticle"],    "label": "Article / BlogPosting"},
    "Other / Landing":   {"types": ["webpage", "breadcrumblist", "faqpage"],     "label": "WebPage / Breadcrumb"},
}


def _schema_types(html):
    """Return the set of lowercase schema.org @type values present (JSON-LD + microdata)."""
    types = set(t.lower() for t in re.findall(r'"@type"\s*:\s*"([^"]+)"', html))
    for it in re.findall(r'itemtype\s*=\s*["\']https?://schema\.org/([^"\']+)', html, re.I):
        types.add(it.lower())
    return types


def analyze(reps, df=None):
    """reps = {page_type: url}. Returns a dict of findings + per-page detail.

    Structured data is checked PER PAGE TYPE: each representative page must carry
    the schema expected for its type (homepage -> Organization/WebSite, service ->
    Service, blog -> Article, etc.). One example per type is surfaced.

    If df (the Screaming Frog dataframe) is supplied AND it contains a
    'Rendered Word Count' column (i.e. SF was crawled in JavaScript mode), the
    render-blocked check uses SF data directly instead of an HTTP fetch. The
    schema check always runs via a live fetch regardless.
    """
    # Detect whether SF was crawled in JavaScript mode (has rendered word counts).
    sf_render_available = (
        df is not None
        and "Rendered Word Count" in df.columns
        and "Word Count" in df.columns
    )

    pages = []
    for ptype, url in reps.items():
        sc, html = fetch(url)
        if sc != 200 or not isinstance(html, str):
            pages.append({"type": ptype, "url": url, "ok": False})
            continue
        types = _schema_types(html)
        exp = EXPECTED_SCHEMA.get(ptype, {"types": [], "label": "schema markup"})
        has_expected = bool(exp["types"]) and any(t in types for t in exp["types"])

        # Render-blocked: prefer SF rendered vs raw comparison; fall back to
        # our own visible-char count from the no-JS fetch.
        if sf_render_available:
            import pandas as pd
            row = df[df["Address"] == url]
            if not row.empty:
                raw_wc = pd.to_numeric(row["Word Count"].iloc[0], errors="coerce") or 0
                rend_wc = pd.to_numeric(row["Rendered Word Count"].iloc[0], errors="coerce") or 0
                # JS-dependent if raw is nearly empty but rendered has content.
                text_chars = int(raw_wc) * 6  # approx chars (5 chars/word + space)
                render_source = "sf"
            else:
                text_chars = len(_visible_text(html))
                render_source = "fetch"
        else:
            text_chars = len(_visible_text(html))
            render_source = "fetch"

        pages.append({
            "type": ptype, "url": url, "ok": True,
            "schema": bool(types),
            "schema_types": sorted(types),
            "schema_expected": exp["label"],
            "schema_ok": has_expected,
            "text_chars": text_chars,
            "render_source": render_source,
        })

    checked = [p for p in pages if p.get("ok")]
    # one example per page type missing its expected schema (canonical type order)
    order = ["Homepage", "Service / Product", "About / Process", "Contact",
             "Article / Blog", "Other / Landing"]
    schema_gaps = sorted(
        [{"type": p["type"], "url": p["url"], "expected": p["schema_expected"]}
         for p in checked if not p.get("schema_ok")],
        key=lambda g: order.index(g["type"]) if g["type"] in order else 99)
    blank_pages = [p for p in checked if p["text_chars"] < RENDER_MIN_CHARS]

    return {
        "pages": pages,
        "schema_gaps": schema_gaps,                 # type-aware structured-data gaps
        "structured_data_absent": bool(schema_gaps),
        "render_blocked": blank_pages,
        "render_ok": bool(checked) and not blank_pages,
        "sf_render_mode": sf_render_available,      # True = SF was crawled with JS rendering
    }
