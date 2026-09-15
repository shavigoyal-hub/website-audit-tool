"""Flask web app — wraps the CLI audit tool."""
import glob
import json
import os
import re
import subprocess
import tempfile
import traceback

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file

from audit import crawler, observations, pagespeed, parameters, report_xlsx, report_sheets, report_slides, sf_csv
from audit.version import VERSION

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

SF_CLI = "/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher"
SF_AVAILABLE = os.path.isfile(SF_CLI)

# Output directory — Vercel serverless FS is read-only except /tmp.
OUTPUT_ROOT = "/tmp/output" if os.environ.get("VERCEL") else "output"


def _crawl_with_sf(url, output_dir):
    cmd = [
        SF_CLI,
        "--headless",
        "--crawl", url,
        "--output-folder", output_dir,
        "--export-tabs", "Internal:All",
        "--overwrite",
    ]
    subprocess.run(cmd, check=True, timeout=600)
    matches = glob.glob(os.path.join(output_dir, "internal_all.csv"))
    if not matches:
        raise FileNotFoundError("Crawl finished but internal_all.csv not found.")
    return matches[0]


def _get_dataframes(live_url):
    """Return (df_raw, df) — crawl via SF if available, else Python crawler."""
    if SF_AVAILABLE:
        tmp_dir = tempfile.mkdtemp(prefix="sf_audit_")
        try:
            csv_path = _crawl_with_sf(live_url, tmp_dir)
            df_raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False, low_memory=False)
            df_raw.columns = [c.strip() for c in df_raw.columns]
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        rows = crawler.crawl(live_url)
        df_raw = pd.DataFrame(rows)

    return df_raw


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_audit():
    try:
        live_url = request.form.get("live_url", "").strip()
        mockup_url = request.form.get("mockup_url", "").strip()
        plan          = request.form.get("plan", "").strip()
        current_spend = request.form.get("current_spend", "").strip()
        sell_price    = request.form.get("sell_price", "").strip()

        if not live_url:
            return jsonify({"error": "Live URL is required."}), 400

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
            if not mockup_url:
                mockup_url = stored.get("mockup_url", "")

        df_raw = _get_dataframes(live_url)
        df = sf_csv.load_from_df(df_raw, exclude_patterns=exclude_patterns)

        status_num = pd.to_numeric(df.get("Status Code", pd.Series([], dtype=str)), errors="coerce").fillna(0).astype(int)
        total_pages = int((sf_csv.is_html(df) & (status_num == 200)).sum())
        total_images = int(sf_csv.is_image(df_raw).sum())

        findings = sf_csv.run_checks(df, df, has_images_csv=False)
        reps = sf_csv.representative_pages(df, custom_patterns=page_type_patterns)

        psi_live, psi_rows, psi_passed = {}, [], []
        if manual_psi:
            psi_live = manual_psi
            psi_rows = observations.psi_to_observations(psi_live)
            _, psi_passed = observations.psi_status(psi_live)
        elif psi_key:
            psi_live = pagespeed.fetch_many(reps, "mobile", psi_key)
            psi_rows = observations.psi_to_observations(psi_live)
            _, psi_passed = observations.psi_status(psi_live)

        live_url_norm = live_url if live_url.endswith("/") else live_url + "/"
        site = parameters.evaluate(df, live_url_norm)
        site_obs = [{"category": i["category"], "observation": i["observation"],
                     "priority": i["priority"], "impact": i["impact"], "reference": i["reference"]}
                    for i in site["issues"]]

        rows, notes = observations.build_rows(findings, psi_rows, site_obs)
        notes.extend(f"Not evaluated : {x}" for x in site["na"])

        evidence_tabs = [f["evidence"] for f in findings if f.get("evidence")]
        fired_csv = {f["key"] for f in findings if f["count"] > 0}
        passed = observations.build_passed_tab(fired_csv, psi_passed, [])
        passed.extend([p] for p in site["passed"])
        evidence_tabs.append(("Checks Passed", ["Parameter tested : no issues found"], passed))

        os.makedirs(OUTPUT_ROOT, exist_ok=True)
        xlsx_name = f"{client_name}_audit.xlsx"
        out_path = os.path.join(OUTPUT_ROOT, xlsx_name)
        report_xlsx.build(out_path, client_name, rows, notes, df_raw, evidence_tabs,
                          total_pages=total_pages, total_images=total_images)

        import datetime
        sheet_title = f"{client_name.replace('_', ' ').title()} SEO Audit — {datetime.date.today()}"
        meta = {
            "version":       VERSION,
            "generated":     datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "live_url":      live_url,
            "plan":          plan,
            "current_spend": current_spend,
            "sell_price":    sell_price,
        }
        sheet_url = report_sheets.build(
            sheet_title, rows, evidence_tabs,
            total_pages=total_pages, total_images=total_images,
            meta=meta,
        )

        resp = {
            "ok": True,
            "version": VERSION,
            "observations": len(rows),
            "xlsx": xlsx_name,
            "message": f"Audit complete — {len(rows)} observations found.",
        }
        if sheet_url:
            resp["sheet_url"] = sheet_url
            resp["message"] += (" Google Sheet created. Review it, tick "
                                "'Reviewed' in the Meta tab, then build the deck.")
        else:
            resp["warning"] = ("Sheet skipped — set COMPOSIO_API_KEY (with a "
                               "connected Google account) or GOOGLE_SERVICE_ACCOUNT_JSON "
                               "on Vercel.")
        return jsonify(resp)

    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/build-deck", methods=["POST"])
def build_deck():
    """Build the Slides deck from an existing, reviewed audit sheet.

    Requires the Meta tab's Reviewed checkbox to be ticked, unless
    `force=1` is passed. Reads plan / current_spend / sell_price from
    the Meta tab; the caller can override any of them via form fields.
    """
    try:
        sheet_url = request.form.get("sheet_url", "").strip()
        force = request.form.get("force", "").strip() in ("1", "true", "yes", "on")
        if not sheet_url:
            return jsonify({"error": "sheet_url is required"}), 400

        data = report_sheets.read_for_deck(sheet_url)
        if not data:
            return jsonify({"error": "Could not read sheet (missing Meta tab or no auth)."}), 400
        meta = data["meta"]
        obs_rows = data["obs_rows"]

        if not meta.get("reviewed") and not force:
            return jsonify({
                "error": "Sheet is not marked Reviewed. Tick the 'Reviewed' checkbox "
                         "in the Meta tab and try again, or resubmit with force=1."
            }), 409

        # Form overrides
        for k in ("plan", "current_spend", "sell_price"):
            v = request.form.get(k, "").strip()
            if v:
                meta[k] = v

        # Derive client display from live URL
        import datetime, re
        live = meta.get("live_url") or ""
        m = re.match(r"https?://(?:www\.)?([^/]+)", live)
        domain = m.group(1) if m else "audit"
        client_display = re.sub(r"\.[^.]+$", "", domain).replace(".", " ").title()

        deck_title = f"{client_display} Tech Audit — {datetime.date.today()}"
        os.makedirs(OUTPUT_ROOT, exist_ok=True)
        pdf_name = re.sub(r"[^a-z0-9]+", "_", client_display.lower()) + "_audit.pdf"
        pdf_path = os.path.join(OUTPUT_ROOT, pdf_name)
        result = report_slides.build(
            deck_title, obs_rows, client_display=client_display, meta=meta,
            pdf_out_path=pdf_path,
        )
        if not result or not result.get("slide_url"):
            return jsonify({"error": "Deck creation failed — check Composio Drive auth."}), 500

        resp = {
            "ok": True,
            "version": VERSION,
            "slide_url": result["slide_url"],
            "message": "Deck built from reviewed sheet.",
        }
        if result.get("pdf_path"):
            resp["pdf"] = pdf_name
            resp["message"] += " PDF export ready."
        return jsonify(resp)
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/health")
def health():
    """Report which auth paths are configured so we can debug on Vercel."""
    from audit import composio_auth
    info = {
        "version": VERSION,
        "composio_api_key_set":  bool(os.environ.get("COMPOSIO_API_KEY")),
        "composio_entity_id":    composio_auth._entity_id(),
        "service_account_json_set": bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")),
        "vercel": bool(os.environ.get("VERCEL")),
        "output_root": OUTPUT_ROOT,
    }
    # Try each auth path (without secrets) and record which yielded credentials.
    try:
        info["composio_credentials"] = composio_auth.get_credentials() is not None
        info["composio_debug"] = composio_auth.LAST_DEBUG
    except Exception as exc:
        info["composio_credentials"] = False
        info["composio_error"] = str(exc)[:200]
    try:
        from audit.report_sheets import _credentials as _sheets_creds, LAST_ERROR as _sheets_last
        info["sheets_credentials"] = _sheets_creds() is not None
        if _sheets_last:
            info["sheets_last_error"] = _sheets_last
    except Exception as exc:
        info["sheets_credentials"] = False
        info["sheets_error"] = str(exc)[:200]
    return jsonify(info)


@app.route("/download/<path:filename>")
def download(filename):
    # Look up by basename in the known output directory.
    # Reject anything with path separators to avoid traversal.
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    abs_path = os.path.join(OUTPUT_ROOT, filename)
    if not os.path.exists(abs_path):
        return jsonify({"error": f"File not found at {abs_path}"}), 404
    return send_file(abs_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
