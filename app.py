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

from audit import crawler, observations, pagespeed, parameters, report_xlsx, report_sheets, report_pdf, deck_html, sf_csv, history, metrics, jobs, pipeline
from audit.version import VERSION

app = Flask(__name__)


class _MountPrefix:
    """Serve the app under /audit as well as at the root.

    The SEO Reporting tool mounts this app at /audit (a Next.js rewrite), so
    the audit sits behind that tool's Google login and inside its upsell
    flow. Requests arriving as /audit/... are served as if at the root, with
    SCRIPT_NAME set, so request.script_root is "/audit" and every link the
    page builds keeps the prefix. Direct visits to this app are unchanged.
    """
    PREFIX = "/audit"

    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "") or "/"
        if path == self.PREFIX or path.startswith(self.PREFIX + "/"):
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + self.PREFIX
            environ["PATH_INFO"] = path[len(self.PREFIX):] or "/"
        return self.wsgi(environ, start_response)


app.wsgi_app = _MountPrefix(app.wsgi_app)
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
    """Enqueue an audit — the local worker (worker.py) drains the queue.

    Pass sync=1 in the form to bypass the queue and run inline (used for
    ad-hoc local testing where you don't want the worker running).
    """
    try:
        live_url = request.form.get("live_url", "").strip()
        if not live_url:
            return jsonify({"error": "Live URL is required."}), 400

        sync = request.form.get("sync", "").lower() in ("1", "true", "yes", "on")

        m = re.match(r"https?://(?:www\.)?([^/]+)", live_url)
        domain = m.group(1) if m else live_url
        client_name = re.sub(r"\.[^.]+$", "", domain).replace(".", "_").lower()

        if sync:
            result = pipeline.run(live_url)
            resp = {
                "ok": True, "version": VERSION,
                "observations": result["observations"],
                "sheet_url": result.get("sheet_url"),
                "metrics": result["metrics"],
                "crawler": result["crawler"],
                "message": f"Audit complete — {result['observations']} observations found.",
            }
            return jsonify(resp)

        jid = jobs.enqueue(client_name, live_url)
        if not jid:
            return jsonify({
                "error": "Could not enqueue job — history sheet unreachable.",
            }), 500
        return jsonify({
            "ok": True, "version": VERSION,
            "job_id": jid,
            "poll_url": f"{request.script_root}/job/{jid}",
            "message": "Queued for local worker.",
        })
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/job/<jid>")
def job_status(jid):
    """Job status by id. If the row isn't found (warm-lambda cache miss,
    Sheets read latency, or a genuinely wrong id), return a soft pending
    response with `note` set so the UI keeps polling instead of showing
    a scary 'unknown job' error. After ~2 min the front-end times out on
    its own.
    """
    j = jobs.get(jid)
    if not j:
        return jsonify({
            "id": jid,
            "status": "pending",
            "live_url": "",
            "worker": "",
            "sheet_url": "",
            "note": "Waiting for the row to become visible…",
        })
    return jsonify(j)


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
            from audit.composio_exec import LAST_TRACE as _trace
            return jsonify({
                "error": "Could not read sheet.",
                "sheet_error": getattr(report_sheets, "READ_LAST_ERROR", "") or "unknown",
                "composio_debug": {"trace": _trace[-6:]},
            }), 400
        meta = data.get("meta") or {}
        obs_rows = data["obs_rows"]

        # Form overrides (plan/current_spend/sell_price optional for the deck)
        for k in ("plan", "current_spend", "sell_price"):
            v = request.form.get(k, "").strip()
            if v:
                meta[k] = v

        # Derive client display — prefer sheet title ("<Client> SEO Audit — <date>"),
        # then live URL from Meta, then fallback.
        import datetime, re
        client_display = None
        try:
            from audit.report_sheets import _extract_sheet_id
            from audit.composio_exec import execute as _cx
            sid = _extract_sheet_id(sheet_url)
            if sid:
                info = _cx("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                          {"spreadsheet_id": sid}) or {}
                title = (info.get("properties") or {}).get("title", "")
                m = re.match(r"^(.*?)\s+SEO Audit", title)
                if m:
                    client_display = m.group(1).strip()
        except Exception as exc:
            print(f"[deck] get sheet title failed: {exc}")
        if not client_display or "." not in client_display:
            # Fallback: scan the sheet's URLs to find the real host
            found_urls = []
            for r in obs_rows:
                for line in (r.get("found") or "").split("\n"):
                    m2 = re.match(r"https?://([^/\s|]+)", line.strip())
                    if m2:
                        found_urls.append(m2.group(1))
            if found_urls:
                # Pick the most common host (strip www.)
                from collections import Counter
                host = Counter(h.lower().lstrip("www.") for h in found_urls).most_common(1)[0][0]
                client_display = host
            else:
                live = meta.get("live_url") or ""
                m = re.match(r"https?://(?:www\.)?([^/]+)", live)
                client_display = m.group(1) if m else (client_display or "Audit")

        os.makedirs(OUTPUT_ROOT, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", client_display.lower()) or "audit"
        html_name = f"{slug}_deck.html"
        html_path = os.path.join(OUTPUT_ROOT, html_name)
        try:
            html_body = deck_html.render(obs_rows, client_display, meta=meta)
            with open(html_path, "w") as fh:
                fh.write(html_body)
        except Exception:
            return jsonify({
                "error": "Deck HTML render failed.",
                "traceback": traceback.format_exc()[:2000],
            }), 500

        # On-the-fly deck URL — Vercel's /tmp file isn't reachable from the
        # next request, so we point at /deck?sheet=… which re-renders live.
        from urllib.parse import quote
        # Built on the host AND the mount prefix the request came through, so
        # a deck made inside SEO Reporting opens inside it too.
        deck_url = (request.host_url.rstrip("/") + request.script_root
                    + f"/deck?sheet={quote(sheet_url, safe=':/?&=')}")
        resp = {
            "ok": True,
            "version": VERSION,
            "deck_url": deck_url,
            "message": f"Deck built ({len(obs_rows)} pages).",
        }
        try:
            history.update_deck(sheet_url, deck_url, "")
        except Exception as exc:
            print(f"[history] update_deck failed: {exc}")
        return jsonify(resp)
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/append-finding", methods=["POST"])
def append_finding_route():
    """Append manual findings to the reviewed sheet.

    Body: sheet_url + prompt (one finding per line, each "<url> <label>" or
    just "<label>"). Each line is audited independently via live_check and
    inserted into the next blank row above the Ending row.
    """
    try:
        sheet_url = request.form.get("sheet_url", "").strip()
        prompt = request.form.get("prompt", "").strip()
        category = request.form.get("category", "").strip() or None

        if not sheet_url:
            return jsonify({"error": "sheet_url required"}), 400
        if not prompt and not request.files:
            return jsonify({"error": "prompt or image required"}), 400

        # Upload any attached screenshots to Drive → public URLs.
        image_urls = []
        from audit.drive_upload import upload_image
        for fs in request.files.getlist("images"):
            content = fs.read()
            if not content:
                continue
            url = upload_image(fs.filename or "screenshot.png", content,
                                mime_type=fs.mimetype or "image/png")
            if url:
                image_urls.append(url)
                print(f"[chatbot] uploaded {fs.filename} -> {url}")
            else:
                print(f"[chatbot] upload failed for {fs.filename}")

        from audit.live_check import audit_url
        from audit.llm_frame import frame as _llm_frame

        # Merge lines into (url, hint) pairs. Rules:
        #   "URL description..."     -> one pair
        #   "URL" then "description" -> one pair (previous URL adopts next line)
        #   "URL" alone at end       -> pair with empty hint (audit_url auto-detects)
        #   "description" alone      -> pair with no url (uses hint verbatim)
        raw_lines = [l.strip() for l in prompt.splitlines() if l.strip()]
        # If the user only attached images with no text, create a single
        # placeholder pair so the images actually land on a row.
        if not raw_lines and image_urls:
            raw_lines = ["Screenshot attached — reviewer note"]
        pairs = []
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]
            m = re.match(r"(https?://\S+)(?:\s+(.+))?$", line)
            if m:
                url = m.group(1).strip().rstrip(".,;")
                hint = (m.group(2) or "").strip()
                # Adopt the next non-URL line as the description
                if not hint and i + 1 < len(raw_lines) and not raw_lines[i + 1].startswith(("http://", "https://")):
                    hint = raw_lines[i + 1].strip()
                    i += 1
                pairs.append((url, hint))
            else:
                pairs.append(("", line))
            i += 1

        results = []
        errors = []
        for url, hint in pairs:
            line = f"{url} {hint}".strip()
            # 1. Static rule check + on-page detection (fetches URL if given).
            analysis = audit_url(url, hint) if url else {
                "key": "", "label": (hint or "Custom")[:60], "url": "",
                "evidence": "no URL supplied — recorded as manual note",
                "detected": [],
            }
            row_label = analysis["label"]
            row_priority = "Medium"

            # 2. Ask the LLM (OpenAI first, Anthropic fallback) to phrase it.
            overrides = _llm_frame(url, hint)
            if overrides:
                analysis["framed_by"] = "llm"
                analysis["label"] = overrides.get("label") or analysis["label"]
                row_label = analysis["label"]
                row_priority = overrides.get("priority") or row_priority
                overrides.setdefault("status_label", overrides.get("label"))
                if overrides.get("verified") is False:
                    analysis["evidence"] = "LLM couldn't verify from HTML — added on your say-so"

            # Attach the uploaded screenshots to the FIRST finding row
            # (usually there's just one). Stored in overrides["support"]
            # as an IMG: marker line the deck renderer picks up.
            if image_urls and not results:
                marker = "\n".join(f"IMG: {u}" for u in image_urls)
                if overrides is None:
                    overrides = {}
                overrides["support"] = ((overrides.get("support") or "") + "\n" + marker).strip()

            row, err = report_sheets.append_finding(
                sheet_url, url, row_label, priority=row_priority,
                category=category, finding_key=analysis["key"],
                overrides=overrides)
            if err:
                errors.append({"line": line, "error": err,
                                "analysis": analysis})
            else:
                results.append({"line": line, "row": row,
                                 "analysis": analysis})

        if not results and errors:
            return jsonify({"ok": False, "errors": errors,
                            "message": errors[0]["error"]}), 400
        msg_bits = [f"row {r['row']}: {r['analysis']['label']} ({r['analysis']['evidence']})"
                    for r in results]
        return jsonify({
            "ok": True,
            "added": len(results),
            "results": results,
            "errors": errors,
            "message": f"Added {len(results)} finding(s). " + "; ".join(msg_bits),
        })
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500


@app.route("/img/<file_id>")
def drive_image_proxy(file_id):
    """Serve a Drive-hosted image (uploaded via chatbot) as raw bytes.

    Fixes the 'broken screenshot in deck' — Drive's public inline URLs
    have been flaky; proxying through Flask makes it always work.
    """
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9_-]{10,64}", file_id):
        return "bad file id", 400
    from audit.drive_upload import fetch_bytes
    body, mime = fetch_bytes(file_id)
    if not body:
        return "not found", 404
    from flask import Response
    return Response(body, mimetype=(mime or "image/png"),
                    headers={"Cache-Control": "public, max-age=86400"})


@app.route("/history")
def history_route():
    """Return recent audit runs + the history sheet URL."""
    try:
        n = int(request.args.get("n", 25))
    except ValueError:
        n = 25
    return jsonify({
        "sheet_url": history.get_url(),
        "runs": history.list_recent(n),
    })


@app.route("/history-ui")
def history_ui():
    """Human-friendly history page. Combines Jobs (queue state) and
    History (past audits) into one sortable table so CS can find and
    reopen any past run without hunting through the Google Sheet."""
    from audit import jobs as _jobs_mod
    jobs_rows = _jobs_mod.list_recent(50)
    hist_rows = history.list_recent(50)
    # Merge on sheet_url so a completed job also carries its deck URL.
    by_sheet = {r.get("sheet_url", ""): r for r in hist_rows if r.get("sheet_url")}
    merged = []
    seen_sheets = set()
    for j in jobs_rows:
        row = dict(j)
        sheet_url = j.get("sheet_url", "")
        if sheet_url and sheet_url in by_sheet:
            row["deck_url"] = by_sheet[sheet_url].get("deck_url", "")
            seen_sheets.add(sheet_url)
        merged.append(row)
    for h in hist_rows:
        if h.get("sheet_url") in seen_sheets:
            continue
        merged.append({
            "id": "",
            "created_utc": h.get("timestamp") or "",
            "client": h.get("client") or "",
            "live_url": h.get("live_url") or "",
            "status": "done",
            "worker": "",
            "sheet_url": h.get("sheet_url") or "",
            "deck_url": h.get("deck_url") or "",
            "pages": h.get("pages") or "",
            "crawler": "",
            "cost_usd": h.get("cost_usd") or "",
        })
    return render_template("history.html", runs=merged,
                           jobs_sheet_url=_jobs_mod.get_url() if hasattr(_jobs_mod, "get_url") else "")


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
        info["composio_ready"] = bool(os.environ.get("COMPOSIO_API_KEY"))
    except Exception as exc:
        info["composio_error"] = str(exc)[:200]
    try:
        from audit.report_sheets import _credentials as _sheets_creds, LAST_ERROR as _sheets_last
        info["sheets_ready"] = _sheets_creds() is not None
        if _sheets_last:
            info["sheets_last_error"] = _sheets_last
    except Exception as exc:
        info["sheets_ready"] = False
        info["sheets_error"] = str(exc)[:200]
    return jsonify(info)


@app.route("/deck/<path:filename>")
def deck_file(filename):
    """Legacy path — the pre-baked file may not survive Vercel's per-request
    /tmp. Fall back to reading the sheet URL passed as ?sheet= or from the
    session's last-build record.
    """
    sheet_url = request.args.get("sheet", "").strip()
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    abs_path = os.path.join(OUTPUT_ROOT, filename)
    if os.path.exists(abs_path):
        return send_file(abs_path, as_attachment=False, mimetype="text/html")
    # Fallback — render on the fly if a sheet_url is provided
    if sheet_url:
        return deck_render(sheet_url)
    return jsonify({
        "error": f"Deck not on this instance (Vercel /tmp is per-request).",
        "fix": "Re-open from the build result — the URL now includes ?sheet=… for on-the-fly rendering.",
    }), 404


@app.route("/deck")
def deck_render(sheet_url=None):
    """Render the deck HTML on-the-fly from a Google Sheet URL.

    Vercel serverless doesn't persist /tmp files between requests, so serving
    a pre-built .html blows up. Instead we re-read the sheet + re-render.
    """
    sheet_url = sheet_url or request.args.get("sheet", "").strip()
    if not sheet_url:
        return jsonify({"error": "Missing ?sheet=<google sheet url>"}), 400
    data = report_sheets.read_for_deck(sheet_url)
    if not data:
        return jsonify({
            "error": "Could not read sheet.",
            "sheet_error": getattr(report_sheets, "READ_LAST_ERROR", "") or "unknown",
        }), 400
    obs_rows = data["obs_rows"]
    meta = data.get("meta") or {}
    # Derive client from sheet title (as /build-deck does)
    import re
    client_display = None
    try:
        from audit.report_sheets import _extract_sheet_id
        from audit.composio_exec import execute as _cx
        sid = _extract_sheet_id(sheet_url)
        if sid:
            info = _cx("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                      {"spreadsheet_id": sid}) or {}
            title = (info.get("properties") or {}).get("title", "")
            # Handles both new format "Foo Bar — SEO Audit (2026-09-11)"
            # and the older "foo.com SEO Audit — 2026-09-11".
            m = re.match(r"^(.+?)\s+(?:—|-)\s+SEO Audit", title) \
                or re.match(r"^(.+?)\s+SEO Audit", title)
            if m:
                client_display = m.group(1).strip()
    except Exception:
        pass
    if not client_display or "." not in client_display:
        # Fallback: pull the real host from URLs in the sheet.
        found_urls = []
        for r in obs_rows:
            for line in (r.get("found") or "").split("\n"):
                m2 = re.match(r"https?://([^/\s|]+)", line.strip())
                if m2:
                    found_urls.append(m2.group(1))
        if found_urls:
            from collections import Counter
            host = Counter(h.lower().lstrip("www.") for h in found_urls).most_common(1)[0][0]
            client_display = host
        elif not client_display:
            client_display = "Audit"
    html_body = deck_html.render(obs_rows, client_display, meta=meta)
    return html_body, 200, {"Content-Type": "text/html; charset=utf-8"}


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
