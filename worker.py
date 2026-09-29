"""Local worker: pulls jobs from the Jobs tab and runs the SF audit.

Run on your Mac:  python3 worker.py
Keep it awake:    caffeinate -i python3 worker.py
Auto-start:       load com.gushwork.audit-worker.plist into launchd

Env: COMPOSIO_API_KEY, optional PAGESPEED_API_KEY (same as Flask app).
"""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import traceback

from audit import jobs
from audit.pipeline import SF_AVAILABLE


# Per-job wall-clock cap. 0 = no cap. Enforced by killing the pipeline
# SUBPROCESS with SIGKILL when it exceeds this — the OS kernel enforces it,
# so a hung HTTP read cannot survive it (unlike the old SIGALRM path,
# which couldn't interrupt native socket blocks).
_JOB_TIMEOUT_SEC = int(os.environ.get("WORKER_JOB_TIMEOUT_SEC", "0"))


class _JobTimeout(Exception):
    pass


def _run_pipeline_subprocess(live_url, timeout=0):
    """Run pipeline.run in a real subprocess. Parent kills it if it hangs.

    Returns the pipeline result dict on success, raises RuntimeError or
    _JobTimeout on failure. Because the pipeline runs in a separate OS
    process, SIGKILL from the parent is guaranteed to end it no matter
    what the child was blocked on (Composio HTTP, SF subprocess, PSI,
    even native OpenSSL).
    """
    cmd = [sys.executable, "-m", "audit.pipeline_cli", live_url]
    # Inherit the parent's env (COMPOSIO_API_KEY / OPENAI_API_KEY / etc.)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=os.environ.copy(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=(timeout or None))
    except subprocess.TimeoutExpired:
        # Escalate: SIGTERM (5s grace) then SIGKILL — kernel-enforced.
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        raise _JobTimeout(f"pipeline subprocess exceeded {timeout}s and was killed")

    if proc.returncode != 0 and not stdout.strip():
        raise RuntimeError(f"pipeline subprocess exit {proc.returncode}\n"
                            f"stderr:\n{stderr[-2000:]}")
    # Parse the last JSON line the subprocess printed. Its own log lines
    # from pipeline / judge / worker also go to stdout, so pick the last
    # complete JSON object.
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not payload.get("ok"):
                raise RuntimeError(payload.get("error", "unknown subprocess error"))
            return payload["res"]
    raise RuntimeError(f"pipeline subprocess produced no JSON result\n"
                        f"stderr:\n{stderr[-2000:]}")


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
    to_str = f"{args.timeout}s (SIGKILL if exceeded)" if args.timeout > 0 else "off"
    print(f"[worker] {worker_id} — SF={'yes' if SF_AVAILABLE else 'no'} "
          f"— poll every {args.poll}s, per-job timeout {to_str}, "
          f"pipeline runs in subprocess (kill-safe)")
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
            res = _run_pipeline_subprocess(job["live_url"], timeout=args.timeout)
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
