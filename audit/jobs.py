"""Job queue backed by a `Jobs` tab in the shared history sheet.

Flow:
  Vercel /run                    → jobs.enqueue()           status=pending
  worker.py on the Mac (poller)  → jobs.claim_next()        status=running
                                 → jobs.mark_done()         status=done
                                 → jobs.mark_error()        status=error
Browser polls /job/<id> to render progress + final sheet_url.
"""
import datetime as _dt
import uuid

from audit.composio_exec import execute as _cx
from audit.history import _find_history_sheet as _find_sheet

JOBS_TAB = "Jobs"
JOB_HEADER = ["id", "created_utc", "client", "live_url",
              "status", "worker", "started_utc", "finished_utc",
              "sheet_url", "error"]


def _ensure_tab(sid):
    try:
        info = _cx("GOOGLESHEETS_GET_SPREADSHEET_INFO",
                   {"spreadsheet_id": sid}) or {}
        titles = [(s.get("properties") or {}).get("title", "")
                  for s in (info.get("sheets") or [])]
        if JOBS_TAB in titles:
            return
        resp = _cx("GOOGLESHEETS_ADD_SHEET", {
            "spreadsheet_id": sid, "title": JOBS_TAB,
            "sheet_name": JOBS_TAB}) or {}
        new_id = None
        for r in (resp.get("replies") or []) if isinstance(resp, dict) else []:
            add = (r or {}).get("addSheet") or {}
            new_id = add.get("sheetId") or (add.get("properties") or {}).get("sheetId")
            if new_id:
                break
        if new_id is not None:
            _cx("GOOGLESHEETS_UPDATE_SHEET_PROPERTIES", {
                "spreadsheetId": sid,
                "updateSheetProperties": {
                    "properties": {"sheetId": new_id, "title": JOBS_TAB,
                                   "gridProperties": {"frozenRowCount": 1}},
                    "fields": "title,gridProperties.frozenRowCount",
                }})
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
            "first_cell_location": "A1",
            "valueInputOption": "USER_ENTERED",
            "values": [JOB_HEADER],
        })
    except Exception as exc:
        print(f"[jobs] ensure_tab: {exc}")


def _read_rows(sid):
    try:
        resp = _cx("GOOGLESHEETS_BATCH_GET", {
            "spreadsheet_id": sid, "ranges": [f"{JOBS_TAB}!A1:J"]})
    except Exception as exc:
        print(f"[jobs] read: {exc}")
        return []
    ranges = (resp.get("valueRanges") if isinstance(resp, dict) else None) or []
    return (ranges[0].get("values") or []) if ranges else []


def _now():
    return _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _find_row(sid, job_id):
    for i, r in enumerate(_read_rows(sid)[1:], start=2):
        if r and r[0] == job_id:
            return i
    return None


def enqueue(client, live_url):
    sid = _find_sheet()
    if not sid:
        return None
    _ensure_tab(sid)
    rows = _read_rows(sid)
    row_num = (len(rows) + 1) if rows else 1
    jid = uuid.uuid4().hex[:8]
    try:
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
            "first_cell_location": f"A{row_num}",
            "valueInputOption": "USER_ENTERED",
            "values": [[jid, _now(), client, live_url,
                        "pending", "", "", "", "", ""]],
        })
        return jid
    except Exception as exc:
        print(f"[jobs] enqueue: {exc}")
        return None


def get(job_id):
    sid = _find_sheet()
    if not sid:
        return None
    for r in _read_rows(sid)[1:]:
        while len(r) < len(JOB_HEADER):
            r.append("")
        if r[0] == job_id:
            return dict(zip(JOB_HEADER, r))
    return None


def claim_next(worker_id):
    """First pending row → running (best-effort atomic — race is a re-run)."""
    sid = _find_sheet()
    if not sid:
        return None
    _ensure_tab(sid)
    rows = _read_rows(sid)
    for i, r in enumerate(rows[1:], start=2):
        while len(r) < len(JOB_HEADER):
            r.append("")
        if r[4] == "pending":
            ts = _now()
            try:
                _cx("GOOGLESHEETS_BATCH_UPDATE", {
                    "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
                    "first_cell_location": f"E{i}",
                    "valueInputOption": "USER_ENTERED",
                    "values": [["running", worker_id, ts]],
                })
            except Exception as exc:
                print(f"[jobs] claim: {exc}")
                return None
            r[4] = "running"
            r[5] = worker_id
            r[6] = ts
            return dict(zip(JOB_HEADER, r))
    return None


def mark_done(job_id, sheet_url):
    sid = _find_sheet()
    row = _find_row(sid, job_id) if sid else None
    if not row:
        return False
    _cx("GOOGLESHEETS_BATCH_UPDATE", {
        "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
        "first_cell_location": f"E{row}",
        "valueInputOption": "USER_ENTERED",
        "values": [["done", "", "", _now(), sheet_url or "", ""]],
    })
    return True


def mark_error(job_id, err):
    sid = _find_sheet()
    row = _find_row(sid, job_id) if sid else None
    if not row:
        return False
    _cx("GOOGLESHEETS_BATCH_UPDATE", {
        "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
        "first_cell_location": f"E{row}",
        "valueInputOption": "USER_ENTERED",
        "values": [["error", "", "", _now(), "", (err or "")[:500]]],
    })
    return True


def list_recent(n=25, statuses=None):
    """Return latest N jobs (newest first)."""
    sid = _find_sheet()
    if not sid:
        return []
    rows = _read_rows(sid)
    if not rows:
        return []
    out = []
    for r in rows[1:]:
        while len(r) < len(JOB_HEADER):
            r.append("")
        d = dict(zip(JOB_HEADER, r))
        if statuses and d["status"] not in statuses:
            continue
        out.append(d)
    out.reverse()
    return out[:n]
