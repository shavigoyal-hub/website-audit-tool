"""Render-time checks that the Screaming Frog CSV can't answer on its own.

We fetch the raw HTML of the representative pages (no JavaScript, i.e. what a
crawler sees) and check two things:

  1. Structured data (schema.org) — is there any JSON-LD or microdata at all?
     Mirrors what https://validator.schema.org/ reports. Absence is an SEO gap
     (no rich-result eligibility).

  2. Rendering — does meaningful content appear WITHOUT JavaScript? This is the
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


def _has_schema(html):
    jsonld = re.search(r'type=["\']application/ld\+json["\']', html, re.I)
    micro = re.search(r"itemscope|itemtype\s*=", html, re.I)
    return bool(jsonld or micro)


def analyze(reps):
    """reps = {page_type: url}. Returns a dict of findings + per-page detail."""
    pages = []
    for ptype, url in reps.items():
        sc, html = fetch(url)
        if sc != 200 or not isinstance(html, str):
            pages.append({"type": ptype, "url": url, "ok": False})
            continue
        pages.append({
            "type": ptype, "url": url, "ok": True,
            "schema": _has_schema(html),
            "text_chars": len(_visible_text(html)),
        })

    checked = [p for p in pages if p.get("ok")]
    schema_pages = [p for p in checked if p["schema"]]
    blank_pages = [p for p in checked if p["text_chars"] < RENDER_MIN_CHARS]

    return {
        "pages": pages,
        # Structured data: flagged if NO checked page has any schema markup.
        "structured_data_absent": bool(checked) and not schema_pages,
        # Rendering: flagged only if some page is an empty shell without JS.
        "render_blocked": blank_pages,
        "render_ok": bool(checked) and not blank_pages,
    }
