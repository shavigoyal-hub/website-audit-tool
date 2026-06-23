"""Write a complete audit to a new Google Sheet and share it.

Authentication: set GOOGLE_SERVICE_ACCOUNT_JSON env var to the full JSON
of a GCP service account key that has been granted Editor access to Google
Sheets. The Sheets will be shared with AUDIT_SHARE_EMAIL (default:
shavi.goyal@gushwork.ai) and the sheet URL is returned.

If the env var is missing the function returns None — the caller falls back
to XLSX-only mode.
"""
import json
import os

_SHARE_EMAIL = os.environ.get("AUDIT_SHARE_EMAIL", "shavi.goyal@gushwork.ai")

_DARK  = {"red": 0.102, "green": 0.102, "blue": 0.102}
_WHITE = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
_HIGH  = {"red": 1.0,   "green": 0.878, "blue": 0.878}
_MED   = {"red": 1.0,   "green": 0.949, "blue": 0.8}
_LOW   = {"red": 0.851, "green": 0.918, "blue": 0.827}
_CRIT  = {"red": 0.95,  "green": 0.8,   "blue": 0.8}

_PRIORITY_BG = {
    "Critical": _CRIT,
    "High":     _HIGH,
    "Medium":   _MED,
    "Low":      _LOW,
}


def _credentials():
    """Return google.oauth2.service_account.Credentials or None."""
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        from google.oauth2.service_account import Credentials
        info = json.loads(raw)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
        return Credentials.from_service_account_info(info, scopes=scopes)
    except Exception as exc:
        print(f"[sheets] credential error: {exc}")
        return None


def _service(creds):
    from googleapiclient.discovery import build
    return (
        build("sheets", "v4", credentials=creds, cache_discovery=False),
        build("drive",  "v3", credentials=creds, cache_discovery=False),
    )


def _cell(v):
    return {"userEnteredValue": {"stringValue": str(v) if v is not None else ""}}


def _hdr_fmt(nc, sid, bg=None):
    return {"repeatCell": {
        "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": nc},
        "cell": {"userEnteredFormat": {
            "backgroundColor": bg or _DARK,
            "textFormat": {"foregroundColor": _WHITE, "bold": True,
                           "fontFamily": "Proxima Nova", "fontSize": 11},
            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"}}


def _body_fmt(nr, nc, sid):
    return {"repeatCell": {
        "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": nr,
                  "startColumnIndex": 0, "endColumnIndex": nc},
        "cell": {"userEnteredFormat": {
            "textFormat": {"fontFamily": "Proxima Nova", "fontSize": 10},
            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat(textFormat,verticalAlignment,wrapStrategy)"}}


def _write_rows(sheets_svc, sid, sheet_id, rows):
    """Write rows to a sheet, batching at 1000 rows."""
    BATCH = 1000
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        cell_data = [{"values": [_cell(v) for v in row]} for row in batch]
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"updateCells": {
                "range": {"sheetId": sheet_id,
                          "startRowIndex": start,
                          "startColumnIndex": 0},
                "rows": cell_data,
                "fields": "userEnteredValue"}}]}
        ).execute()


def _add_sheet(sheets_svc, sid, title, idx):
    resp = sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=sid,
        body={"requests": [{"addSheet": {"properties": {"title": title, "index": idx}}}]}
    ).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]


def build(spreadsheet_title, obs_rows, evidence_tabs,
          page_type_rows=None, total_pages=None, total_images=None):
    """
    Create a Google Sheet with all audit data.

    obs_rows       — list of observation dicts (same as report_xlsx)
    evidence_tabs  — [(tab_name, [headers], [rows]), ...]
    page_type_rows — optional list of rows for Page Type tab
    total_pages    — int, total indexable HTML pages (for Count column)
    total_images   — int, total images in crawl (for image Count column)

    Returns the sheet URL (str) or None if credentials not available.
    """
    creds = _credentials()
    if creds is None:
        return None

    try:
        sheets_svc, drive_svc = _service(creds)

        # ── Create spreadsheet ────────────────────────────────────────────────
        sp = sheets_svc.spreadsheets().create(body={
            "properties": {"title": spreadsheet_title},
            "sheets": [{"properties": {"title": "Observations", "index": 0}}]
        }).execute()
        sid = sp["spreadsheetId"]
        obs_sheet_id = sp["sheets"][0]["properties"]["sheetId"]

        idx = 1  # next tab index

        # ── Observations tab ──────────────────────────────────────────────────
        _IMAGE_KEYS = {"image_large"}
        COUNT_HDR = "Count ⚠ DELETE BEFORE SHARING"
        obs_header = ["Category", "Observation", "Priority", "Impact", "Reference", COUNT_HDR]
        obs_data = [obs_header]
        for r in obs_rows:
            count = r.get("count")
            key   = r.get("key", "")
            if count and key in _IMAGE_KEYS and total_images:
                cl = f"{count} / {total_images} images"
            elif count and total_pages:
                cl = f"{count} / {total_pages} pages"
            elif count:
                cl = str(count)
            else:
                cl = ""
            obs_data.append([r.get("category",""), r["observation"],
                             r["priority"], r["impact"], r["reference"], cl])

        _write_rows(sheets_svc, sid, obs_sheet_id, obs_data)

        # Format Observations
        fmt_reqs = [
            _hdr_fmt(6, obs_sheet_id),
            _body_fmt(len(obs_data), 6, obs_sheet_id),
            {"updateSheetProperties": {"properties": {"sheetId": obs_sheet_id,
                "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            # Count header in red
            {"repeatCell": {"range": {"sheetId": obs_sheet_id, "startRowIndex": 0,
                "endRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 6},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.9, "green": 0.2, "blue": 0.2},
                    "textFormat": {"foregroundColor": _WHITE, "bold": True,
                                   "fontFamily": "Proxima Nova", "fontSize": 11}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        ]
        # Priority row colours (rows 1..N, 0-indexed)
        for ri, r in enumerate(obs_rows, start=1):
            bg = _PRIORITY_BG.get(r.get("priority", ""))
            if bg:
                fmt_reqs.append({"repeatCell": {
                    "range": {"sheetId": obs_sheet_id, "startRowIndex": ri,
                              "endRowIndex": ri + 1, "startColumnIndex": 0, "endColumnIndex": 6},
                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                    "fields": "userEnteredFormat.backgroundColor"}})
        sheets_svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": fmt_reqs}).execute()

        # ── Evidence tabs ─────────────────────────────────────────────────────
        for tab_name, headers, data_rows in evidence_tabs:
            t_id = _add_sheet(sheets_svc, sid, tab_name[:31], idx)
            idx += 1
            all_rows = [headers] + [list(r) for r in data_rows]
            _write_rows(sheets_svc, sid, t_id, all_rows)
            sheets_svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
                _hdr_fmt(len(headers), t_id),
                _body_fmt(len(all_rows), len(headers), t_id),
                {"updateSheetProperties": {"properties": {"sheetId": t_id,
                    "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
                {"updateDimensionProperties": {"range": {"sheetId": t_id, "dimension": "COLUMNS",
                    "startIndex": 0, "endIndex": 1},
                    "properties": {"pixelSize": 460}, "fields": "pixelSize"}},
            ]}).execute()

        # ── Page Type tab (optional) ──────────────────────────────────────────
        if page_type_rows:
            pt_id = _add_sheet(sheets_svc, sid, "Page Type", idx)
            idx += 1
            _write_rows(sheets_svc, sid, pt_id, page_type_rows)
            sheets_svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
                _hdr_fmt(len(page_type_rows[0]), pt_id),
                _body_fmt(len(page_type_rows), len(page_type_rows[0]), pt_id),
            ]}).execute()

        # ── Share ─────────────────────────────────────────────────────────────
        if _SHARE_EMAIL:
            drive_svc.permissions().create(
                fileId=sid, sendNotificationEmail=False,
                body={"type": "user", "role": "writer", "emailAddress": _SHARE_EMAIL}
            ).execute()

        return f"https://docs.google.com/spreadsheets/d/{sid}"

    except Exception as exc:
        print(f"[sheets] error: {exc}")
        return None
