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

# Last error from a build() attempt, surfaced via /health.
LAST_ERROR = ""


def _credentials():
    """Return Google credentials or None.

    Order:
      1. Composio-connected Google account (COMPOSIO_API_KEY env var).
      2. Service account (GOOGLE_SERVICE_ACCOUNT_JSON env var).
    """
    try:
        from audit.composio_auth import get_credentials as _composio_creds
        creds = _composio_creds()
        if creds is not None:
            return creds
    except Exception as exc:
        print(f"[sheets] composio unavailable: {exc}")

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


def _meta_tab(sheets_svc, sid, idx, meta):
    """Add a Meta tab with version + plan inputs + Reviewed checkbox.
    Returns the sheetId of the new tab.
    """
    t_id = _add_sheet(sheets_svc, sid, "Meta", idx)
    rows = [
        ["Field", "Value"],
        ["Version", meta.get("version", "")],
        ["Generated", meta.get("generated", "")],
        ["Live URL", meta.get("live_url", "")],
        ["Plan ($ / month)", meta.get("plan", "")],
        ["Currently paying ($ / month)", meta.get("current_spend", "")],
        ["Sell price ($)", meta.get("sell_price", "")],
        ["Reviewed", "FALSE"],
    ]
    _write_rows(sheets_svc, sid, t_id, rows)
    reviewed_row = len(rows) - 1  # 0-indexed row of Reviewed
    sheets_svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
        _hdr_fmt(2, t_id),
        _body_fmt(len(rows), 2, t_id),
        {"updateDimensionProperties": {
            "range": {"sheetId": t_id, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 240}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": t_id, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 320}, "fields": "pixelSize"}},
        # Checkbox on Reviewed value cell
        {"setDataValidation": {
            "range": {"sheetId": t_id,
                      "startRowIndex": reviewed_row, "endRowIndex": reviewed_row + 1,
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "rule": {"condition": {"type": "BOOLEAN"}, "strict": True}}},
        # Highlight the Reviewed row
        {"repeatCell": {
            "range": {"sheetId": t_id, "startRowIndex": reviewed_row,
                      "endRowIndex": reviewed_row + 1,
                      "startColumnIndex": 0, "endColumnIndex": 2},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 1.0, "green": 0.976, "blue": 0.808},
                "textFormat": {"bold": True, "fontFamily": "Proxima Nova", "fontSize": 11}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
    ]}).execute()
    return t_id


def build(spreadsheet_title, obs_rows, evidence_tabs,
          page_type_rows=None, total_pages=None, total_images=None,
          meta=None):
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

        # ── Meta tab (version + plan inputs + Reviewed checkbox) ──────────
        if meta:
            _meta_tab(sheets_svc, sid, idx, meta)
            idx += 1

        # ── Observations tab ──────────────────────────────────────────────────
        # Columns: 0 Slide # | 1 Slide Type | 2 Approved | 3 Category |
        #          4 Observation | 5 Priority | 6 Impact | 7 Reference |
        #          8 Hook Stat | 9 Hook Context | 10 What We Found |
        #          11 What It Costs You | 12 Supporting Stats | 13 Count
        _IMAGE_KEYS = {"image_large"}
        COUNT_HDR = "Count ⚠ DELETE BEFORE SHARING"
        obs_header = [
            "Slide #", "Slide Type", "Approved",
            "Category", "Observation", "Priority", "Impact", "Reference",
            "Hook Stat", "Hook Context", "What We Found",
            "What It Costs You", "Supporting Stats", COUNT_HDR,
        ]
        NCOL = len(obs_header)
        obs_data = [obs_header]

        # Intro slide row (Slide # = 1)
        intro_hook = "Increase your leads by 33%"
        intro_ctx  = "Same pages. Same website."
        intro_formula = "e.g. Meta descriptions +5.8% + Structured data +25% = +33%"
        intro_costs   = "If you get 10 leads today → 14 leads. Before any ranking gains."
        obs_data.append([
            1, "intro", "FALSE",
            "Intro", "Cover / hook slide — CS edits messaging", "", "", "",
            "+33%", f"{intro_hook}. {intro_ctx}",
            intro_formula, intro_costs, "",
            "",
        ])

        # Finding rows
        for i, r in enumerate(obs_rows, start=2):
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
            # Pre-seed Hook Stat / Context / What We Found from finding data
            ref = r.get("reference", "") or ""
            hook_stat = ""      # CS fills e.g. "+32.3%"
            hook_ctx  = r["observation"]
            found     = ref
            costs     = r["impact"]
            obs_data.append([
                i, "finding", "FALSE",
                r.get("category",""), r["observation"], r["priority"], r["impact"], ref,
                hook_stat, hook_ctx, found, costs, "",
                cl,
            ])

        # Ending slide row
        end_idx = len(obs_data)  # 1-based Slide # for CS reordering
        obs_data.append([
            end_idx, "ending", "FALSE",
            "Ending", "CTA / closing slide — CS edits messaging", "", "", "",
            "4 extra leads / month",
            "Every month you wait, you lose out on extra leads from the same pages.",
            "", "Approve the audit fixes.", "",
            "",
        ])

        _write_rows(sheets_svc, sid, obs_sheet_id, obs_data)

        # Format Observations
        count_col = NCOL - 1
        approved_col = 2
        fmt_reqs = [
            _hdr_fmt(NCOL, obs_sheet_id),
            _body_fmt(len(obs_data), NCOL, obs_sheet_id),
            {"updateSheetProperties": {"properties": {"sheetId": obs_sheet_id,
                "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 3}},
                "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
            # Count header in red
            {"repeatCell": {"range": {"sheetId": obs_sheet_id, "startRowIndex": 0,
                "endRowIndex": 1, "startColumnIndex": count_col, "endColumnIndex": count_col + 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.9, "green": 0.2, "blue": 0.2},
                    "textFormat": {"foregroundColor": _WHITE, "bold": True,
                                   "fontFamily": "Proxima Nova", "fontSize": 11}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
            # Approved column = checkboxes for every data row
            {"setDataValidation": {
                "range": {"sheetId": obs_sheet_id,
                          "startRowIndex": 1, "endRowIndex": len(obs_data),
                          "startColumnIndex": approved_col,
                          "endColumnIndex": approved_col + 1},
                "rule": {"condition": {"type": "BOOLEAN"}, "strict": True}}},
            # Column widths
            {"updateDimensionProperties": {"range": {"sheetId": obs_sheet_id,
                "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 60}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": obs_sheet_id,
                "dimension": "COLUMNS", "startIndex": 1, "endIndex": 3},
                "properties": {"pixelSize": 80}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": obs_sheet_id,
                "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5},
                "properties": {"pixelSize": 280}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": obs_sheet_id,
                "dimension": "COLUMNS", "startIndex": 10, "endIndex": 12},
                "properties": {"pixelSize": 300}, "fields": "pixelSize"}},
        ]
        # Priority row colours (Priority is now column 5)
        # Skip intro (row 1) and ending (last row) — no priority
        for ri, r in enumerate(obs_rows, start=2):
            bg = _PRIORITY_BG.get(r.get("priority", ""))
            if bg:
                fmt_reqs.append({"repeatCell": {
                    "range": {"sheetId": obs_sheet_id, "startRowIndex": ri,
                              "endRowIndex": ri + 1,
                              "startColumnIndex": 5, "endColumnIndex": 6},
                    "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                    "fields": "userEnteredFormat.backgroundColor"}})
        # Highlight intro + ending rows
        for special_row in (1, len(obs_data) - 1):
            fmt_reqs.append({"repeatCell": {
                "range": {"sheetId": obs_sheet_id, "startRowIndex": special_row,
                          "endRowIndex": special_row + 1,
                          "startColumnIndex": 0, "endColumnIndex": NCOL},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.949, "green": 0.949, "blue": 0.968},
                    "textFormat": {"bold": True, "fontFamily": "Proxima Nova", "fontSize": 10}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
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

        # ── Share (non-fatal — token may lack Drive scope) ────────────────────
        if _SHARE_EMAIL:
            try:
                drive_svc.permissions().create(
                    fileId=sid, sendNotificationEmail=False,
                    body={"type": "user", "role": "writer", "emailAddress": _SHARE_EMAIL}
                ).execute()
            except Exception as exc:
                print(f"[sheets] share failed (non-fatal): {exc}")

        return f"https://docs.google.com/spreadsheets/d/{sid}"

    except Exception as exc:
        import traceback as _tb
        err = _tb.format_exc()
        # Google API HttpError has the response body on .content
        try:
            from googleapiclient.errors import HttpError
            if isinstance(exc, HttpError):
                body = exc.content.decode("utf-8", errors="replace") if exc.content else ""
                err = f"HttpError {exc.resp.status}: {body[:1500]}\n\n{err}"
        except Exception:
            pass
        print(f"[sheets] error: {err}")
        global LAST_ERROR
        LAST_ERROR = err[:2500]
        return None


# ── Read-back for /build-deck ──────────────────────────────────────────────
def _extract_sheet_id(url_or_id):
    """Accept full Sheets URL or bare ID."""
    import re
    if not url_or_id:
        return None
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def read_for_deck(sheet_url_or_id):
    """Fetch Meta + Observations tabs from an existing audit sheet.

    Returns dict:
        {
            "meta": {version, plan, current_spend, sell_price, reviewed: bool, ...},
            "obs_rows": [{category, observation, priority, impact, reference}, ...],
        }
    Returns None if sheet cannot be read or Meta tab is missing.
    """
    sid = _extract_sheet_id(sheet_url_or_id)
    if not sid:
        return None
    creds = _credentials()
    if creds is None:
        return None
    try:
        sheets_svc, _ = _service(creds)
        # Meta tab
        try:
            meta_resp = sheets_svc.spreadsheets().values().get(
                spreadsheetId=sid, range="Meta!A1:B20"
            ).execute()
        except Exception as exc:
            print(f"[sheets] read Meta failed: {exc}")
            return None
        meta = {}
        for row in meta_resp.get("values", [])[1:]:
            if not row: continue
            k = (row[0] if len(row) > 0 else "").strip()
            v = (row[1] if len(row) > 1 else "").strip()
            meta[k] = v
        reviewed_raw = str(meta.get("Reviewed", "")).strip().lower()
        parsed_meta = {
            "version":       meta.get("Version", ""),
            "generated":     meta.get("Generated", ""),
            "live_url":      meta.get("Live URL", ""),
            "plan":          meta.get("Plan ($ / month)", ""),
            "current_spend": meta.get("Currently paying ($ / month)", ""),
            "sell_price":    meta.get("Sell price ($)", ""),
            "reviewed":      reviewed_raw in ("true", "yes", "checked", "1"),
        }
        # Observations tab (14 cols — see report_sheets.build)
        obs_resp = sheets_svc.spreadsheets().values().get(
            spreadsheetId=sid, range="Observations!A1:N"
        ).execute()
        values = obs_resp.get("values", [])
        obs_rows = []
        def _g(row, i):
            return row[i].strip() if i < len(row) and row[i] is not None else ""
        for row in values[1:]:
            if not row or not any(row): continue
            approved_raw = _g(row, 2).lower()
            try:
                slide_no = int(float(_g(row, 0))) if _g(row, 0) else 999
            except ValueError:
                slide_no = 999
            obs_rows.append({
                "slide_no":    slide_no,
                "slide_type":  _g(row, 1).lower() or "finding",
                "approved":    approved_raw in ("true", "yes", "checked", "1"),
                "category":    _g(row, 3),
                "observation": _g(row, 4),
                "priority":    _g(row, 5),
                "impact":      _g(row, 6),
                "reference":   _g(row, 7),
                "hook_stat":   _g(row, 8),
                "hook_ctx":    _g(row, 9),
                "found":       _g(row, 10),
                "costs":       _g(row, 11),
                "support":     _g(row, 12),
            })
        # Sort by Slide # so CS's ordering is honoured
        obs_rows.sort(key=lambda r: r["slide_no"])
        return {"meta": parsed_meta, "obs_rows": obs_rows}
    except Exception as exc:
        print(f"[sheets] read_for_deck error: {exc}")
        return None
