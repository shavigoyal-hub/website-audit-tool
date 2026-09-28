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


def _sf_crawl(url):
    tmp_dir = tempfile.mkdtemp(prefix="sf_audit_")
    try:
        subprocess.run(
            [SF_CLI, "--headless", "--crawl", url,
             "--output-folder", tmp_dir,
             "--export-tabs", "Internal:All",
             "--overwrite"],
            check=True, timeout=600,
        )
        matches = glob.glob(os.path.join(tmp_dir, "internal_all.csv"))
        if not matches:
            raise FileNotFoundError("Crawl finished but internal_all.csv missing.")
        df = pd.read_csv(matches[0], dtype=str, keep_default_na=False,
                         low_memory=False)
        df.columns = [c.strip() for c in df.columns]
        return df
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _get_dataframe(live_url):
    if SF_AVAILABLE:
        return _sf_crawl(live_url)
    rows = crawler.crawl(live_url)
    return pd.DataFrame(rows)


def run(live_url):
    """Full audit pipeline. Returns dict with sheet_url + metrics."""
    metrics.reset()
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

    df_raw = _get_dataframe(live_url)
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
        "crawler":      "screaming-frog" if SF_AVAILABLE else "python",
    }
