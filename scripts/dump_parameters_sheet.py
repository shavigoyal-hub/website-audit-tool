"""Create a standalone Google Sheet with the full parameter catalog.

Run:  python3 scripts/dump_parameters_sheet.py

Prints the sheet URL. Uses the same Composio creds the audit tool uses.
"""
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.hook_copy import HOOK_COPY, STATUS_LABEL
from audit.report_sheets import (
    _LEAD_KEYS_MASTER, _primary_signal,
    _create_spreadsheet, _add_sheet_tab, _rename_sheet,
    _composio_execute, _share, _get_placeholder_sheet_id,
)


def main():
    from datetime import date
    title = f"Gushwork audit parameter catalog — {date.today().isoformat()}"
    sid = _create_spreadsheet(title)
    if not sid:
        print("ERROR: could not create spreadsheet")
        sys.exit(1)

    # Rename the default first tab to "Parameters" instead of adding a new
    # tab (which would leave Sheet1 as a blank leftover).
    ph_id, _ph_title = _get_placeholder_sheet_id(sid)
    if ph_id is not None:
        _rename_sheet(sid, int(ph_id), "Parameters")
    else:
        _add_sheet_tab(sid, "Parameters")

    header = ["Key", "Label", "Priority", "Primary signal", "Hook stat",
              "Hook context", "Costs", "Support", "In lead-sum"]
    rows = [header]
    for key in sorted(HOOK_COPY.keys()):
        spec = HOOK_COPY.get(key) or {}
        label_tuple = STATUS_LABEL.get(key) or (key, "medium")
        label, prio = label_tuple[0], label_tuple[1].title()
        ctx = spec.get("hook_ctx", "")
        rows.append([
            key, label, prio,
            _primary_signal(key, ctx),
            spec.get("hook_stat", ""),
            ctx,
            spec.get("costs", ""),
            spec.get("support", ""),
            "YES" if key in _LEAD_KEYS_MASTER else "",
        ])
    _composio_execute("GOOGLESHEETS_BATCH_UPDATE", {
        "spreadsheet_id": sid,
        "sheet_name": "Parameters",
        "first_cell_location": "A1",
        "valueInputOption": "USER_ENTERED",
        "values": rows,
    })
    _share(sid)
    url = f"https://docs.google.com/spreadsheets/d/{sid}"
    print(f"\n✅ Parameter catalog sheet: {url}")
    print(f"   {len(rows)-1} parameters, {len(_LEAD_KEYS_MASTER)} in lead-sum.")


if __name__ == "__main__":
    main()
