"""Local worker: pulls jobs from the Jobs tab and runs the SF audit.

Run on your Mac:  python3 worker.py
Keep it awake:    caffeinate -i python3 worker.py
Auto-start:       load com.gushwork.audit-worker.plist into launchd

Env: COMPOSIO_API_KEY, optional PAGESPEED_API_KEY (same as Flask app).
"""
import argparse
import signal
import socket
import time
import traceback

from audit import jobs
from audit.pipeline import SF_AVAILABLE, run as _run


# Absolute wall-clock ceiling per job. A stuck Composio/PSI call has caused
# jobs to hang for 1h+ before — we'd rather fail visibly than block the queue.
_JOB_TIMEOUT_SEC = 15 * 60


class _JobTimeout(Exception):
    pass


def _run_with_timeout(fn, args, timeout):
    """Run `fn(*args)` in-process, raise _JobTimeout after `timeout` seconds.

    Uses signal.SIGALRM (POSIX only, fine for macOS/Linux worker). Blocking
    syscalls (subprocess.run for SF, requests.get for PSI, Composio HTTP)
    all get interrupted by the alarm.
    """
    def _handler(signum, frame):
        raise _JobTimeout(f"job exceeded {timeout}s")

    prev = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(int(timeout))
    try:
        return fn(*args)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


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
            res = _run_with_timeout(_run, (job["live_url"],), args.timeout)
            sheet = res.get("sheet_url") or ""
            crawler = res.get("crawler", "")
            counts = res["metrics"]["counts"]
            pages = counts.get("pages_crawled", 0)
            composio_calls = counts.get("composio_calls", 0)
            psi_calls = counts.get("psi_calls", 0)
            cost_usd = res["metrics"].get("est_cost_usd", 0)
            jobs.mark_done(job["id"], sheet,
                            crawler=crawler, pages=pages,
                            composio_calls=composio_calls,
                            psi_calls=psi_calls,
                            cost_usd=cost_usd)
            print(f"[worker] done {job['id']} → {sheet}  "
                  f"(crawler={crawler}, pages={pages}, "
                  f"composio={composio_calls}, psi={psi_calls}, "
                  f"cost=${cost_usd})")
        except _JobTimeout as exc:
            print(f"[worker] timeout {job['id']}: {exc}")
            jobs.mark_error(job["id"], str(exc))
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
