"""Write a complete audit to a new Google Sheet via Composio's tools-execute API.

Composio doesn't hand out raw OAuth tokens — you call their proxy actions
instead (POST /api/v3/tools/execute/{slug}). This module builds the audit
sheet using only Composio-native actions:

  GOOGLEDRIVE_CREATE_FILE_FROM_TEXT — create a blank Sheet via Drive
  GOOGLESHEETS_ADD_SHEET             — add extra tabs
  GOOGLESHEETS_BATCH_UPDATE          — write cell values
  GOOGLESHEETS_GET_SPREADSHEET_INFO  — read tab structure back
  GOOGLESHEETS_DELETE_SHEET          — remove the placeholder tab
  GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE — share with @gushwork.ai

Fancy formatting (checkbox data validation, colour-per-priority,
conditional formats) needs the raw Sheets API and can't be applied through
Composio's named actions alone — CS still gets the columns and values,
just plain-text 'TRUE'/'FALSE' instead of native checkboxes.
"""
import os

from audit.composio_exec import execute as _composio_execute
from audit.composio_exec import reset_trace as _reset_trace, LAST_TRACE
from audit.hook_copy import for_row as _hook_for

_SHARE_DOMAIN = "gushwork.ai"

# Last error surfaced via /run response
LAST_ERROR = ""


def _sheets_available():
    """We rely on Composio; require COMPOSIO_API_KEY to be set."""
    return bool(os.environ.get("COMPOSIO_API_KEY"))


# For /health compatibility
def _credentials():
    if _sheets_available():
        return "composio"  # truthy sentinel
    return None


def _get_placeholder_sheet_id(spreadsheet_id):
    info = _composio_execute("GOOGLESHEETS_GET_SPREADSHEET_INFO", {
        "spreadsheet_id": spreadsheet_id,
    })
    sheets = (info or {}).get("sheets") or []
    for s in sheets:
        props = s.get("properties", {})
        return props.get("sheetId"), props.get("title")
    return None, None


def _create_spreadsheet(title):
    """Drive create-from-text with mime_type=spreadsheet → blank Sheet."""
    result = _composio_execute("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {
        "file_name": title,
        "text_content": " ",
        "mime_type": "application/vnd.google-apps.spreadsheet",
    })
    sid = None
    if isinstance(result, dict):
        sid = result.get("id") or result.get("fileId") or result.get("spreadsheetId")
    if not sid:
        raise RuntimeError(f"Drive create returned no id: {str(result)[:300]}")
    return sid


def _add_sheet_tab(spreadsheet_id, tab_name):
    """Composio's GOOGLESHEETS_ADD_SHEET ignores any title/sheet_name arg we
    pass and returns 'Sheet1', 'Sheet2', ... Read the new sheetId from the
    reply and rename it in a second call.
    """
    resp = _composio_execute("GOOGLESHEETS_ADD_SHEET", {
        "spreadsheet_id": spreadsheet_id,
        "title": tab_name[:100],
        "sheet_name": tab_name[:100],  # cover both spellings
    }) or {}
    # Extract the sheetId of the newly-created tab
    new_sheet_id = None
    replies = resp.get("replies") if isinstance(resp, dict) else None
    if isinstance(replies, list):
        for r in replies:
            add = r.get("addSheet") if isinstance(r, dict) else None
            if isinstance(add, dict):
                new_sheet_id = add.get("sheetId") or (add.get("properties") or {}).get("sheetId")
                if new_sheet_id is not None:
                    break
    if new_sheet_id is None:
        # Fallback: get spreadsheet info and pick the last sheet
        info = _composio_execute("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                                 {"spreadsheet_id": spreadsheet_id}) or {}
        sheets = (info.get("sheets") or []) if isinstance(info, dict) else []
        if sheets:
            new_sheet_id = (sheets[-1].get("properties") or {}).get("sheetId")
    if new_sheet_id is None:
        raise RuntimeError(f"ADD_SHEET returned no sheetId: {str(resp)[:300]}")
    _rename_sheet(spreadsheet_id, new_sheet_id, tab_name)


def _rename_sheet(spreadsheet_id, sheet_id, new_title):
    """Rename an existing tab (used to rename the placeholder tab to 'Observations')."""
    _composio_execute("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
        "spreadsheetId": spreadsheet_id,
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "title": new_title},
            "fields": "title",
        },
    })


def _write_rows_to_tab(spreadsheet_id, tab_name, rows, start_cell="A1"):
    """Write a 2D list of values into a tab."""
    if not rows:
        return
    # Composio's BATCH_UPDATE action writes values via its own shape.
    _composio_execute("GOOGLESHEETS_BATCH_UPDATE", {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": tab_name,
        "first_cell_location": start_cell,
        "valueInputOption": "USER_ENTERED",
        "values": rows,
    })


_PRIORITY_BG = {
    "Critical": {"red": 0.95, "green": 0.80, "blue": 0.80},
    "High":     {"red": 1.00, "green": 0.88, "blue": 0.80},
    "Medium":   {"red": 1.00, "green": 0.95, "blue": 0.80},
    "Low":      {"red": 0.85, "green": 0.92, "blue": 0.83},
}
_HEADER_BG  = {"red": 0.102, "green": 0.102, "blue": 0.102}
_WHITE      = {"red": 1.0, "green": 1.0, "blue": 1.0}
_BLACK      = {"red": 0.0, "green": 0.0, "blue": 0.0}
_SPECIAL_BG = {"red": 0.949, "green": 0.949, "blue": 0.968}
_DECK_BG    = {"red": 0.90, "green": 0.90, "blue": 0.92}  # grey for deck columns

# Column layout constants — keep in sync with build()
_COL_APPROVED       = 2
_COL_PRIORITY       = 5
_COL_DECK_START     = 8   # first deck-specific column (Hook Stat)


def _format_observations(sid, sheet_id, obs_data):
    """Header + priority tint + intro/ending highlight + grey fill on deck cols."""
    ncols = len(obs_data[0])
    reqs = [
        # Freeze first row + first 3 cols
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 1,
                                              "frozenColumnCount": 3}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
        # Header: dark bg + white bold text
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": ncols},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _HEADER_BG,
                "textFormat": {"foregroundColor": _WHITE, "bold": True,
                               "fontSize": 11},
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"}},
        # Body: wrap all cells, top-align
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "endRowIndex": len(obs_data),
                      "startColumnIndex": 0, "endColumnIndex": ncols},
            "cell": {"userEnteredFormat": {"verticalAlignment": "TOP",
                                             "wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)"}},
    ]

    # Column widths (0 Slide# / 1 SlideType / 2 Approved / 3 Cat / 4 Obs /
    # 5 Prio / 6 Impact / 7 Ref / 8-12 deck)
    for start, end, px in [(0, 1, 60), (1, 3, 90), (3, 4, 120), (4, 5, 260),
                            (5, 6, 90), (6, 7, 260), (7, 8, 220),
                            (8, 9, 100), (9, 10, 240), (10, 11, 240),
                            (11, 12, 240), (12, 13, 220)]:
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": start, "endIndex": end},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})

    # Row-level fills — intro/ending row + priority tint on Priority cell
    for ri, row in enumerate(obs_data[1:], start=1):
        stype = row[1] if len(row) > 1 else ""
        if stype in ("intro", "ending"):
            reqs.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": ri,
                          "endRowIndex": ri + 1, "startColumnIndex": 0,
                          "endColumnIndex": ncols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _SPECIAL_BG,
                    "textFormat": {"bold": True, "foregroundColor": _BLACK}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
            continue
        prio = row[_COL_PRIORITY] if len(row) > _COL_PRIORITY else ""
        bg = _PRIORITY_BG.get(prio)
        if bg:
            reqs.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": ri,
                          "endRowIndex": ri + 1,
                          "startColumnIndex": _COL_PRIORITY,
                          "endColumnIndex": _COL_PRIORITY + 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": bg,
                    "textFormat": {"foregroundColor": _BLACK, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    # Deck columns (8-12) get uniform grey fill + black font — applied LAST so
    # it overrides intro/ending row highlight on those columns.
    reqs.append({"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": 1,
                  "endRowIndex": len(obs_data),
                  "startColumnIndex": _COL_DECK_START, "endColumnIndex": ncols},
        "cell": {"userEnteredFormat": {
            "backgroundColor": _DECK_BG,
            "textFormat": {"foregroundColor": _BLACK}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat.foregroundColor)"}})

    # Approved column = TRUE/FALSE data validation (Sheets shows a checkbox)
    reqs.append({"setDataValidation": {
        "range": {"sheetId": sheet_id, "startRowIndex": 1,
                  "endRowIndex": len(obs_data),
                  "startColumnIndex": _COL_APPROVED,
                  "endColumnIndex": _COL_APPROVED + 1},
        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True}}})

    # Fire it all in one batchUpdate against the raw Sheets API. Composio's
    # named BATCH_UPDATE action only handles cell values — for formatting we
    # need the raw request shape, which they expose as GOOGLESHEETS_BATCH_UPDATE
    # by-passing valueInputOption when we pass `requests` instead.
    try:
        _composio_execute("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid,
            "requests": reqs,
        })
    except Exception as exc:
        # Formatting is best-effort — the sheet is still usable without it.
        print(f"[sheets] format (non-fatal): {exc}")


def _share(spreadsheet_id):
    try:
        _composio_execute("GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE", {
            "file_id": spreadsheet_id,
            "role": "writer",
            "type": "domain",
            "domain": _SHARE_DOMAIN,
            "sendNotificationEmail": False,
        })
    except Exception as exc:
        print(f"[sheets] share failed (non-fatal): {exc}")


def build(spreadsheet_title, obs_rows, evidence_tabs,
          page_type_rows=None, total_pages=None, total_images=None,
          meta=None):
    """Create the audit Sheet. Returns URL or None."""
    global LAST_ERROR
    LAST_ERROR = ""
    _reset_trace()

    if not _sheets_available():
        LAST_ERROR = "COMPOSIO_API_KEY not set"
        return None

    try:
        # 1) Create blank spreadsheet via Drive → gives us a fileId
        sid = _create_spreadsheet(spreadsheet_title)

        # 2) Rename the default first tab to "Observations"
        first_id, first_title = _get_placeholder_sheet_id(sid)
        if first_id is not None:
            _rename_sheet(sid, first_id, "Observations")

        # 3) Observations tab schema (13 cols):
        # Original audit columns (0-7)  |  Deck-specific columns (8-12, grey fill)
        #   0 Slide #        3 Category       8  Hook Stat
        #   1 Slide Type     4 Observation    9  Hook Context
        #   2 Approved       5 Priority       10 What We Found
        #                    6 Impact         11 What It Costs You
        #                    7 Reference      12 Supporting Stats
        header = [
            "Slide #", "Slide Type", "Approved",
            "Category", "Observation", "Priority", "Impact", "Reference",
            "Hook Stat", "Hook Context", "What We Found",
            "What It Costs You", "Supporting Stats",
        ]
        obs_data = [header]

        # Intro row — audit-side cells are metadata, deck-side is the actual copy
        obs_data.append([
            1, "intro", "FALSE",
            "Intro",
            "Cover / hook slide — CS edits messaging",
            "", "",
            "",
            "+33%",
            "Increase your leads by 33%. Same pages. Same website.",
            "e.g. Meta descriptions +5.8% + Structured data +25% = +33%",
            "If you get 10 leads today → 14 leads. Before any ranking gains.",
            "",
        ])

        # Finding rows — original audit copy + PDF-matched deck copy via hook_copy
        for i, r in enumerate(obs_rows, start=2):
            key = r.get("key", "")
            copy = _hook_for(key, r.get("observation", ""), r.get("impact", ""))
            ref  = r.get("reference", "") or ""
            obs_data.append([
                i, "finding", "FALSE",
                r.get("category", ""),
                r.get("observation", ""),
                r.get("priority", ""),
                r.get("impact", ""),
                ref,
                copy["hook_stat"],
                copy["hook_ctx"],
                ref,                    # 'What we found' seeded with page list
                copy["costs"],
                copy["support"],
            ])

        # Ending row
        end_slide = len(obs_data)
        obs_data.append([
            end_slide, "ending", "FALSE",
            "Ending",
            "CTA / closing slide — CS edits messaging",
            "", "",
            "",
            "4 extra leads / month",
            "Every month you wait, you lose out on extra leads from the same pages.",
            "",
            "Approve the audit fixes.",
            "",
        ])
        _write_rows_to_tab(sid, "Observations", obs_data)

        # 4) Formatting — header + priority tint + intro/ending highlight + freeze
        _format_observations(sid, first_id if first_id is not None else 0, obs_data)

        # 5) Share with the org (non-fatal if it fails)
        _share(sid)

        return f"https://docs.google.com/spreadsheets/d/{sid}"

    except Exception as exc:
        import traceback as _tb
        LAST_ERROR = _tb.format_exc()[:3000]
        print(f"[sheets] error: {LAST_ERROR}")
        return None


# ── Read-back for /build-deck ──────────────────────────────────────────────
def _extract_sheet_id(url_or_id):
    import re
    if not url_or_id:
        return None
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def read_for_deck(sheet_url_or_id):
    """Fetch Observations tab via Composio's Sheets read action.

    13-col schema:
      0 Slide # | 1 Slide Type | 2 Approved |
      3 Category | 4 Observation | 5 Priority | 6 Impact | 7 Reference |
      8 Hook Stat | 9 Hook Context | 10 What We Found |
      11 What It Costs You | 12 Supporting Stats
    """
    sid = _extract_sheet_id(sheet_url_or_id)
    if not sid or not _sheets_available():
        return None
    try:
        obs_resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": ["Observations!A1:M"],
        })
    except Exception as exc:
        print(f"[sheets] read Observations failed: {exc}")
        return None
    obs_values = _extract_first_range(obs_resp) or []
    obs_rows = []
    def _g(row, i):
        return row[i].strip() if i < len(row) and row[i] is not None else ""
    for row in obs_values[1:]:
        if not row or not any(row): continue
        try:
            slide_no = int(float(_g(row, 0))) if _g(row, 0) else 999
        except ValueError:
            slide_no = 999
        approved_raw = _g(row, 2).lower()
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
    obs_rows.sort(key=lambda r: r["slide_no"])
    return {"meta": {}, "obs_rows": obs_rows}


def _extract_first_range(resp):
    """Compact BATCH_GET response → 2D list of the first value range."""
    if not resp:
        return []
    if isinstance(resp, dict):
        vrs = resp.get("valueRanges") or resp.get("value_ranges")
        if isinstance(vrs, list) and vrs:
            return vrs[0].get("values") or []
        if "values" in resp and isinstance(resp["values"], list):
            return resp["values"]
    return []
