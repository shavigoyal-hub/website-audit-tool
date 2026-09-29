"""Pull the master parameter sheet into parameters_data.json.

The audit tool loads parameters_data.json at import time to override
HOOK_COPY / STATUS_LABEL / lead-sum membership. Workflow:

  1. Edit the Google Sheet.
  2. Run:  python3 scripts/sync_parameters_from_sheet.py [<sheet_url>]
     (defaults to the sheet id below when no arg is given)
  3. git commit + push
  4. Restart the worker so it picks up the new JSON.

Expected header row (in order): Key, Label, Priority, Primary signal,
Hook stat, Hook context, Costs, Support, In lead-sum.
Extra columns are ignored. Missing columns log a warning.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.report_sheets import _composio_execute, _extract_sheet_id

DEFAULT_SHEET_ID = "16aJEm6EuHVDvu2yw0EnHMjXflxUdgJjfbDtIMBkNDyY"
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "parameters_data.json")

EXPECTED = ["key", "label", "priority", "primary_signal", "hook_stat",
            "hook_ctx", "costs", "support", "in_lead_sum"]


def _norm(h):
    h = (h or "").strip().lower()
    return {
        "key": "key", "label": "label", "priority": "priority",
        "primary signal": "primary_signal", "primary": "primary_signal",
        "hook stat": "hook_stat", "stat": "hook_stat",
        "hook context": "hook_ctx", "hook_ctx": "hook_ctx", "context": "hook_ctx",
        "costs": "costs", "support": "support",
        "in lead-sum": "in_lead_sum", "in_lead_sum": "in_lead_sum",
        "lead-sum": "in_lead_sum", "in lead sum": "in_lead_sum",
    }.get(h, h)


def main():
    sheet_id = DEFAULT_SHEET_ID
    if len(sys.argv) > 1:
        sheet_id = _extract_sheet_id(sys.argv[1])

    # Pull the Parameters tab
    resp = _composio_execute("GOOGLESHEETS_BATCH_GET", {
        "spreadsheet_id": sheet_id,
        "ranges": ["Parameters!A1:I500"],
    })
    values = None
    for _key in ("valueRanges", "value_ranges", "data"):
        vr = (resp or {}).get(_key)
        if vr and isinstance(vr, list) and vr:
            values = vr[0].get("values") or []
            break
    if not values:
        # Some Composio builds bury values under 'response_data'
        rd = (resp or {}).get("response_data") or {}
        vr = rd.get("valueRanges") or rd.get("value_ranges") or []
        if vr:
            values = vr[0].get("values") or []

    if not values or len(values) < 2:
        print(f"ERROR: no rows read from sheet {sheet_id}")
        print(f"  raw resp keys: {list((resp or {}).keys())[:8]}")
        sys.exit(1)

    header = [_norm(h) for h in values[0]]
    unknown = [h for h in header if h not in EXPECTED]
    if unknown:
        print(f"  (ignoring unknown columns: {unknown})")
    missing = [c for c in EXPECTED if c not in header]
    if missing:
        print(f"  WARNING: missing columns will be blank: {missing}")

    data = {}
    for row in values[1:]:
        # pad row to header length
        row = list(row) + [""] * (len(header) - len(row))
        entry = {}
        for h, cell in zip(header, row):
            if h in EXPECTED and h != "key":
                entry[h] = (cell or "").strip()
        key = ""
        for h, cell in zip(header, row):
            if h == "key":
                key = (cell or "").strip()
                break
        if not key:
            continue
        data[key] = entry

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)

    leadcount = sum(1 for v in data.values()
                    if str(v.get("in_lead_sum", "")).strip().upper()
                    in {"YES", "TRUE", "1"})
    print(f"✅ Synced {len(data)} params → {OUT_PATH}")
    print(f"   {leadcount} marked YES for lead-sum")
    print(f"\nNext: git add parameters_data.json && git commit -m 'sync params' && git push")
    print(f"Then restart the worker.")


if __name__ == "__main__":
    main()
