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

        # 3) Observations tab: 14-column schema + intro row + finding rows + ending row
        _IMAGE_KEYS = {"image_large"}
        header = [
            "Slide #", "Slide Type", "Approved",
            "Category", "Observation", "Priority", "Impact", "Reference",
            "Hook Stat", "Hook Context", "What We Found",
            "What It Costs You", "Supporting Stats",
            "Count ⚠ DELETE BEFORE SHARING",
        ]
        obs_data = [header]
        # Intro
        intro_hook = "Increase your leads by 33%"
        intro_ctx  = "Same pages. Same website."
        obs_data.append([
            1, "intro", "FALSE",
            "Intro", "Cover / hook slide — CS edits messaging", "", "", "",
            "+33%", f"{intro_hook}. {intro_ctx}",
            "e.g. Meta descriptions +5.8% + Structured data +25% = +33%",
            "If you get 10 leads today → 14 leads. Before any ranking gains.",
            "", "",
        ])
        # Findings
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
            ref = r.get("reference", "") or ""
            obs_data.append([
                i, "finding", "FALSE",
                r.get("category", ""), r["observation"], r["priority"], r["impact"], ref,
                "", r["observation"], ref, r["impact"], "",
                cl,
            ])
        # Ending
        end_slide = len(obs_data)
        obs_data.append([
            end_slide, "ending", "FALSE",
            "Ending", "CTA / closing slide — CS edits messaging", "", "", "",
            "4 extra leads / month",
            "Every month you wait, you lose out on extra leads from the same pages.",
            "", "Approve the audit fixes.", "", "",
        ])
        _write_rows_to_tab(sid, "Observations", obs_data)

        # 4) Meta tab
        if meta:
            _add_sheet_tab(sid, "Meta")
            meta_rows = [
                ["Field", "Value"],
                ["Version", meta.get("version", "")],
                ["Generated", meta.get("generated", "")],
                ["Live URL", meta.get("live_url", "")],
                ["Plan ($ / month)", meta.get("plan", "")],
                ["Currently paying ($ / month)", meta.get("current_spend", "")],
                ["Sell price ($)", meta.get("sell_price", "")],
                ["Reviewed", "FALSE"],
            ]
            _write_rows_to_tab(sid, "Meta", meta_rows)

        # 5) Evidence tabs
        for tab_name, headers, data_rows in evidence_tabs:
            name = tab_name[:31]
            _add_sheet_tab(sid, name)
            all_rows = [list(headers)] + [list(r) for r in data_rows]
            _write_rows_to_tab(sid, name, all_rows)

        # 6) Page Type (optional)
        if page_type_rows:
            _add_sheet_tab(sid, "Page Type")
            _write_rows_to_tab(sid, "Page Type", page_type_rows)

        # 7) Share with the org (non-fatal if it fails)
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
    """Fetch Meta + Observations via Composio's Sheets read action."""
    sid = _extract_sheet_id(sheet_url_or_id)
    if not sid or not _sheets_available():
        return None
    try:
        meta_resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": ["Meta!A1:B20"],
        })
    except Exception as exc:
        print(f"[sheets] read Meta failed: {exc}")
        return None
    parsed_meta = {}
    values = _extract_first_range(meta_resp)
    for row in values[1:] if values else []:
        if not row: continue
        k = (row[0] if len(row) > 0 else "").strip()
        v = (row[1] if len(row) > 1 else "").strip()
        parsed_meta[k] = v
    reviewed_raw = str(parsed_meta.get("Reviewed", "")).strip().lower()
    meta = {
        "version":       parsed_meta.get("Version", ""),
        "generated":     parsed_meta.get("Generated", ""),
        "live_url":      parsed_meta.get("Live URL", ""),
        "plan":          parsed_meta.get("Plan ($ / month)", ""),
        "current_spend": parsed_meta.get("Currently paying ($ / month)", ""),
        "sell_price":    parsed_meta.get("Sell price ($)", ""),
        "reviewed":      reviewed_raw in ("true", "yes", "checked", "1"),
    }
    try:
        obs_resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": ["Observations!A1:N"],
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
    return {"meta": meta, "obs_rows": obs_rows}


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
