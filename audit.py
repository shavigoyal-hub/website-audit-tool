#!/usr/bin/env python3
"""Website Audit Tool : generate a technical SEO/UX audit of a client's live site.

Usage:
    export PAGESPEED_API_KEY=...
    python audit.py clients/endeavorfg.json
    python audit.py clients/endeavorfg.json --no-psi   # skip PageSpeed (faster)

Output: output/<client>_audit.xlsx  (upload to Drive -> opens as a Google Sheet)
"""
import argparse
import json
import os
import sys

from audit import config as cfg_mod
from audit import sf_csv, pagespeed, observations, report_xlsx, html_checks, parameters


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="path to clients/<name>.json")
    ap.add_argument("--no-psi", action="store_true", help="skip PageSpeed Insights calls")
    ap.add_argument("--api-key", default=os.environ.get("PAGESPEED_API_KEY"))
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    client = cfg["client"]
    print(f"== Auditing {client} ({cfg['live_url']}) ==")

    # 1. Load CSV. df_raw = the untouched export (for the "complete internal all"
    #    tab); df = observation scope (feeds + system + cdn-cgi removed).
    import pandas as pd
    df_raw = pd.read_csv(cfg["sf_internal_all_csv"], dtype=str, keep_default_na=False, low_memory=False)
    df_raw.columns = [c.strip() for c in df_raw.columns]
    df = sf_csv.load(cfg["sf_internal_all_csv"], exclude_patterns=cfg["exclude_url_patterns"])
    print(f"   rows: {len(df_raw)} total (raw export), {len(df)} in observation scope "
          f"(excluded patterns: {cfg['exclude_url_patterns']})")

    # 2. CSV checks
    findings = sf_csv.run_checks(df, df, has_images_csv=bool(cfg.get("sf_images_csv")))
    for f in findings:
        if f["count"]:
            print(f"   [csv] {f['key']}: {f['count']}")

    # SEO-page representatives (feeds, system & non-SEO pages already excluded)
    reps = sf_csv.representative_pages(df)

    # 3. PageSpeed on representative page types (live; mockup backend-only)
    psi_live, psi_mockup = {}, {}
    psi_rows, psi_passed = [], []
    if not args.no_psi:
        print(f"   page types -> {json.dumps(reps, indent=0)[:400]}")
        psi_live = pagespeed.fetch_many(reps, cfg["pagespeed_strategy"], args.api_key)
        for pt, r in psi_live.items():
            if r.get("error"):
                print(f"   [psi] {pt}: ERROR {r['error'][:80]}")
            else:
                print(f"   [psi] {pt}: perf={r['performance_score']} LCP={r['lcp_s']}s "
                      f"CLS={r['cls']} TBT={r['tbt_ms']}ms")
        psi_rows = observations.psi_to_observations(psi_live)
        _, psi_passed = observations.psi_status(psi_live)

        # Backend-only mockup comparison (logged, never shown in the sheet)
        if cfg.get("mockup_url"):
            mock_reps = {pt: cfg["mockup_url"] for pt in ["Homepage"] if pt in psi_live}
            psi_mockup = pagespeed.fetch_many(mock_reps, cfg["pagespeed_strategy"], args.api_key)
            _log_backend_compare(psi_live, psi_mockup)

    # 3b. Render-time checks (structured data + fetch-and-render) on the same pages
    html_result = html_checks.analyze(reps)
    render_obs, render_passed = observations.render_rows(html_result)
    for p in html_result["pages"]:
        if p.get("ok"):
            print(f"   [html] {p['type']}: schema={p['schema']} text={p['text_chars']}c")
    cro_obs = observations.cro_rows(cfg.get("cro_observations"))

    # 3c. Site-level + live parameters (presence, robots, sitemap, favicon,
    #     www/http redirects, multiple title/meta, alt text, soft 404, crawl budget)
    site = parameters.evaluate(df, reps, cfg["live_url"])
    site_obs = [{"category": i["category"], "observation": i["observation"],
                 "priority": i["priority"], "impact": i["impact"], "reference": i["reference"]}
                for i in site["issues"]]
    for i in site["issues"]:
        print(f"   [site] ISSUE {i['key']}")

    # 4. Build observation rows
    rows, notes = observations.build_rows(findings, psi_rows, render_obs + cro_obs + site_obs)
    notes.extend(f"Not evaluated : {x}" for x in site["na"])
    print(f"   -> {len(rows)} observations")

    # 5. Evidence tabs
    evidence_tabs = [f["evidence"] for f in findings if f.get("evidence")]

    # 5b. "Checks Passed" tab : every parameter tested that came back clean
    fired_csv = {f["key"] for f in findings if f["count"] > 0}
    passed = observations.build_passed_tab(fired_csv, psi_passed, render_passed)
    passed.extend([p] for p in site["passed"])   # site-level + live passes
    evidence_tabs.append(("Checks Passed", ["Parameter tested : no issues found"], passed))

    # 6. Write xlsx
    os.makedirs("output", exist_ok=True)
    out = os.path.join("output", f"{client}_audit.xlsx")
    report_xlsx.build(out, client, rows, notes, df_raw, evidence_tabs)
    print(f"== wrote {out} ==")

    # dump a JSON sidecar for the Drive-upload step
    side = os.path.join("output", f"{client}_audit.json")
    with open(side, "w") as f:
        json.dump({"client": client, "xlsx": out, "rows": rows, "notes": notes,
                   "passed": passed, "html": html_result,
                   "psi_live": psi_live, "psi_mockup": psi_mockup}, f, indent=2, default=str)
    print(f"== wrote {side} ==")


def _log_backend_compare(live, mock):
    print("   --- BACKEND ONLY: live vs our mockup (not shown in sheet) ---")
    home_live = live.get("Homepage")
    home_mock = next(iter(mock.values()), None)
    if home_live and home_mock and not home_mock.get("error"):
        print(f"   homepage perf:  live={home_live.get('performance_score')}  mockup={home_mock.get('performance_score')}")
        print(f"   homepage LCP:   live={home_live.get('lcp_s')}s  mockup={home_mock.get('lcp_s')}s")
        print(f"   homepage CLS:   live={home_live.get('cls')}  mockup={home_mock.get('cls')}")


if __name__ == "__main__":
    sys.exit(main())
