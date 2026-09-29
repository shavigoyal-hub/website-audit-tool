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
from audit.hook_copy import STATUS_LABEL as _STATUS_LABEL


_PRIO_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# Findings intentionally NOT reported in the sheet / deck.
# User rule: never surface these as observations.
SKIP_KEYS = {"h1_long", "h1_duplicate",
             # Every og:* / open graph / social preview finding — CRO
             # / social share concern, not SEO. Direct-chat audit rule.
             "og_missing", "og_image_missing", "og_title_missing",
             "og_description_missing", "og_url_missing", "og_type_missing",
             "twitter_card_missing", "social_preview_missing"}


def _drop_og_findings(rows):
    """Belt-and-braces: also drop anything whose observation mentions og: or
    Open Graph, in case a finding leaks in from an LLM-enriched row that
    used a different key name."""
    import re as _re
    og_re = _re.compile(r"\b(og:|open graph|twitter:card|social preview)", _re.I)
    kept = []
    for r in rows:
        cat = (r.get("category") or "")
        obs = (r.get("observation") or "")
        if og_re.search(cat) or og_re.search(obs):
            continue
        kept.append(r)
    return kept

# Canonical family name per finding key, so ALL H1 sub-issues collapse into
# one 'H1 Tags' row (not one row per Missing/Multiple/Short/etc.).
_CATEGORY_FAMILY = {
    # H1
    "h1_missing":   "H1 Tags",
    "h1_multiple":  "H1 Tags",
    "h1_short":     "H1 Tags",
    "h1_long":      "H1 Tags",
    "h1_duplicate": "H1 Tags",
    # Meta descriptions
    "meta_missing":   "Meta Description",
    "meta_long":      "Meta Description",
    "meta_short":     "Meta Description",
    "meta_duplicate": "Meta Description",
    # Title tags
    "title_missing":   "Title Tags",
    "title_long":      "Title Tags",
    "title_short":     "Title Tags",
    "title_duplicate": "Title Tags",
    "title_stuffed":   "Title Tags",
    # Page speed
    "lcp_high":       "Page Speed",
    "lcp_medium":     "Page Speed",
    "cls_high":       "Page Speed",
    "perf_low":       "Page Speed",
    "perf_moderate":  "Page Speed",
}


def _merge_findings_by_category(rows):
    """Group findings that share the same top-level category into one row.

    Category families we merge (identified by the CATEGORY dict in
    observations.py which produces short labels like 'H1 Tags',
    'Meta Description', 'Title Length', 'Page Speed'):
      H1 Tags       → h1_missing, h1_multiple, h1_short, h1_long, h1_duplicate
      Meta Description → meta_missing, meta_long, meta_short, meta_duplicate
      Title Length     → title_long, title_short (title_missing stays as its own
                          'Missing Titles' category)
      Page Speed       → lcp_high, lcp_medium, perf_low, perf_moderate

    Merging: keep the highest-priority row as base, join URL examples with
    each finding's specific status label, keep the harshest hook_stat.
    """
    # Group by CANONICAL family name (H1 Tags, Meta Description, Title Tags,
    # Page Speed). Findings not in the family map stand alone.
    groups = {}
    order  = []
    for r in rows:
        key = r.get("key", "")
        family = _CATEGORY_FAMILY.get(key, (r.get("category") or "").strip())
        if family not in groups:
            order.append(family)
            groups[family] = []
        groups[family].append(r)

    merged = []
    for family in order:
        group = groups[family]
        if len(group) == 1:
            merged.append(group[0])
            continue
        # Sort by priority (Critical first)
        group.sort(key=lambda x: _PRIO_RANK.get(x.get("priority", ""), 9))
        base = dict(group[0])
        base["category"] = family      # rename to the family label
        # Combine URL examples across all sub-findings, each with its own pill.
        combined_refs = []
        for f in group:
            key = f.get("key", "")
            label, _ = _STATUS_LABEL.get(key, ("Issue", "medium"))
            ref = f.get("reference", "") or ""
            for u in ref.split("\n"):
                u = u.strip()
                if not u or u == "-": continue
                combined_refs.append(f"{u}||LABEL={label}")
        base["reference"]      = "\n".join(combined_refs)
        base["_merged_labels"] = True
        merged.append(base)
    return merged

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
_COL_WIDTHS_PX    = [180, 760, 100, 320, 110, 320, 320, 320, 240]


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
    """Share the sheet so BOTH gushwork.ai users AND Composio's own Sheets
    connection can access it. Composio's googlesheets connected account may
    be a different Google account than the googledrive one that created the
    file — without an anyone-with-link permission the Sheets API returns
    403 Forbidden on subsequent calls.
    """
    # 1. Domain-wide writer for internal collaboration
    try:
        _composio_execute("GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE", {
            "file_id": spreadsheet_id, "role": "writer", "type": "domain",
            "domain": _SHARE_DOMAIN, "sendNotificationEmail": False,
        })
    except Exception as exc:
        print(f"[sheets] domain share failed (non-fatal): {exc}")
    # 2. Anyone-with-link writer so Composio's Sheets connection can act on it
    try:
        _composio_execute("GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE", {
            "file_id": spreadsheet_id, "role": "writer", "type": "anyone",
            "sendNotificationEmail": False,
        })
    except Exception as exc:
        print(f"[sheets] anyone share failed (non-fatal): {exc}")


_HEADER_HEX     = "#1a1a1a"
_HEADER_TEXT    = "#ffffff"
_SPECIAL_HEX    = "#f2f2f7"
_DECK_HEX       = "#e6e6ee"
_PRIORITY_HEX   = {
    "Critical": "#f4cccc",
    "High":     "#fce5cd",
    "Medium":   "#fff2cc",
    "Low":      "#cfe2f3",  # light blue — green reads as 'passing', which Low is not
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

    # Body rows — height:auto lets long-wrapped content grow the row.
    # Priority tint applies to the whole AUDIT side (cols 0..DECK_START-1).
    # Deck-preview columns keep uniform grey fill.
    for ri, row in enumerate(obs_data[1:], start=1):
        is_special = ri == 1 or ri == last_i
        priority = row[_COL_PRIORITY] if len(row) > _COL_PRIORITY else ""
        priority_bg = _PRIORITY_HEX.get(priority)
        parts.append('<tr style="height:110px">')
        for ci, val in enumerate(row):
            if ci >= _COL_DECK_START:
                bg, color, bold = _DECK_HEX, "#111", False
            elif is_special:
                bg, color, bold = _SPECIAL_HEX, "#111", True
            elif priority_bg:
                # Tint entire audit-side row with the priority colour
                bg, color, bold = priority_bg, "#111", False
            else:
                bg, color, bold = None, "#111", False
            parts.append(_td(val, bg=bg, color=color, bold=bold))
        parts.append("</tr>")
    parts.append("</table></body></html>")
    return "".join(parts)


def _apply_dimensions(sid, sheet_id, obs_data):
    """Column widths + row heights via the Sheets API `batchUpdate` endpoint.

    Composio has no named action for `updateDimensionProperties`, so we go
    through `tools/proxy`. If the caller's API key lacks proxy scope this
    call fails cleanly and the sheet keeps auto-sized defaults.
    """
    from audit.composio_exec import proxy as _composio_proxy
    ncols = len(obs_data[0])
    requests_ = []
    # Column widths
    for i, px in enumerate(_COL_WIDTHS_PX[:ncols]):
        requests_.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": int(px)}, "fields": "pixelSize"}})
    # Header row height
    requests_.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS",
                  "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 40}, "fields": "pixelSize"}})
    # Body row height — a comfortable minimum; long-wrapped text can still
    # grow past this when Sheets recomputes on-view.
    if len(obs_data) > 1:
        requests_.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": 1, "endIndex": len(obs_data)},
            "properties": {"pixelSize": 90}, "fields": "pixelSize"}})
    # Header-row filter (Sheets shows the dropdown funnel icons in row 1)
    requests_.append({"setBasicFilter": {
        "filter": {
            "range": {"sheetId": sheet_id,
                      "startRowIndex": 0, "endRowIndex": len(obs_data),
                      "startColumnIndex": 0, "endColumnIndex": ncols}}}})
    # Priority column (C, index 2) — data-validation dropdown so cells show
    # the arrow chevron and only accept Critical / High / Medium / Low.
    priority_values = [
        {"userEnteredValue": "Critical"},
        {"userEnteredValue": "High"},
        {"userEnteredValue": "Medium"},
        {"userEnteredValue": "Low"},
    ]
    requests_.append({"setDataValidation": {
        "range": {"sheetId": sheet_id,
                  "startRowIndex": 1, "endRowIndex": len(obs_data),
                  "startColumnIndex": 2, "endColumnIndex": 3},
        "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": priority_values},
            "showCustomUi": True,
            "strict": False,
        }}})
    try:
        _composio_proxy(
            endpoint=f"https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate",
            method="POST",
            body={"requests": requests_},
        )
    except Exception as exc:
        print(f"[sheets] dimension proxy (non-fatal): {exc}")


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

        # 2) Share IMMEDIATELY so the Composio googlesheets connection (which
        # may be a different Google account than googledrive) can access it.
        # Without this, later Sheets API calls return 403 Forbidden.
        _share(sid)

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

        # Intro + ending slides now live on the separate 'Slide Review' tab
        # so the Observations tab is findings-only (CS review of findings is
        # the common case; slide-copy review is separate).
        intro_row = [
            "Intro — cover slide",
            "Same pages. Same website.",
            "", "",
            "+33%",
            'Increase your leads by 33%',
            "+5.8% Meta descriptions  ×  +25% Structured data  =  +33% More leads",
            "If you get 10 leads a month today 10 leads → 14 leads. Same pages, same website. Before any ranking gains.",
            "",
        ]

        # Merge findings by category — all H1 rows collapse into one, all
        # Meta / Title rows too — so the deck doesn't show 4 near-identical
        # slides for the same category. Priority ordering keeps the worst
        # first; URLs from every merged sub-finding are combined with their
        # specific status labels.
        obs_rows = [r for r in obs_rows if r.get("key", "") not in SKIP_KEYS]
        obs_rows = _drop_og_findings(obs_rows)
        obs_rows = _merge_findings_by_category(obs_rows)

        # Finding rows — Hook Context references Hook Stat in column E.
        # "What We Found" is seeded as "URL | STATUS_LABEL" per line so the
        # PDF can render a colored status pill per URL.
        for r in obs_rows:
            key = r.get("key", "")
            copy = _hook_for(key, r.get("observation", ""), r.get("impact", ""),
                              priority=r.get("priority", ""))
            default_label, _ = _STATUS_LABEL.get(key, ("Issue", "medium"))
            ref = r.get("reference", "") or ""
            merged = r.get("_merged_labels", False)
            # Only include entries that actually look like URLs or paths —
            # observations.py falls back to the evidence-tab name (e.g. the
            # category "Missing H1") when there are no examples, which we
            # don't want rendered as a URL row on the deck.
            labelled = []
            for entry in ref.split("\n"):
                entry = entry.strip()
                if not entry or entry == "-":
                    continue
                if merged and "||LABEL=" in entry:
                    u, label = entry.split("||LABEL=", 1)
                    u = u.strip(); label = label.strip()
                else:
                    u, label = entry, default_label
                if u.startswith("http") or u.startswith("/") or "." in u:
                    labelled.append((u, label))
            found_with_labels = "\n".join(f"{u} | {lb}" for u, lb in labelled[:8])
            sheet_row = len(obs_data) + 1
            ctx_body = copy["hook_ctx"].replace('"', '""')
            # Formula rules:
            #   - Empty stat → just the context (no leading "0%").
            #   - Numeric stat (Sheets auto-parses "-15%" as -0.15)
            #     → format WITHOUT forced trailing zero and prefix in blue-worthy form.
            #   - Text stat → pass through as-is.
            # Google Sheets number format #.#% strips trailing zeros:
            #   -0.15 → "-15%",   -0.083 → "-8.3%",   0.058 → "5.8%"
            hook_ctx_formula = (
                f'=IF(E{sheet_row}="","{ctx_body}",'
                f'IFERROR(TEXT(E{sheet_row},"+#.#%;-#.#%;0%")&" "&"{ctx_body}",'
                f'E{sheet_row}&" "&"{ctx_body}"))'
            )
            obs_data.append([
                r.get("category", ""),
                r.get("observation", ""),
                r.get("priority", ""),
                r.get("impact", ""),
                copy["hook_stat"],
                hook_ctx_formula,
                found_with_labels,      # URL | STATUS per line
                copy["costs"],
                copy["support"],
            ])

        # 4 blank rows for the user to add parameters manually after the run.
        for _ in range(4):
            obs_data.append(["", "", "", "", "", "", "", "", ""])

        # Ending row lives on 'Slide Review' too — see intro_row above.
        ending_row = [
            "Ending — CTA slide",
            "The searchers are already there. Let's make sure they land with you.",
            "", "",
            "4 extra leads",
            "Every month you wait, you lose out on 4 extra leads from the same pages.",
            "",
            "Approve the audit fixes",
            "",
        ]
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

        # 5a) Rename the imported tab to "Observations" — MUST succeed or the
        #     deck builder can't find it later. If Composio errors, retry with
        #     title-only fields.
        info = _composio_execute("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                                 {"spreadsheet_id": sid}) or {}
        sheets = info.get("sheets") or []
        imported_id = ((sheets[0].get("properties") or {}).get("sheetId")
                       if sheets else 0)
        try:
            _composio_execute("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
                "spreadsheetId": sid,
                "updateSheetProperties": {
                    "properties": {"sheetId": imported_id, "title": "Observations",
                                   "gridProperties": {"frozenRowCount": 1,
                                                      "frozenColumnCount": 1}},
                    "fields": "title,gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                },
            })
        except Exception as exc:
            print(f"[sheets] combined rename+freeze failed: {exc} — retrying title only")
            try:
                _composio_execute("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
                    "spreadsheetId": sid,
                    "updateSheetProperties": {
                        "properties": {"sheetId": imported_id, "title": "Observations"},
                        "fields": "title",
                    },
                })
            except Exception as exc2:
                print(f"[sheets] rename fallback also failed: {exc2}")

        # 5b) Column widths + row heights via proxy (best-effort).
        try:
            _apply_dimensions(sid, imported_id, obs_data)
        except Exception as exc:
            print(f"[sheets] dimensions (non-fatal): {exc}")

        # 6) Slide Review tab — intro + ending copy live here, not in
        #    Observations. Findings review and slide-copy review are
        #    separate workflows for CS.
        try:
            _write_slide_review_tab(sid, header, intro_row, ending_row)
        except Exception as exc:
            print(f"[sheets] slide review tab (non-fatal): {exc}")

        # 7) Sources tab (hidden by default — reviewer can un-hide from Sheets)
        try:
            _write_sources_tab(sid)
        except Exception as exc:
            print(f"[sheets] sources tab (non-fatal): {exc}")

        # 8) Share with the org (non-fatal if it fails)
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


READ_LAST_ERROR = ""


def read_for_deck(sheet_url_or_id):
    """Fetch Observations tab via Composio's Sheets read action.

    9-col schema (row order = deck order):
      0 Category | 1 Observation | 2 Priority | 3 Impact |
      4 Hook Stat | 5 Hook Context | 6 What We Found |
      7 What It Costs You | 8 Supporting Stats
    First data row → intro; last data row → ending; middle → findings.
    """
    global READ_LAST_ERROR
    READ_LAST_ERROR = ""
    sid = _extract_sheet_id(sheet_url_or_id)
    if not sid:
        READ_LAST_ERROR = f"Could not extract spreadsheet id from url: {sheet_url_or_id[:120]!r}"
        return None
    if not _sheets_available():
        READ_LAST_ERROR = "COMPOSIO_API_KEY not set"
        return None
    # Prefer 'Observations' but gracefully fall back to the first tab of
    # the spreadsheet if the rename step failed during /run.
    tab_name = "Observations"
    try:
        obs_resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": [f"{tab_name}!A1:I"],
        })
    except Exception as exc:
        # Look up the first tab name and retry
        try:
            info = _composio_execute("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                                     {"spreadsheet_id": sid}) or {}
            sheets = info.get("sheets") or []
            if not sheets:
                READ_LAST_ERROR = f"spreadsheet {sid} has no tabs: {exc}"
                return None
            tab_name = ((sheets[0].get("properties") or {}).get("title") or "")
            if not tab_name:
                READ_LAST_ERROR = f"first tab has no title on {sid}"
                return None
            obs_resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
                "spreadsheet_id": sid, "ranges": [f"{tab_name}!A1:I"],
            })
        except Exception as exc2:
            READ_LAST_ERROR = f"BATCH_GET {tab_name!r} failed on {sid}: {exc2}"
            print(f"[sheets] {READ_LAST_ERROR}")
            return None
    obs_values = _extract_first_range(obs_resp) or []
    data_rows = [r for r in obs_values[1:] if r and any(str(c).strip() for c in r)]

    # Try to fetch Slide Review tab for intro + ending; fall back to legacy
    # single-tab layout (first/last row in Observations) if it isn't there.
    intro_row_data = None
    ending_row_data = None
    try:
        sr = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": ["Slide Review!A1:I"],
        })
        sr_rows = _extract_first_range(sr) or []
        sr_data = [r for r in sr_rows[1:] if r and any(str(c).strip() for c in r)]
        if len(sr_data) >= 1:
            intro_row_data = sr_data[0]
        if len(sr_data) >= 2:
            ending_row_data = sr_data[1]
    except Exception:
        pass

    obs_rows = []
    def _g(row, i):
        return row[i].strip() if i < len(row) and row[i] is not None else ""

    # Assemble slides: intro (from Slide Review or first Observations row)
    # + findings (all Observations rows, except first/last in legacy mode)
    # + ending (from Slide Review or last Observations row).
    combined = []
    n = len(data_rows)
    if intro_row_data is not None:
        combined.append((intro_row_data, "intro"))
        findings = data_rows
    else:
        # Legacy: first data row was intro, last was ending
        if n >= 2:
            combined.append((data_rows[0], "intro"))
        findings = data_rows[1:-1] if n >= 3 else (data_rows[1:] if n >= 2 else [])
    for f in findings:
        combined.append((f, "finding"))
    if ending_row_data is not None:
        combined.append((ending_row_data, "ending"))
    elif intro_row_data is None and n >= 3:
        combined.append((data_rows[-1], "ending"))

    for i, (row, stype) in enumerate(combined):
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


def _write_slide_review_tab(spreadsheet_id, header, intro_row, ending_row):
    """Create/populate 'Slide Review' tab with just the intro + ending rows."""
    _add_sheet_tab(spreadsheet_id, "Slide Review")
    _composio_execute("GOOGLESHEETS_BATCH_UPDATE", {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": "Slide Review",
        "first_cell_location": "A1",
        "valueInputOption": "USER_ENTERED",
        "values": [header, intro_row, ending_row],
    })


def _write_sources_tab(spreadsheet_id):
    """Add a hidden 'Sources' tab with methodology + per-stat citations."""
    from audit import sources as _sources
    # Add the tab
    _add_sheet_tab(spreadsheet_id, "Sources")
    # Look up its numeric sheetId
    info = _composio_execute("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                             {"spreadsheet_id": spreadsheet_id}) or {}
    sheet_id = None
    for s in (info.get("sheets") or []):
        props = s.get("properties") or {}
        if props.get("title") == "Sources":
            sheet_id = props.get("sheetId")
            break
    # Write the HTML block by pasting values row-by-row
    rows = [["Sources & methodology"], [""],
            ["1. Lead math — how percentages become leads"]]
    for k, v in _sources.LEAD_MATH:
        rows.append([k, v])
    rows.append([""])
    rows.append(["2. Per-finding stat sources"])
    rows.append(["Finding key", "Stat", "Signal", "Source"])
    for key, stat, direction, source in _sources.STAT_SOURCES:
        rows.append([key, stat, direction, source])
    _composio_execute("GOOGLESHEETS_BATCH_UPDATE", {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": "Sources",
        "first_cell_location": "A1",
        "valueInputOption": "USER_ENTERED",
        "values": rows,
    })
    # Hide the tab
    if sheet_id is not None:
        try:
            _composio_execute("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
                "spreadsheetId": spreadsheet_id,
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "hidden": True},
                    "fields": "hidden",
                }})
        except Exception as exc:
            print(f"[sheets] hide Sources (non-fatal): {exc}")


def append_finding(sheet_url_or_id, url, label, priority="Medium",
                   category=None, finding_key="", overrides=None):
    """Fill the next blank row above the Ending row with a manual finding.

    Sheet is created with 4 blank rows before Ending — this fills them one
    by one. Returns (row_number, None) on success, (None, error_message) on
    failure. Never rewrites existing rows (memory: append-only edits).

    When `finding_key` is a known key in HOOK_COPY (e.g. resolved by the
    live_check chatbot), the row uses that entry's canonical hook_stat,
    hook_ctx, costs and support copy instead of the priority-based fallback.

    `overrides` dict (from llm_frame.frame) can supply explicit hook_stat /
    hook_ctx / costs / support / label / status_label — takes precedence
    over everything else. Any missing field falls back to HOOK_COPY[key]
    then to the priority-based fallback.
    """
    global LAST_ERROR
    LAST_ERROR = ""
    sid = _extract_sheet_id(sheet_url_or_id)
    if not sid:
        return None, "Bad sheet URL"
    if not _sheets_available():
        return None, "COMPOSIO_API_KEY not set"
    try:
        resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": ["Observations!A1:I"],
        })
    except Exception as exc:
        return None, f"read failed: {exc}"
    rows = _extract_first_range(resp) or []
    # Find first blank row after the header (row 1). Ending row no longer
    # lives in Observations — it's on 'Slide Review' — so we scan from the
    # end downwards for the last non-blank row and append after it.
    last_content = 1  # header on row 1
    for i, r in enumerate(rows, start=1):
        if r and any(str(c).strip() for c in r):
            last_content = i
    # Insert right after the last content row
    target_row = last_content + 1
    # If any row between last_content and end already looked ending-like
    # from a legacy sheet, land before it.
    for i, r in enumerate(rows, start=1):
        if r and str(r[0] if r else "").strip().startswith("Ending") and i <= target_row:
            target_row = i
            break
    from audit.hook_copy import for_row as _hf
    copy = _hf(finding_key, default_obs=label, default_costs="", priority=priority)
    overrides = overrides or {}
    hook_stat = overrides.get("hook_stat") or copy["hook_stat"]
    hook_ctx  = overrides.get("hook_ctx")  or copy["hook_ctx"]
    costs     = overrides.get("costs")     or copy["costs"] \
                or f"{label}, flagged manually during review."
    support   = overrides.get("support") if overrides.get("support") is not None \
                else copy["support"]
    row_label = overrides.get("label")    or label
    row_priority = overrides.get("priority") or priority
    row_category = overrides.get("category") or category or "Manual"
    pill = overrides.get("status_label") or row_label
    ctx_body = hook_ctx.replace('"', '""')
    formula = (
        f'=IF(E{target_row}="","{ctx_body}",'
        f'IFERROR(TEXT(E{target_row},"+#.#%;-#.#%;0%")&" "&"{ctx_body}",'
        f'E{target_row}&" "&"{ctx_body}"))'
    )
    values = [[
        row_category,
        row_label,
        row_priority,
        "",
        hook_stat,
        formula,
        f"{url} | {pill}" if url else f"Site-wide | {pill}",
        costs,
        support,
    ]]
    try:
        _composio_execute("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid,
            "sheet_name": "Observations",
            "first_cell_location": f"A{target_row}",
            "valueInputOption": "USER_ENTERED",
            "values": values,
        })
    except Exception as exc:
        return None, f"write failed: {exc}"
    return target_row, None


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
