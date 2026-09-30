"""LLM sweep — free-form findings the fixed-rule checks would miss.

Hands GPT a compressed picture of the site (homepage HTML, sitemap sample,
a handful of key pages) and asks 'what else is wrong here that a rule set
wouldn't catch'. Returns a list of finding dicts in the same shape as
parameters._issue() so pipeline.run can merge them into obs_rows.

Falls back to [] cleanly if OPENAI_API_KEY isn't set or the call fails.

Design constraints (from user memory):
  - Every observation is 1-2 short sentences + eg URLs.
  - No stories, no benchmarking, no prescriptive fixes.
  - Skip llms.txt and og:image findings.
"""
import json
import os
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"}

_MAX_HTML = 28000       # per-page char cap sent to the LLM
_MAX_PAGES = 4          # homepage + up to 3 more
_MAX_SITEMAP_URLS = 60


def _get(url, timeout=15):
    try:
        return requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None


def _origin(url):
    m = re.match(r"(https?://[^/]+)", url.strip())
    return m.group(1) if m else url.rstrip("/")


def _strip(html):
    """Compact HTML: drop <script>/<style>/comments, collapse whitespace."""
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    html = re.sub(r"<style\b[^>]*>.*?</style>",   "", html, flags=re.I | re.S)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"\s+", " ", html)
    return html[:_MAX_HTML]


_JUNK_URL = re.compile(
    # (?:/|$|\?|#) so /feeds (no slash) is matched too
    r"/feeds?(?:/|$|\?|#)|/tags?(?:/|$|\?|#)|/categor(?:y|ies)(?:/|$|\?|#)"
    r"|/page/\d+|[?&]paged?=|/author(?:/|$)|/attachment(?:/|$)"
    r"|/wp-json/|/wp-admin/|/xmlrpc\.php|/wp-content/uploads/", re.I)


_THIN_WORDS = re.compile(
    r"\bthin\b|word count|\b(?:little|minimal|sparse|short|not enough|lack of|"
    r"lacks?)\s+(?:copy|content|text)|content depth|low[- ]value", re.I)


def _is_non_seo_url(line):
    """True when a reference line names a utility page (contact, login…)."""
    from audit.sf_csv import NON_SEO_PATTERNS
    low = line.lower()
    return any(pat in low for pat in NON_SEO_PATTERNS)


def _sitemap_sample(origin):
    r = _get(origin + "/sitemap.xml", timeout=10)
    if not r or r.status_code != 200:
        return []
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text or "")
    # Never show junk URLs to the LLM as sample content (feeds/tags/etc.).
    # Track the raw count separately so it can report 'feeds dominate sitemap'
    # from the ratio.
    non_junk = [u for u in urls if not _JUNK_URL.search(u)]
    return non_junk[:_MAX_SITEMAP_URLS]


def _pick_extra_pages(sitemap_urls, origin):
    """Choose up to 3 non-homepage URLs: prefer /services, /about, /contact, /pricing."""
    prefs = ("/service", "/about", "/contact", "/pricing", "/product")
    picked = []
    for pref in prefs:
        for u in sitemap_urls:
            if pref in u.lower() and u not in picked and u.rstrip("/") != origin:
                picked.append(u)
                break
        if len(picked) >= 3:
            break
    return picked[:3]


_SYSTEM = """You are a senior SEO auditor doing a manual pass over a website.
Fixed-rule crawlers already caught the generic issues (missing titles, thin
content, bad canonicals, 4xx, etc). Your job is to find the site-specific
weirdness a rule set would miss:

  - Wix/WordPress editor leftovers (copy-of-*, /services-2, /page-2)
  - Nav labels that don't match their destination URL
  - Same H1 used across many pages as a CTA line
  - Indexable thank-you / confirmation pages
  - Duplicate <form> ids on the same page
  - (DO NOT talk about /feeds/, /tags/, /categories/, /author/ pages —
    they're excluded from every audit. Never mention them.)
  - Broken image references, placeholder text, lorem ipsum
  - Content that looks AI-generated with no editing

Return STRICT JSON:
{"findings": [{"key": "<short_snake_case>", "category": "<2-4 word category>",
"priority": "Critical"|"High"|"Medium"|"Low", "observation": "<1-2 short
sentences>", "impact": "<1 sentence business consequence>", "reference":
"<eg URL(s) separated by newlines>"}]}

RULES:
  - Every observation is 1-2 short sentences + eg URLs. NO stories, NO
    benchmarking, NO prescriptive fixes.
  - Skip anything about /llms.txt or missing og:image.
  - Skip generic findings a rule set already catches (missing title, thin
    content, 4xx, canonical issues) — those are already in the sheet.
  - If you find nothing that fits, return {"findings": []}. Do not invent.
  - Cap at 8 findings, ranked by real impact.
"""


def _call_openai(prompt):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "max_tokens": 1800,
            },
            timeout=60,
        )
    except Exception as exc:
        print(f"[llm_sweep] openai call failed: {exc}")
        return None
    if not r.ok:
        print(f"[llm_sweep] openai {r.status_code}: {(r.text or '')[:200]}")
        return None
    try:
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        return json.loads(text)
    except Exception as exc:
        print(f"[llm_sweep] openai parse failed: {exc}")
        return None


def evaluate(live_url):
    """Return list of finding dicts. Never raises."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return []
    try:
        origin = _origin(live_url)
        home = _get(origin + "/")
        if home is None or home.status_code != 200:
            return []
        home_html = _strip(home.text or "")

        sitemap = _sitemap_sample(origin)
        extra_urls = _pick_extra_pages(sitemap, origin)
        extras = []
        for u in extra_urls:
            r = _get(u)
            if r and r.status_code == 200:
                extras.append((u, _strip(r.text or "")))

        parts = [
            f"SITE: {origin}",
            f"\nSITEMAP SAMPLE ({len(sitemap)} of many):",
            "\n".join(sitemap[:_MAX_SITEMAP_URLS]),
            f"\n\nHOMEPAGE HTML ({origin}/):\n{home_html}",
        ]
        for u, h in extras:
            parts.append(f"\n\nPAGE HTML ({u}):\n{h}")

        result = _call_openai("\n".join(parts))
        if not result:
            return []

        raw = result.get("findings") or []
        findings = []
        for f in raw[:8]:
            key = str(f.get("key", "")).strip().lower()
            key = re.sub(r"[^a-z0-9_]+", "_", key)[:60]
            if not key:
                continue
            # Namespace so we can tell rule vs sweep findings apart later
            if not key.startswith("llm_"):
                key = f"llm_{key}"
            obs = str(f.get("observation", "")).strip()
            if not obs:
                continue
            # User-requested skips: never emit HTML-entity or low-inlinks
            # findings even if the model wants to.
            _lo = obs.lower()
            if ("html entit" in _lo or "&amp;" in _lo or "&#" in _lo
                    or "few internal link" in _lo or "internal linking" in _lo
                    or "inlinks" in _lo):
                continue
            # Strip junk URLs from the reference list — never show a feed /
            # tag / category / author page as evidence, even if the LLM
            # mentioned it.
            ref_raw = str(f.get("reference", "")).strip()
            ref_lines = [ln.strip() for ln in ref_raw.split("\n") if ln.strip()]
            ref_lines = [ln for ln in ref_lines if not _JUNK_URL.search(ln)]
            # Thin / low-copy observations are SEO-content findings, and
            # those never fire on utility pages (/contact, /login, /privacy…
            # — sf_csv.NON_SEO_PATTERNS, same rule as v46). The prompt tells
            # the model to skip thin content, but it still reported the
            # pilotpaintingco contact page as thin; drop such URLs here, and
            # drop the finding when nothing else backs it.
            if _THIN_WORDS.search(obs):
                ref_lines = [ln for ln in ref_lines if not _is_non_seo_url(ln)]
                if not ref_lines:
                    continue
            reference = "\n".join(ref_lines) if ref_lines else "-"
            # If a finding is *specifically about* feeds pages, drop it —
            # the user's hard rule: never talk about feeds pages.
            if _JUNK_URL.search(obs.lower()) or "feeds" in obs.lower():
                continue
            findings.append({
                "key":         key,
                "category":    str(f.get("category", "")).strip() or "Manual review",
                "priority":    str(f.get("priority", "Medium")).strip().title(),
                "observation": obs,
                "impact":      str(f.get("impact", "")).strip(),
                "reference":   reference,
            })
        print(f"[llm_sweep] {len(findings)} findings from LLM sweep")
        return findings
    except Exception as exc:
        print(f"[llm_sweep] failed: {exc}")
        return []
