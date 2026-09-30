"""Runs a full audit (crawl → checks → sheet) for one URL.

Extracted from app.py so both the sync /run path and the local worker can
call it without going through Flask. Uses Screaming Frog when the binary
is on disk (Mac), else the built-in Python crawler.
"""
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as _ET

import pandas as pd
import requests

from audit import (crawler, history, metrics, observations, pagespeed,
                   parameters, report_sheets, sf_csv)
from audit.version import VERSION

SF_CLI = "/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher"
SF_AVAILABLE = os.path.isfile(SF_CLI)


# Real-Chrome UA so sites that fingerprint SF's default UA still let us in.
_DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/126.0.0.0 Safari/537.36")


def _sf_crawl(url, max_urls=None):
    """Crawl HTML pages only, with SF's own defaults.

    Older SF CLI versions (like the one on this Mac) don't recognise
    --config-option, so we skip it entirely and rely on the SF GUI's
    saved config (user agent, threads, respect-robots etc.). To tune
    those, open SF once and set them in Configuration → Spider.

    Opt-in via env:
      SF_MAX_URLS      — hint SF via env; SF still needs its own crawl-limit config
      SF_CONFIG_FILE   — pass a .seospiderconfig file via --config <path>
    """
    tmp_dir = tempfile.mkdtemp(prefix="sf_audit_")
    try:
        cmd = [SF_CLI, "--headless", "--crawl", url,
               "--output-folder", tmp_dir,
               "--export-tabs", "Internal:HTML",
               "--overwrite"]
        cfg = os.environ.get("SF_CONFIG_FILE", "").strip()
        if cfg and os.path.isfile(cfg):
            cmd += ["--config", cfg]
        # Capture stderr so a failure surfaces something usable in the Jobs row.
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(
                f"SF exit {r.returncode}. stderr[:800]: {r.stderr[:800]}"
            )
        # Newer SF exports as internal_html.csv when the tab is Internal:HTML.
        for name in ("internal_html.csv", "internal_all.csv"):
            matches = glob.glob(os.path.join(tmp_dir, name))
            if matches:
                break
        else:
            raise FileNotFoundError(
                f"Crawl finished but no internal_*.csv found in {tmp_dir}. "
                f"Files present: {os.listdir(tmp_dir)[:20]}"
            )
        df = pd.read_csv(matches[0], dtype=str, keep_default_na=False,
                         low_memory=False)
        df.columns = [c.strip() for c in df.columns]
        return df
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _probe_site(url):
    """One HEAD-like GET to learn canonical URL + whether the site is JS-rendered.

    Returns dict with:
      final_url:  URL after redirects (feed THIS to SF, not the raw input)
      js_hint:    True if body suggests SPA (Next.js/React/Vue root, tiny HTML)
      html_ok:    True if we got a 2xx with non-empty HTML
      sitemap:    URL of the sitemap if we can detect it (from robots.txt), else ""
    """
    out = {"final_url": url, "js_hint": False, "html_ok": False, "sitemap": ""}
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 Gushwork-Audit"},
                         timeout=15, allow_redirects=True)
    except Exception:
        return out
    out["final_url"] = str(r.url) or url
    if r.status_code // 100 == 2 and r.text:
        out["html_ok"] = True
        body = r.text
        m = re.search(r"<body[^>]*>(.*?)</body>", body, re.I | re.S)
        body_only = m.group(1).strip() if m else body
        # SPA heuristic — tiny body OR obvious SPA markers
        markers = ("__NEXT_DATA__", "id=\"__next\"", "id='__next'",
                   "data-reactroot", "<div id=\"root\"", "id=\"app\"",
                   "id='app'", "ng-app", "data-v-app")
        if len(body_only) < 2500 or any(mk in body for mk in markers):
            out["js_hint"] = True
    # Sitemap discovery via robots.txt
    from urllib.parse import urlparse, urljoin
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    try:
        rob = requests.get(urljoin(origin, "/robots.txt"), timeout=5)
        if rob.ok:
            for line in rob.text.splitlines():
                m2 = re.match(r"^\s*sitemap\s*:\s*(\S+)", line, re.I)
                if m2:
                    out["sitemap"] = m2.group(1).strip()
                    break
    except Exception:
        pass
    if not out["sitemap"]:
        # Try well-known locations
        for path in ("/sitemap.xml", "/sitemap_index.xml"):
            try:
                sm = requests.head(urljoin(origin, path), timeout=5,
                                    allow_redirects=True)
                if sm.ok:
                    out["sitemap"] = urljoin(origin, path)
                    break
            except Exception:
                continue
    return out


def _sitemap_urls(sitemap_url, cap=2000):
    """Fetch a sitemap (or sitemap index) and return a flat list of page URLs."""
    seen = set()
    def _walk(url, depth=0):
        if depth > 3 or len(seen) >= cap or not url:
            return
        try:
            r = requests.get(url, timeout=15)
            if not r.ok:
                return
        except Exception:
            return
        # Strip default namespace so ET matching is easy
        text = re.sub(r'xmlns="[^"]+"', "", r.text, count=1)
        try:
            root = _ET.fromstring(text)
        except Exception:
            return
        # Sitemap index → recurse into each <sitemap>/<loc>
        for sm in root.findall(".//sitemap/loc"):
            _walk((sm.text or "").strip(), depth + 1)
        # Leaf sitemap → collect <url>/<loc>
        for u in root.findall(".//url/loc"):
            v = (u.text or "").strip()
            if v.startswith("http"):
                seen.add(v)
                if len(seen) >= cap:
                    return
    _walk(sitemap_url)
    return list(seen)


def _sf_list_crawl(urls, max_urls=None):
    """Run SF in LIST mode against a fixed URL list (typically from sitemap).

    Uses SF's own default config (older SF CLI does not recognise
    --config-option). Tune via SF GUI or SF_CONFIG_FILE env.
    """
    tmp_dir = tempfile.mkdtemp(prefix="sf_list_")
    list_path = os.path.join(tmp_dir, "urls.txt")
    try:
        with open(list_path, "w") as fh:
            for u in urls[: (max_urls or 5000)]:
                fh.write(u.strip() + "\n")
        cmd = [SF_CLI, "--headless", "--crawl-list", list_path,
               "--output-folder", tmp_dir,
               "--export-tabs", "Internal:HTML",
               "--overwrite"]
        cfg = os.environ.get("SF_CONFIG_FILE", "").strip()
        if cfg and os.path.isfile(cfg):
            cmd += ["--config", cfg]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError(
                f"SF list-mode exit {r.returncode}. stderr[:800]: {r.stderr[:800]}"
            )
        for name in ("internal_html.csv", "internal_all.csv"):
            matches = glob.glob(os.path.join(tmp_dir, name))
            if matches:
                break
        else:
            raise FileNotFoundError(
                f"list-mode: no internal_*.csv in {tmp_dir}. "
                f"Files: {os.listdir(tmp_dir)[:20]}"
            )
        df = pd.read_csv(matches[0], dtype=str, keep_default_na=False,
                         low_memory=False)
        df.columns = [c.strip() for c in df.columns]
        return df
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _get_dataframe_with_tag(live_url):
    """SF first with smart auto-detection; fall back through progressively
    simpler crawlers on failure.

    Chain:
      1. Probe homepage — canonical URL after redirects, SPA detection, sitemap.
      2. SF spider crawl of the canonical URL. JS rendering auto-on if SPA.
      3. If SF returns 0-1 rows, retry with JS rendering.
      4. **SF LIST mode** against sitemap URLs (many sites where SF spider
         fails still let SF fetch a fixed URL list). We keep SF's rich
         data extraction this way.
      5. Python fetch of sitemap URLs (last resort — thin data).
      6. Python spider crawl of the homepage (final fallback).

    Returns (df, crawler_used) — 'screaming-frog' / 'screaming-frog-list'
    / 'sitemap' / 'python'.
    """
    max_urls = os.environ.get("SF_MAX_URLS", "").strip()
    max_urls = int(max_urls) if max_urls.isdigit() else None
    js_env = os.environ.get("SF_JS_RENDER", "").strip() in ("1", "true", "yes")

    probe = _probe_site(live_url)
    target = probe["final_url"] or live_url
    if probe["js_hint"] and not js_env:
        print(f"[pipeline] SPA markers detected — enabling JS rendering for SF")
        os.environ["SF_JS_RENDER"] = "1"

    if SF_AVAILABLE:
        try:
            df = _sf_crawl(target, max_urls=max_urls)
            if len(df) <= 1 and not js_env:
                print(f"[pipeline] SF returned {len(df)} rows — retrying with JS rendering")
                os.environ["SF_JS_RENDER"] = "1"
                df = _sf_crawl(target, max_urls=max_urls)
            if len(df) >= 2:
                return df, "screaming-frog"
            print(f"[pipeline] SF crawl came back empty on {target}")
        except Exception as exc:
            print(f"[pipeline] SF spider failed: {exc}")

        # SF LIST mode — feed sitemap URLs directly to SF.
        if probe["sitemap"]:
            urls = _sitemap_urls(probe["sitemap"])
            if urls:
                print(f"[pipeline] SF list-mode fallback — {len(urls)} URLs "
                       f"from {probe['sitemap']}")
                try:
                    df = _sf_list_crawl(urls, max_urls=max_urls)
                    if len(df) >= 1:
                        return df, "screaming-frog-list"
                except Exception as exc:
                    print(f"[pipeline] SF list-mode failed: {exc}")

    # Python-side sitemap fallback (no SF at all — thinner data)
    if probe["sitemap"]:
        urls = _sitemap_urls(probe["sitemap"])
        if urls:
            print(f"[pipeline] python-sitemap fallback — {len(urls)} URLs")
            rows = crawler.crawl_urls(urls) if hasattr(crawler, "crawl_urls") else crawler.crawl(target)
            return pd.DataFrame(rows), "sitemap"

    print(f"[pipeline] falling back to Python crawler for {target}")
    rows = crawler.crawl(target)
    return pd.DataFrame(rows), "python"


# Always-skip URL patterns — Direct-chat audit rules copied over. Never
# report findings whose sample URLs are only these (junk to Google, or CRO
# assets that don't compete for organic traffic).
DEFAULT_EXCLUDE_URL_PATTERNS = [
    r"/feeds?/",              # /feed/, /feeds/
    r"/tags?/",               # /tag/, /tags/
    r"/categor(y|ies)/",      # /category/, /categories/
    r"/page/\d+",             # WordPress paged archives
    r"[?&]paged?=",           # ?paged=2, ?page=2
    r"/author/",              # WordPress author archives
    r"/attachment/",          # WordPress attachment pages
    r"/wp-json/",             # WordPress REST endpoints
    r"/wp-admin/",
    r"/xmlrpc\.php",
    r"/wp-content/uploads/",
    r"/\?replytocom=",        # WordPress reply comment URLs
]

# Conversion-path pages — LCP/thin-content/meta/title/H1 gaps on THESE
# pages are CRO concerns, not organic SEO issues, so we don't flag them.
CONVERSION_PATH_PATTERNS = [
    r"/contact",
    r"/apply",
    r"/book",
    r"/schedule",
    r"/demo",
    r"/get-in-touch",
    r"/get-started",
    r"/free-consultation",
    r"/request-quote",
    r"/thank-you",
    r"/thankyou",
    r"/who-we-are",
    r"/about-us",
    r"/about",
    r"/careers",
    r"/jobs",
    r"/privacy",
    r"/terms",
    r"/legal",
    r"/cookie",
    r"/refund",
    r"/shipping",
    r"/returns",
]

# Additional per-URL exclusion: never quote a parameterized URL as an
# example (?product_cat=..., ?utm_source=..., etc.). Query strings are
# junk for SEO and clutter the deck.
_HAS_QUERY = r"\?"

# Findings where a conversion-page URL should be dropped from the sample list.
_CONVERSION_SKIP_KEYS = {
    "lcp_high", "lcp_medium", "thin_content",
    "meta_missing", "meta_long", "meta_short",
    "title_missing", "title_long", "title_short",
    "h1_missing", "h1_short",
}


def _apply_url_rules(findings):
    """Filter finding-URL evidence per Direct-chat audit rules.

    Three passes on each finding's example URLs:
      1. Drop always-junk paths (feeds, tags, categories, wp-admin).
      2. Drop parameterized URLs (anything with a `?query`) — SEO junk.
      3. For LCP/thin/meta/title/H1 findings: also drop conversion pages
         (contact/about/apply/careers/privacy/terms/etc.) since they are
         CRO assets not organic-traffic targets.
    Empty finding after filtering → drop the whole finding.
    """
    import re as _re
    exclude_re = _re.compile("|".join(DEFAULT_EXCLUDE_URL_PATTERNS), _re.I)
    conv_re = _re.compile("|".join(CONVERSION_PATH_PATTERNS), _re.I)
    kept = []
    for f in findings:
        exs = f.get("examples") or []
        # Pass 1: always-junk
        exs = [u for u in exs if not exclude_re.search(u)]
        # Pass 2: query strings — never show ?product_cat=... etc. in examples
        exs = [u for u in exs if "?" not in u]
        # Pass 3: conversion pages for the finding types where they don't apply
        if f.get("key") in _CONVERSION_SKIP_KEYS:
            exs = [u for u in exs if not conv_re.search(u)]
        if not exs:
            continue
        new = dict(f)
        new["examples"] = exs
        if "count" in new:
            new["count"] = len(exs)
        kept.append(new)
    return kept


def run(live_url):
    """Full audit pipeline. Returns dict with sheet_url + metrics."""
    metrics.reset()
    _crawler_used = "python"  # updated below if SF succeeds
    m = re.match(r"https?://(?:www\.)?([^/]+)", live_url)
    domain = m.group(1) if m else live_url
    client_name = re.sub(r"\.[^.]+$", "", domain).replace(".", "_").lower()
    psi_key = os.environ.get("PAGESPEED_API_KEY")

    exclude_patterns, page_type_patterns, manual_psi = [], None, None
    client_json = os.path.join("clients", f"{client_name}.json")
    if os.path.exists(client_json):
        with open(client_json) as f:
            stored = json.load(f)
        exclude_patterns = stored.get("exclude_url_patterns", [])
        page_type_patterns = stored.get("page_type_patterns")
        manual_psi = stored.get("manual_psi")

    df_raw, _crawler_used = _get_dataframe_with_tag(live_url)
    df = sf_csv.load_from_df(df_raw, exclude_patterns=exclude_patterns)
    status_num = pd.to_numeric(df.get("Status Code", pd.Series([], dtype=str)),
                               errors="coerce").fillna(0).astype(int)
    total_pages = int((sf_csv.is_html(df) & (status_num == 200)).sum())
    total_images = int(sf_csv.is_image(df_raw).sum())
    metrics.set_value("pages_crawled", total_pages)

    findings = sf_csv.run_checks(df, df, has_images_csv=False)
    findings = _apply_url_rules(findings)
    reps = sf_csv.representative_pages(df, custom_patterns=page_type_patterns)

    psi_live = manual_psi or pagespeed.fetch_many(reps, "mobile", psi_key)
    psi_rows = observations.psi_to_observations(psi_live) if psi_live else []
    # If EVERY PSI response errored (usually anonymous quota exhaustion),
    # tell the reviewer instead of silently missing the LCP finding.
    if psi_live and observations.psi_all_errored(psi_live):
        sample_err = ""
        for r in psi_live.values():
            if r and r.get("error"):
                sample_err = str(r["error"])[:200]
                break
        psi_rows.append({
            "key": "psi_unavailable",
            "category": "Page Speed",
            "observation": ("Multiple pages found where PageSpeed Insights was "
                            "blocked. LCP and Core Web Vitals could not be measured this run.\n"
                            f"eg: {sample_err}"),
            "priority": "High",
            "impact": "May impact ranking",
            "reference": "-",
        })

    live_url_norm = live_url if live_url.endswith("/") else live_url + "/"
    site = parameters.evaluate(df, live_url_norm)
    # Chat-style deep audit on the homepage + key pages. Runs regardless
    # of which crawler produced df, so even sitemap-fallback runs get
    # the same homepage findings a chat audit would surface.
    try:
        from audit import deep_analyzer as _deep
        deep_issues = _deep.evaluate(live_url_norm)
        if deep_issues:
            print(f"[pipeline] deep_analyzer emitted {len(deep_issues)} findings")
        site["issues"].extend(deep_issues)
    except Exception as exc:
        print(f"[pipeline] deep_analyzer skipped: {exc}")

    # LLM free-form sweep — catches site-specific weirdness the fixed rules
    # miss (Wix copy-of-* pages, nav-label mismatches, HTML entities in
    # titles, indexable TY pages, feeds sitemap ratios, etc.).
    try:
        from audit import llm_sweep as _sweep
        sweep_issues = _sweep.evaluate(live_url_norm)
        if sweep_issues:
            print(f"[pipeline] llm_sweep emitted {len(sweep_issues)} findings")
        site["issues"].extend(sweep_issues)
    except Exception as exc:
        print(f"[pipeline] llm_sweep skipped: {exc}")

    site_obs = [{"key": i.get("key", ""),
                 "category": i["category"], "observation": i["observation"],
                 "priority": i["priority"], "impact": i["impact"],
                 "reference": i["reference"]}
                for i in site["issues"]]

    rows, _notes = observations.build_rows(findings, psi_rows, site_obs)

    # LLM judgement pass — rewrites each finding in Gushwork's voice using
    # the actual HTML of the affected page. No-op if OPENAI_API_KEY /
    # ANTHROPIC_API_KEY aren't set.
    try:
        from audit import llm_judge
        rows = llm_judge.enrich(rows, live_url)
    except Exception as exc:
        print(f"[pipeline] LLM judgement skipped: {exc}")

    friendly = client_name.replace("_", " ").replace("-", " ").title()
    sheet_title = f"{friendly} — SEO Audit ({datetime.date.today()})"
    meta = {
        "version":   VERSION,
        "generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "live_url":  live_url,
    }
    sheet_url = report_sheets.build(
        sheet_title, rows, evidence_tabs=[],
        total_pages=total_pages, total_images=total_images, meta=meta,
    )
    metrics_snap = metrics.snapshot()
    if sheet_url:
        try:
            history.append_run(client_name, live_url, sheet_url,
                                metrics=metrics_snap)
        except Exception:
            pass
    else:
        # report_sheets.build swallowed an exception into LAST_ERROR.
        # Surface it so the worker can mark the job with a real error
        # instead of silently marking done with sheet_url="".
        err = getattr(report_sheets, "LAST_ERROR", "") or "sheet build failed with no diagnostic"
        raise RuntimeError(f"Sheet build failed: {err[:1500]}")
    return {
        "sheet_url":    sheet_url,
        "metrics":      metrics_snap,
        "observations": len(rows),
        "client_name":  client_name,
        "crawler":      _crawler_used,
    }
