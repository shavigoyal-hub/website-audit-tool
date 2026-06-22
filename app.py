"""Flask web app — wraps the CLI audit tool for Vercel hosting."""
import json
import os
import tempfile
import traceback

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for

from audit import config as cfg_mod, observations, pagespeed, parameters, report_xlsx, sf_csv

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_audit():
    try:
        client_name = request.form.get("client_name", "").strip().lower().replace(" ", "_")
        live_url = request.form.get("live_url", "").strip()
        exclude_raw = request.form.get("exclude_patterns", "").strip()
        psi_key = request.form.get("psi_key", "").strip() or os.environ.get("PAGESPEED_API_KEY")
        no_psi = not bool(psi_key)

        if not client_name or not live_url:
            return jsonify({"error": "Client name and live URL are required."}), 400

        csv_file = request.files.get("csv_file")
        if not csv_file or csv_file.filename == "":
            return jsonify({"error": "Screaming Frog Internal All CSV is required."}), 400

        # Parse exclude patterns
        exclude_patterns = [p.strip() for p in exclude_raw.split(",") if p.strip()] if exclude_raw else []

        # Save uploaded CSV to a temp file
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            csv_file.save(tmp.name)
            tmp_csv_path = tmp.name

        try:
            cfg = {
                "client": client_name,
                "live_url": live_url if live_url.endswith("/") else live_url + "/",
                "sf_internal_all_csv": tmp_csv_path,
                "exclude_url_patterns": exclude_patterns,
                "pagespeed_strategy": "mobile",
                "manual_psi": None,
                "page_type_patterns": None,
                "cro_observations": [],
            }

            import pandas as pd
            df_raw = pd.read_csv(tmp_csv_path, dtype=str, keep_default_na=False, low_memory=False)
            df_raw.columns = [c.strip() for c in df_raw.columns]
            df = sf_csv.load(tmp_csv_path, exclude_patterns=exclude_patterns)

            findings = sf_csv.run_checks(df, df, has_images_csv=False)
            reps = sf_csv.representative_pages(df)

            psi_live, psi_rows, psi_passed = {}, [], []
            if not no_psi:
                psi_live = pagespeed.fetch_many(reps, "mobile", psi_key)
                psi_rows = observations.psi_to_observations(psi_live)
                _, psi_passed = observations.psi_status(psi_live)

            site = parameters.evaluate(df, cfg["live_url"])
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

        finally:
            os.unlink(tmp_csv_path)

    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/download/<path:filepath>")
def download(filepath):
    abs_path = os.path.join(os.getcwd(), filepath)
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found"}), 404
    return send_file(abs_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
