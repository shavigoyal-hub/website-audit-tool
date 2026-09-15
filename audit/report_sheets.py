"""Write a complete audit to a new Google Sheet via Composio.

Formatting approach: Composio's GOOGLESHEETS_FORMAT_CELL only handles
background + bold, unreliably. The proven way (borrowed from seo-reporting's
styled-sheet.ts) is to build an HTML table with inline CSS and upload it
via GOOGLEDRIVE_EDIT_FILE with mime_type=text/html — Drive converts the
HTML into a Sheet, preserving colour, font, weight, AND formulas (a cell
whose value starts with '=' becomes a real formula).
"""
import html as _html
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

# 9-col schema (0-indexed):
#   0 Category   1 Observation   2 Priority   3 Impact
#   4 Hook Stat  5 Hook Context  6 What We Found
#   7 What It Costs You   8 Supporting Stats
_COL_PRIORITY     = 2
_COL_DECK_START   = 4
# Per-column pixel widths applied after HTML import (order matches header)
_COL_WIDTHS_PX    = [160, 400, 110, 320, 120, 340, 320, 320, 240]


def _format_cell(sid, worksheet_id, r0, r1, c0, c1, rgb, bold=False):
    """Composio's GOOGLESHEETS_FORMAT_CELL: background color + bold only."""
    try:
        _composio_execute("GOOGLESHEETS_FORMAT_CELL", {
            "spreadsheet_id": sid,
            "worksheet_id": worksheet_id,
            "start_row_index": r0, "end_row_index": r1,
            "start_column_index": c0, "end_column_index": c1,
            "red": rgb["red"], "green": rgb["green"], "blue": rgb["blue"],
            "bold": bool(bold),
        })
    except Exception as exc:
        print(f"[sheets] format_cell (non-fatal): {exc}")


def _format_observations(sid, sheet_id, obs_data):
    """Header + priority tint + intro/ending highlight + grey fill on deck cols.

    Composio only supports per-range background+bold via FORMAT_CELL; freeze
    and column widths go through UPDATE_SHEET_PROPERTIES.
    """
    ncols = len(obs_data[0])

    # Freeze first row + first 3 cols
    try:
        _composio_execute("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
            "spreadsheetId": sid,
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id,
                               "gridProperties": {"frozenRowCount": 1,
                                                  "frozenColumnCount": 3}},
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            },
        })
    except Exception as exc:
        print(f"[sheets] freeze (non-fatal): {exc}")

    # Header row — dark background + bold
    _format_cell(sid, sheet_id, 0, 1, 0, ncols, _HEADER_BG, bold=True)

    # Row-level fills
    for ri, row in enumerate(obs_data[1:], start=1):
        stype = row[1] if len(row) > 1 else ""
        if stype in ("intro", "ending"):
            _format_cell(sid, sheet_id, ri, ri + 1, 0, ncols, _SPECIAL_BG, bold=True)
            continue
        prio = row[_COL_PRIORITY] if len(row) > _COL_PRIORITY else ""
        bg = _PRIORITY_BG.get(prio)
        if bg:
            _format_cell(sid, sheet_id, ri, ri + 1,
                         _COL_PRIORITY, _COL_PRIORITY + 1, bg, bold=True)

    # Deck columns get uniform grey — applied LAST so it overrides row-level
    # highlight on intro/ending rows in the deck cols.
    _format_cell(sid, sheet_id, 1, len(obs_data),
                 _COL_DECK_START, ncols, _DECK_BG, bold=False)


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


_HEADER_HEX     = "#1a1a1a"
_HEADER_TEXT    = "#ffffff"
_SPECIAL_HEX    = "#f2f2f7"
_DECK_HEX       = "#e6e6ee"
_PRIORITY_HEX   = {
    "Critical": "#f4cccc",
    "High":     "#fce5cd",
    "Medium":   "#fff2cc",
    "Low":      "#d9ead3",
}


def _td(value, *, bg=None, color="#111", bold=False, font_size=10):
    """Escape and wrap a single cell as an HTML <td> with inline styles.
    Values starting with '=' become real formulas when Drive imports the HTML.
    """
    if value is None:
        value = ""
    text = _html.escape(str(value), quote=False)
    # Preserve newlines in cell content as line breaks so multi-URL "What
    # We Found" lists render on multiple lines (also drives row height up).
    text = text.replace("\n", "<br>")
    style_parts = [
        "font-family:Proxima Nova,Arial,sans-serif",
        f"font-size:{font_size}pt",
        f"color:{color}",
        "vertical-align:top",
        "white-space:normal",           # force wrap on long strings
        "padding:8px 10px",             # gives visual row height
        "line-height:1.4",
    ]
    if bg:
        style_parts.append(f"background-color:{bg}")
    if bold:
        style_parts.append("font-weight:bold")
    return f'<td style="{";".join(style_parts)}">{text}</td>'


def _build_observations_html(obs_data):
    """Build the styled HTML that Drive will convert into the Sheet.

    Intro / ending are the first and last data rows (index 1 and last).
    """
    header = obs_data[0]
    ncols = len(header)
    last_i = len(obs_data) - 1
    parts = ['<html><head><meta charset="utf-8"></head><body><table>']
    # colgroup with widths — Sheets HTML import respects these on first render.
    parts.append("<colgroup>")
    for w in _COL_WIDTHS_PX[:ncols]:
        parts.append(f'<col style="width:{w}px">')
    parts.append("</colgroup>")

    # Header row
    parts.append('<tr style="height:44px">')
    for cell in header:
        parts.append(_td(cell, bg=_HEADER_HEX, color=_HEADER_TEXT,
                          bold=True, font_size=11))
    parts.append("</tr>")

    # Body rows — height:auto lets long-wrapped content grow the row
    for ri, row in enumerate(obs_data[1:], start=1):
        is_special = ri == 1 or ri == last_i
        priority = row[_COL_PRIORITY] if len(row) > _COL_PRIORITY else ""
        parts.append('<tr style="height:110px">')
        for ci, val in enumerate(row):
            if ci >= _COL_DECK_START:
                bg, color, bold = _DECK_HEX, "#111", False
            elif is_special:
                bg, color, bold = _SPECIAL_HEX, "#111", True
            elif ci == _COL_PRIORITY and priority in _PRIORITY_HEX:
                bg, color, bold = _PRIORITY_HEX[priority], "#111", True
            else:
                bg, color, bold = None, "#111", False
            parts.append(_td(val, bg=bg, color=color, bold=bold))
        parts.append("</tr>")
    parts.append("</table></body></html>")
    return "".join(parts)


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

        # 3) Observations tab — 10 cols. Row order in the sheet decides the
        # deck order. First data row → intro slide, last → ending. Everything
        # in between is a finding. CS can drag rows / delete rows.
        # Hook Context is a formula that references its own row's Hook Stat
        # cell (column F), so editing the stat updates the context.
        header = [
            "Category", "Observation", "Priority", "Impact",
            "Hook Stat", "Hook Context", "What We Found",
            "What It Costs You", "Supporting Stats",
        ]
        obs_data = [header]

        # Intro row (Sheets row 2 → Hook Stat cell = E2)
        obs_data.append([
            "Intro — cover slide",
            "Cover / hook slide — CS edits messaging",
            "", "",
            "+33%",
            '=E2&" "&"Increase your leads. Same pages. Same website."',
            "e.g. Meta descriptions +5.8% + Structured data +25% = +33%",
            "If you get 10 leads today → 14 leads. Before any ranking gains.",
            "",
        ])

        # Finding rows — Hook Context references Hook Stat in column E
        for r in obs_rows:
            key = r.get("key", "")
            copy = _hook_for(key, r.get("observation", ""), r.get("impact", ""))
            ref  = r.get("reference", "") or ""
            sheet_row = len(obs_data) + 1
            ctx_body = copy["hook_ctx"].replace('"', '""')
            hook_ctx_formula = f'=E{sheet_row}&" "&"{ctx_body}"'
            obs_data.append([
                r.get("category", ""),
                r.get("observation", ""),
                r.get("priority", ""),
                r.get("impact", ""),
                copy["hook_stat"],
                hook_ctx_formula,
                ref,                    # 'What we found' seeded with page list
                copy["costs"],
                copy["support"],
            ])

        # Ending row
        end_row = len(obs_data) + 1
        obs_data.append([
            "Ending — CTA slide",
            "CTA / closing slide — CS edits messaging",
            "", "",
            "4 extra leads / month",
            f'=E{end_row}&" "&"— every month you wait, you lose out from the same pages."',
            "",
            "Approve the audit fixes.",
            "",
        ])
        # 4) Import the styled HTML into the sheet — Drive converts HTML with
        #    inline CSS into a Sheet with colours, weights, and preserves
        #    =formulas. This is the only reliable Composio-native path for
        #    coloured cells (FORMAT_CELL silently drops most styling).
        html_body = _build_observations_html(obs_data)
        _composio_execute("GOOGLEDRIVE_EDIT_FILE", {
            "file_id": sid,
            "content": html_body,
            "mime_type": "text/html",
        })

        # 5) Freeze first row + first 3 cols (HTML import doesn't set this).
        try:
            info = _composio_execute("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                                     {"spreadsheet_id": sid}) or {}
            sheets = info.get("sheets") or []
            imported_id = ((sheets[0].get("properties") or {}).get("sheetId")
                           if sheets else 0)
            _composio_execute("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
                "spreadsheetId": sid,
                "updateSheetProperties": {
                    "properties": {"sheetId": imported_id,
                                   "title": "Observations",
                                   "gridProperties": {"frozenRowCount": 1,
                                                      "frozenColumnCount": 1}},
                    "fields": "title,gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                },
            })
        except Exception as exc:
            print(f"[sheets] freeze/rename (non-fatal): {exc}")

        # 6) Share with the org (non-fatal if it fails)
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

    9-col schema (row order = deck order):
      0 Category | 1 Observation | 2 Priority | 3 Impact |
      4 Hook Stat | 5 Hook Context | 6 What We Found |
      7 What It Costs You | 8 Supporting Stats
    First data row → intro; last data row → ending; middle → findings.
    """
    sid = _extract_sheet_id(sheet_url_or_id)
    if not sid or not _sheets_available():
        return None
    try:
        obs_resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": ["Observations!A1:I"],
        })
    except Exception as exc:
        print(f"[sheets] read Observations failed: {exc}")
        return None
    obs_values = _extract_first_range(obs_resp) or []
    data_rows = [r for r in obs_values[1:] if r and any(str(c).strip() for c in r)]
    obs_rows = []
    def _g(row, i):
        return row[i].strip() if i < len(row) and row[i] is not None else ""
    last_idx = len(data_rows) - 1
    for i, row in enumerate(data_rows):
        if i == 0:
            stype = "intro"
        elif i == last_idx:
            stype = "ending"
        else:
            stype = "finding"
        obs_rows.append({
            "slide_no":    i + 1,
            "slide_type":  stype,
            "approved":    True,
            "category":    _g(row, 0),
            "observation": _g(row, 1),
            "priority":    _g(row, 2),
            "impact":      _g(row, 3),
            "hook_stat":   _g(row, 4),
            "hook_ctx":    _g(row, 5),
            "found":       _g(row, 6),
            "costs":       _g(row, 7),
            "support":     _g(row, 8),
            "reference":   "",
        })
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
