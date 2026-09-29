"""Local worker: pulls jobs from the Jobs tab and runs the SF audit.

Run on your Mac:  python3 worker.py
Keep it awake:    caffeinate -i python3 worker.py
Auto-start:       load com.gushwork.audit-worker.plist into launchd

Env: COMPOSIO_API_KEY, optional PAGESPEED_API_KEY (same as Flask app).
"""
import argparse
import multiprocessing as _mp
import socket
import time
import traceback

from audit import jobs
from audit.pipeline import SF_AVAILABLE, run as _run


# Absolute wall-clock ceiling per job. A stuck Composio/PSI call has caused
# jobs to hang for 1h+ before — we'd rather fail visibly than block the queue.
_JOB_TIMEOUT_SEC = 15 * 60


def _run_in_subprocess(live_url, out_q):
    try:
        out_q.put({"ok": True, "res": _run(live_url)})
    except Exception:
        out_q.put({"ok": False, "err": traceback.format_exc()})


def _reset_ghost_jobs(worker_id):
    """On startup, flip anything left in 'running' for this worker to error.

    Fixes the case where a previous worker process died mid-audit (SIGKILL,
    Python crash, Composio hang) and left a row stuck in 'running' with no
    finished_utc, blocking the UI from ever getting a done signal.
    """
    try:
        for j in jobs.list_recent(50):
            if j["status"] == "running" and j["worker"] == worker_id:
                print(f"[worker] resetting ghost job {j['id']} ({j['live_url']})")
                jobs.mark_error(j["id"], "worker exited before this job finished")
    except Exception as exc:
        print(f"[worker] ghost reset failed: {exc}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--poll", type=int, default=20,
                   help="Seconds between pending-job checks (default 20)")
    p.add_argument("--once", action="store_true",
                   help="Claim one job and exit")
    p.add_argument("--timeout", type=int, default=_JOB_TIMEOUT_SEC,
                   help=f"Per-job hard timeout in seconds (default {_JOB_TIMEOUT_SEC})")
    args = p.parse_args()

    worker_id = socket.gethostname()
    print(f"[worker] {worker_id} — SF={'yes' if SF_AVAILABLE else 'no'} "
          f"— poll every {args.poll}s, per-job timeout {args.timeout}s")
    _reset_ghost_jobs(worker_id)

    while True:
        try:
            job = jobs.claim_next(worker_id)
        except Exception as exc:
            print(f"[worker] claim error: {exc}")
            time.sleep(args.poll)
            continue

        if not job:
            if args.once:
                print("[worker] no pending jobs")
                return
            time.sleep(args.poll)
            continue

        print(f"[worker] claimed {job['id']} → {job['live_url']}")
        try:
            # Run the pipeline in a subprocess so we can kill it if it
            # hangs (Composio/PSI calls have blocked for 1h+ in the past).
            ctx = _mp.get_context("spawn")
            q = ctx.Queue()
            proc = ctx.Process(target=_run_in_subprocess,
                                args=(job["live_url"], q))
            proc.start()
            proc.join(timeout=args.timeout)
            if proc.is_alive():
                proc.terminate()
                proc.join(5)
                if proc.is_alive():
                    proc.kill()
                raise TimeoutError(
                    f"pipeline exceeded {args.timeout}s and was killed")
            payload = q.get(timeout=5) if not q.empty() else \
                      {"ok": False, "err": "subprocess exited with no result"}
            if not payload.get("ok"):
                raise RuntimeError(payload.get("err", "unknown subprocess error"))
            res = payload["res"]
            sheet = res.get("sheet_url") or ""
            crawler = res.get("crawler", "")
            pages = res["metrics"]["counts"].get("pages_crawled", 0)
            jobs.mark_done(job["id"], sheet, crawler=crawler, pages=pages)
            print(f"[worker] done {job['id']} → {sheet}  "
                  f"(crawler={crawler}, pages={pages}, "
                  f"cost=${res['metrics']['est_cost_usd']})")
        except KeyboardInterrupt:
            jobs.mark_error(job["id"], "worker interrupted")
            print("[worker] interrupted; job marked error")
            return
        except Exception:
            err = traceback.format_exc()
            print(f"[worker] error {job['id']}:\n{err}")
            jobs.mark_error(job["id"], err)

        if args.once:
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[worker] stopped")
