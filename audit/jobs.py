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
              "sheet_url", "error", "crawler", "pages",
              "composio_calls", "psi_calls", "cost_usd",
              # WHO QUEUED IT (Shavi, 2026-09-30): the host the /run request
              # came in on — "seo-reporting-five.vercel.app" when the audit
              # was started from inside the SEO Reporting tool. That tool's
              # Runs & history page reads this tab and shows only the rows it
              # queued itself; the standalone deployment's audits stay off it.
              "source"]


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
            "spreadsheet_id": sid, "ranges": [f"{JOBS_TAB}!A1:P"]})
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


LAST_ENQUEUE_ERROR = ""

# Row-index cache populated by claim_next, consumed by mark_done /
# mark_error so those don't need a second whole-sheet read (which was
# tripping the 429 per-user Sheets read quota). Values are (row, ts) —
# anything older than 2h is pruned on next access so a worker crashing
# mid-job doesn't leak the entry forever.
_CLAIMED_ROWS = {}
_CLAIMED_TTL_SEC = 7200


def enqueue(client, live_url, source=""):
    """Fast append-only enqueue. Avoids the slow _ensure_tab + _read_rows
    round-trips that were timing out Vercel's lambda window — uses the
    append endpoint instead so Google places the row at the first blank.
    """
    global LAST_ENQUEUE_ERROR
    LAST_ENQUEUE_ERROR = ""
    sid = _find_sheet()
    if not sid:
        LAST_ENQUEUE_ERROR = "no history sheet id"
        return None
    jid = uuid.uuid4().hex[:8]
    row = [jid, _now(), client, live_url,
           "pending", "", "", "", "", "",
           "", "", "", "", "", source or ""]
    # Try append first — one API call, no reads.
    try:
        _cx("GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND", {
            "spreadsheet_id": sid,
            "range": f"{JOBS_TAB}!A1",
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
            "values": [row],
        })
        return jid
    except Exception as exc:
        LAST_ENQUEUE_ERROR = f"append: {exc}"[:300]
        print(f"[jobs] enqueue append failed: {exc}")
    # Fallback: ensure tab exists and retry with BATCH_UPDATE at next row.
    try:
        _ensure_tab(sid)
        rows = _read_rows(sid)
        row_num = (len(rows) + 1) if rows else 1
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
            "first_cell_location": f"A{row_num}",
            "valueInputOption": "USER_ENTERED",
            "values": [row],
        })
        return jid
    except Exception as exc:
        LAST_ENQUEUE_ERROR = f"batch_update: {exc}"[:300]
        print(f"[jobs] enqueue fallback failed: {exc}")
        return None


def get(job_id):
    """Fetch a job row by id.

    Retries with a cleared sheet-id cache if the row is not found — a warm
    Vercel lambda can hold a stale HISTORY_SHEET_ID from a previous env
    setting, which would silently point /job at the wrong sheet.
    """
    def _lookup():
        sid = _find_sheet()
        if not sid:
            return None
        for r in _read_rows(sid)[1:]:
            while len(r) < len(JOB_HEADER):
                r.append("")
            if r[0] == job_id:
                return dict(zip(JOB_HEADER, r))
        return None

    row = _lookup()
    if row is not None:
        return row
    # Retry after clearing the module-level cache so a stale warm lambda
    # can re-resolve the correct sheet.
    from audit import history as _hist
    _hist._CACHED_ID = None
    return _lookup()


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
            # Remember where this job lives so mark_done / mark_error can
            # skip the follow-up _find_row read. Prune stale entries first.
            import time as _time
            _now_ts = _time.time()
            for _k, _v in list(_CLAIMED_ROWS.items()):
                if isinstance(_v, tuple) and _now_ts - _v[1] > _CLAIMED_TTL_SEC:
                    _CLAIMED_ROWS.pop(_k, None)
            _CLAIMED_ROWS[r[0]] = (i, _now_ts)
            return dict(zip(JOB_HEADER, r))
    return None


def mark_done(job_id, sheet_url, crawler="", pages="",
              composio_calls="", psi_calls="", cost_usd=""):
    sid = _find_sheet()
    if not sid:
        return False
    row = _pop_claimed_row(job_id) or _find_row(sid, job_id)
    if not row:
        return False
    try:
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
            "first_cell_location": f"E{row}",
            "valueInputOption": "USER_ENTERED",
            "values": [["done", "", "", _now(), sheet_url or "", "",
                        crawler or "",
                        pages if pages != "" else "",
                        composio_calls if composio_calls != "" else "",
                        psi_calls if psi_calls != "" else "",
                        cost_usd if cost_usd != "" else ""]],
        })
        return True
    except Exception as exc:
        # On 429 (quota), swallow — the audit sheet was already built, we
        # just can't tag the job row. Better than crashing the worker loop.
        print(f"[jobs] mark_done quota/err: {exc}")
        return False


def _pop_claimed_row(job_id):
    """Pull the cached row index for a job, unwrapping the (row, ts) tuple."""
    v = _CLAIMED_ROWS.pop(job_id, None)
    if isinstance(v, tuple):
        return v[0]
    return v  # legacy bare-int cache entry, or None


def mark_error(job_id, err):
    sid = _find_sheet()
    if not sid:
        return False
    row = _pop_claimed_row(job_id) or _find_row(sid, job_id)
    if not row:
        return False
    try:
        _cx("GOOGLESHEETS_BATCH_UPDATE", {
            "spreadsheet_id": sid, "sheet_name": JOBS_TAB,
            "first_cell_location": f"E{row}",
            "valueInputOption": "USER_ENTERED",
            "values": [["error", "", "", _now(), "", (err or "")[:3000]]],
        })
        return True
    except Exception as exc:
        print(f"[jobs] mark_error quota/err: {exc}")
        return False


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
