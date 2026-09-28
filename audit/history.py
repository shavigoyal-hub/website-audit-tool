"""Append-only run history persisted to a shared Google Sheet.

A single sheet called "Gushwork Audit History" holds one row per audit
run. Columns: Timestamp | Client | Live URL | Sheet URL | Deck URL | PDF URL.
The `/run` handler appends a new row (Deck URL / PDF URL blank) and
`/build-deck` finds the row by Sheet URL and writes the Deck / PDF URLs
into it.

Persistence strategy on Vercel: module-level cache holds the sheet id
within a warm lambda; cold starts pay one Drive search-by-name call.
"""
import datetime as _dt
import os

from audit.composio_exec import execute as _cx

HISTORY_TITLE = "Gushwork Website Audit Tool — History"
HISTORY_TAB   = "History"

# Baked-in default so the tool works on Vercel without needing the
# HISTORY_SHEET_ID env var to be set. This is the sheet the Composio
# connection ca_oa9LRo81KEjq can actually read+write. Env var still wins.
DEFAULT_HISTORY_SHEET_ID = "1jvOZDxco-kf85UbqQOOoPFV5QwL0JGSPmZMViOtG7E4"

_HEADER = ["Timestamp (UTC)", "Client", "Live URL",
           "Sheet URL", "Deck URL", "PDF URL",
           "Pages", "Composio Calls", "PSI Calls", "Est Cost USD"]

# Cache the found sheet id so we don't Drive-search every request.
_CACHED_ID = None


def _find_history_sheet():
    """Return the sheet id, searching Drive first, else creating a fresh one."""
    global _CACHED_ID
    if _CACHED_ID:
        return _CACHED_ID
    # Env override takes precedence
    env_id = os.environ.get("HISTORY_SHEET_ID", "").strip()
    if env_id:
        _CACHED_ID = env_id
        return env_id
    # Baked-in default (works on Vercel without needing env var configured).
    if DEFAULT_HISTORY_SHEET_ID:
        _CACHED_ID = DEFAULT_HISTORY_SHEET_ID
        return DEFAULT_HISTORY_SHEET_ID
    # Search Drive
    try:
        resp = _cx("GOOGLEDRIVE_FIND_FILE", {
            "query": f"name = '{HISTORY_TITLE}' and trashed = false and "
                     f"mimeType = 'application/vnd.google-apps.spreadsheet'",
        })
        files = (resp.get("files") if isinstance(resp, dict) else None) or []
        if files:
            _CACHED_ID = files[0].get("id") or files[0].get("fileId")
            if _CACHED_ID:
                return _CACHED_ID
    except Exception as exc:
        print(f"[history] find failed: {exc}")
    # Create new
    try:
        created = _cx("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {
            "file_name": HISTORY_TITLE,
            "text_content": " ",
            "mime_type": "application/vnd.google-apps.spreadsheet",
        }) or {}
        sid = created.get("id") or created.get("fileId")
        if not sid:
            return None
        _CACHED_ID = sid
        # Rename tab and write header
        try:
            info = _cx("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                       {"spreadsheet_id": sid}) or {}
            first_id = (((info.get("sheets") or [{}])[0]).get("properties") or {}).get("sheetId", 0)
            _cx("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
                "spreadsheetId": sid,
                "updateSheetProperties": {
                    "properties": {"sheetId": first_id, "title": HISTORY_TAB,
                                   "gridProperties": {"frozenRowCount": 1}},
                    "fields": "title,gridProperties.frozenRowCount",
                },
            })
        except Exception as exc:
            print(f"[history] rename failed: {exc}")
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid,
            "sheet_name": HISTORY_TAB,
            "first_cell_location": "A1",
            "valueInputOption": "USER_ENTERED",
            "values": [_HEADER],
        })
        # Share with the org
        try:
            _cx("GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE", {
                "file_id": sid, "role": "writer", "type": "domain",
                "domain": "gushwork.ai", "sendNotificationEmail": False,
            })
        except Exception:
            pass
        return sid
    except Exception as exc:
        print(f"[history] create failed: {exc}")
        return None


def get_url():
    sid = _find_history_sheet()
    return f"https://docs.google.com/spreadsheets/d/{sid}" if sid else None


def _read_rows(sid):
    try:
        resp = _cx("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": [f"{HISTORY_TAB}!A1:J"],
        })
    except Exception as exc:
        print(f"[history] read failed: {exc}")
        return []
    ranges = (resp.get("valueRanges") if isinstance(resp, dict) else None) or []
    return (ranges[0].get("values") or []) if ranges else []


def _next_free_row(sid):
    rows = _read_rows(sid)
    return len(rows) + 1 if rows else 1


def append_run(client, live_url, sheet_url, metrics=None):
    """Append a fresh row for a completed /run.

    `metrics` is the audit.metrics.snapshot() dict; if provided the row also
    carries page-crawled count, per-service call counts, and estimated cost.
    """
    sid = _find_history_sheet()
    if not sid:
        return None
    row_num = _next_free_row(sid)
    ts = _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    counts = (metrics or {}).get("counts") or {}
    cost   = (metrics or {}).get("est_cost_usd") or ""
    try:
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid, "sheet_name": HISTORY_TAB,
            "first_cell_location": f"A{row_num}",
            "valueInputOption": "USER_ENTERED",
            "values": [[ts, client, live_url, sheet_url, "", "",
                        counts.get("pages_crawled", ""),
                        counts.get("composio_calls", ""),
                        counts.get("psi_calls", ""),
                        cost]],
        })
        return row_num
    except Exception as exc:
        print(f"[history] append failed: {exc}")
        return None


def update_deck(sheet_url, deck_url="", pdf_url=""):
    """Find the row matching sheet_url and write Deck URL / PDF URL into it."""
    sid = _find_history_sheet()
    if not sid or not sheet_url:
        return False
    rows = _read_rows(sid)
    # Find last row whose col D (index 3) matches sheet_url
    match_row = None
    for i, row in enumerate(rows):
        if len(row) > 3 and str(row[3]).strip() == sheet_url.strip():
            match_row = i + 1  # Sheets 1-indexed
    if not match_row:
        return False
    try:
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid, "sheet_name": HISTORY_TAB,
            "first_cell_location": f"E{match_row}",
            "valueInputOption": "USER_ENTERED",
            "values": [[deck_url or "", pdf_url or ""]],
        })
        return True
    except Exception as exc:
        print(f"[history] update deck failed: {exc}")
        return False


def list_recent(n=25):
    """Return the last N rows (newest first) as list of dicts."""
    sid = _find_history_sheet()
    if not sid:
        return []
    rows = _read_rows(sid)
    if not rows:
        return []
    out = []
    for r in rows[1:]:
        while len(r) < 10:
            r.append("")
        out.append({
            "timestamp": r[0], "client": r[1], "live_url": r[2],
            "sheet_url": r[3], "deck_url": r[4], "pdf_url": r[5],
            "pages": r[6], "composio_calls": r[7],
            "psi_calls": r[8], "cost_usd": r[9],
        })
    out.reverse()
    return out[:n]
