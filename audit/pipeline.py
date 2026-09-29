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

import pandas as pd

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
    """Crawl HTML pages only, with sensible defaults for real sites.

    Fixes we bake in by default:
      - HTML only (skip images/css/js/swf/externals)
      - Real Chrome User-Agent (dodges basic bot fingerprinting)
      - Lower thread count (avoids rate limits)
      - Full traceback on failure via captured stderr

    Opt-in via env for the trickier fixes:
      SF_MAX_URLS=1000        — cap the crawl (also stops runaway loops)
      SF_MAX_THREADS=2        — override concurrency (default 2)
      SF_USER_AGENT=<string>  — override UA
      SF_JS_RENDER=1          — enable JS rendering (slower, works on SPAs)
      SF_RESPECT_ROBOTS=0     — ignore robots.txt (only for authorized audits)
      SF_EXCLUDE_PARAMS=1     — skip URLs with query strings (faceted nav)
    """
    ua = os.environ.get("SF_USER_AGENT", "").strip() or _DEFAULT_UA
    max_threads = os.environ.get("SF_MAX_THREADS", "").strip() or "2"
    js_render = os.environ.get("SF_JS_RENDER", "").strip() in ("1", "true", "yes")
    respect_robots = os.environ.get("SF_RESPECT_ROBOTS", "1").strip() not in ("0", "false", "no")
    exclude_params = os.environ.get("SF_EXCLUDE_PARAMS", "").strip() in ("1", "true", "yes")

    tmp_dir = tempfile.mkdtemp(prefix="sf_audit_")
    try:
        cmd = [SF_CLI, "--headless", "--crawl", url,
               "--output-folder", tmp_dir,
               "--export-tabs", "Internal:HTML",
               "--overwrite",
               "--config-option", "crawler.check_images=false",
               "--config-option", "crawler.check_css=false",
               "--config-option", "crawler.check_js=false",
               "--config-option", "crawler.check_swf=false",
               "--config-option", "crawler.check_external_links=false",
               "--config-option", f"spider.user_agent={ua}",
               "--config-option", f"spider.max_threads={int(max_threads)}",
               "--config-option", f"spider.respect_robots_txt={'true' if respect_robots else 'false'}"]
        if js_render:
            cmd += ["--config-option", "spider.js_rendering_enabled=true"]
        if exclude_params:
            # Skip URLs with any ?query — kills faceted-nav loops.
            cmd += ["--config-option", "spider.exclude=.*\\?.*"]
        if max_urls:
            cmd += ["--config-option", f"crawler.max_urls={int(max_urls)}"]
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


def _get_dataframe_with_tag(live_url):
    """SF first; fall back to Python crawler on any failure.

    Returns (df, crawler_used) so the caller can record which crawler
    actually produced the data.
    """
    max_urls = os.environ.get("SF_MAX_URLS", "").strip()
    max_urls = int(max_urls) if max_urls.isdigit() else None
    if SF_AVAILABLE:
        try:
            return _sf_crawl(live_url, max_urls=max_urls), "screaming-frog"
        except Exception as exc:
            print(f"[pipeline] SF failed, falling back to Python crawler: {exc}")
    rows = crawler.crawl(live_url)
    return pd.DataFrame(rows), "python"


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
    reps = sf_csv.representative_pages(df, custom_patterns=page_type_patterns)

    psi_live = manual_psi or pagespeed.fetch_many(reps, "mobile", psi_key)
    psi_rows = observations.psi_to_observations(psi_live) if psi_live else []

    live_url_norm = live_url if live_url.endswith("/") else live_url + "/"
    site = parameters.evaluate(df, live_url_norm)
    site_obs = [{"category": i["category"], "observation": i["observation"],
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
    return {
        "sheet_url":    sheet_url,
        "metrics":      metrics_snap,
        "observations": len(rows),
        "client_name":  client_name,
        "crawler":      _crawler_used,
    }
