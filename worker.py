"""Local worker: pulls jobs from the Jobs tab and runs the SF audit.

Run on your Mac:  python3 worker.py
Keep it awake:    caffeinate -i python3 worker.py
Auto-start:       load com.gushwork.audit-worker.plist into launchd

Env: COMPOSIO_API_KEY, optional PAGESPEED_API_KEY (same as Flask app).
"""
import argparse
import socket
import time
import traceback

from audit import jobs
from audit.pipeline import SF_AVAILABLE, run as _run


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--poll", type=int, default=20,
                   help="Seconds between pending-job checks (default 20)")
    p.add_argument("--once", action="store_true",
                   help="Claim one job and exit")
    args = p.parse_args()

    worker_id = socket.gethostname()
    print(f"[worker] {worker_id} — SF={'yes' if SF_AVAILABLE else 'no'} "
          f"— poll every {args.poll}s")

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
            res = _run(job["live_url"])
            sheet = res.get("sheet_url") or ""
            jobs.mark_done(job["id"], sheet)
            print(f"[worker] done {job['id']} → {sheet}  "
                  f"(cost ${res['metrics']['est_cost_usd']}, "
                  f"pages {res['metrics']['counts']['pages_crawled']})")
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
