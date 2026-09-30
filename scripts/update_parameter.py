"""Apply a batch of parameter edits.

Called by the /chat endpoint when the LLM router classifies a user
message as edit_parameter.

Strategy — resilient across environments:
  1. ALWAYS update the master Google Sheet via Composio (durable, works
     on Vercel serverless where the local FS is ephemeral and no git).
  2. Also update parameters_data.json locally + git commit + push when
     possible (worker's Mac). Best-effort — silent skip on Vercel.

Worker syncs sheet→JSON periodically anyway (see worker.py periodic
sync), so step 1 alone is sufficient for the change to reach audits.
"""
import json
import os
import subprocess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JSON = os.path.join(_ROOT, "parameters_data.json")
_MASTER_SHEET_ID = "16aJEm6EuHVDvu2yw0EnHMjXflxUdgJjfbDtIMBkNDyY"

# Sheet columns (matches dump_parameters_sheet.py):
# A Key | B Label | C Priority | D Primary signal | E Hook stat |
# F Hook context | G Costs | H Support | I In lead-sum
_FIELD_TO_COL = {
    "label":         "B",
    "priority":      "C",
    "primary_signal": "D",
    "hook_stat":     "E",
    "hook_ctx":      "F",
    "costs":         "G",
    "support":       "H",
    "in_lead_sum":   "I",
}


def _load():
    if not os.path.exists(_JSON):
        return {}
    try:
        with open(_JSON, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save(data):
    try:
        with open(_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        return True
    except Exception as exc:
        print(f"[update_parameter] local save failed: {exc}")
        return False


def _git(*args, timeout=30):
    return subprocess.run(["git", *args], cwd=_ROOT, timeout=timeout,
                          capture_output=True, text=True)


def _update_sheet(edits):
    """Push edits to the master Google Sheet Parameters tab. Composio-backed.

    Returns True on success. Never raises. Skips silently if COMPOSIO_API_KEY
    is missing.
    """
    if not os.environ.get("COMPOSIO_API_KEY"):
        return False
    try:
        from audit.report_sheets import _composio_execute, _extract_first_range
        # Fetch the Key column to find each row number for a given key.
        resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": _MASTER_SHEET_ID,
            "ranges": ["Parameters!A1:A500"],
        })
        rows = _extract_first_range(resp) or []
        key_to_row = {}
        for i, r in enumerate(rows, start=1):
            if r and str(r[0]).strip():
                key_to_row[str(r[0]).strip()] = i
        # One BATCH_UPDATE per cell (few edits per call — cheap).
        ok_count = 0
        for e in edits:
            row = key_to_row.get(e["key"])
            col = _FIELD_TO_COL.get(e["field"])
            if not row or not col:
                continue
            _composio_execute("GOOGLESHEETS_BATCH_UPDATE", {
                "spreadsheet_id": _MASTER_SHEET_ID,
                "sheet_name": "Parameters",
                "first_cell_location": f"{col}{row}",
                "valueInputOption": "USER_ENTERED",
                "values": [[e["value"]]],
            })
            ok_count += 1
        return ok_count > 0
    except Exception as exc:
        print(f"[update_parameter] sheet update failed: {exc}")
        return False


def apply_edits(edits):
    """Apply {key, field, value} edits to sheet + local JSON + git.

    Returns {ok, applied, message}. ok=True even when git push is skipped
    (Vercel) — sheet update alone is sufficient given worker's sheet sync.
    """
    if not edits:
        return {"ok": False, "message": "no edits given"}

    applied = [f"{e['key']}.{e['field']} → {e['value']}" for e in edits]
    summary = "; ".join(applied[:3])
    if len(applied) > 3:
        summary += f" (+{len(applied) - 3} more)"

    sheet_ok = _update_sheet(edits)

    # Best-effort local mirror + git push (works on worker's Mac).
    local_ok = False
    git_ok = False
    data = _load()
    for e in edits:
        row = data.setdefault(e["key"], {})
        row[e["field"]] = e["value"]
    if _save(data):
        local_ok = True
        try:
            _git("add", "parameters_data.json")
            r = _git("commit", "-m", f"params: {summary}")
            if r.returncode == 0:
                push = _git("push", "origin", "main", timeout=60)
                git_ok = (push.returncode == 0)
            elif "nothing to commit" in (r.stdout + r.stderr).lower():
                git_ok = True  # already up to date
        except Exception as exc:
            print(f"[update_parameter] git skipped: {exc}")

    parts = []
    if sheet_ok:
        parts.append("master sheet updated")
    if git_ok:
        parts.append("committed to main (worker auto-restarts)")
    elif local_ok:
        parts.append("JSON updated locally")
    if not parts:
        return {"ok": False, "applied": applied,
                "message": "Could not persist the edit anywhere (sheet + git both failed)."}
    return {"ok": True, "applied": applied,
            "message": f"Updated {summary}. " + " · ".join(parts) + "."}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4 or (len(sys.argv) - 1) % 3 != 0:
        print("usage: update_parameter.py <key> <field> <value> [<key> <field> <value> ...]")
        sys.exit(1)
    edits = []
    for i in range(1, len(sys.argv), 3):
        edits.append({"key": sys.argv[i], "field": sys.argv[i + 1],
                      "value": sys.argv[i + 2]})
    print(apply_edits(edits))
