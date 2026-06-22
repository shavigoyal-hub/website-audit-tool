"""Flask web app — wraps the CLI audit tool for Vercel hosting."""
import glob
import json
import os
import re
import subprocess
import tempfile
import traceback

from flask import Flask, jsonify, render_template, request, send_file

from audit import observations, pagespeed, parameters, report_xlsx, sf_csv

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

SF_CLI = "/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher"


def _crawl_with_sf(url, output_dir):
    """Run a headless Screaming Frog crawl and return path to internal_all.csv."""
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
        raise FileNotFoundError("Crawl finished but internal_all.csv not found in output folder.")
    return matches[0]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_audit():
    tmp_dir = None
    try:
        live_url = request.form.get("live_url", "").strip()
        mockup_url = request.form.get("mockup_url", "").strip()

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

        # Crawl via Screaming Frog — no manual CSV needed
        tmp_dir = tempfile.mkdtemp(prefix="sf_audit_")
        csv_path = _crawl_with_sf(live_url, tmp_dir)

        import pandas as pd
        df_raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False, low_memory=False)
        df_raw.columns = [c.strip() for c in df_raw.columns]
        df = sf_csv.load(csv_path, exclude_patterns=exclude_patterns)

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

        os.makedirs("output", exist_ok=True)
        out_path = os.path.join("output", f"{client_name}_audit.xlsx")
        report_xlsx.build(out_path, client_name, rows, notes, df_raw, evidence_tabs)

        return jsonify({
            "ok": True,
            "observations": len(rows),
            "xlsx": out_path,
            "message": f"Audit complete — {len(rows)} observations found.",
        })

    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500

    finally:
        if tmp_dir:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route("/download/<path:filepath>")
def download(filepath):
    abs_path = os.path.join(os.getcwd(), filepath)
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found"}), 404
    return send_file(abs_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
