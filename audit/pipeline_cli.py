"""Run pipeline.run(live_url) and print the result as JSON to stdout.

Wrapped this way so worker.py can execute the pipeline as a real OS
subprocess. A subprocess can be SIGKILLed by the parent — Python's
signal.alarm can't. This is how we guarantee no Composio / SF / PSI hang
ever wedges the worker indefinitely.

CLI:  python3 -m audit.pipeline_cli <live_url>
STDOUT: one JSON object per successful run, or one JSON object with
        {"ok": false, "error": "..."} on any error.
"""
import contextlib
import json
import sys
import traceback


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: pipeline_cli <url>"}))
        sys.exit(2)
    live_url = sys.argv[1]
    real_stdout = sys.stdout
    try:
        # Route pipeline's own print() logs to stderr so the parent can
        # parse the final JSON from stdout cleanly.
        with contextlib.redirect_stdout(sys.stderr):
            from audit.pipeline import run as _run
            res = _run(live_url)
        real_stdout.write(json.dumps({"ok": True, "res": res}) + "\n")
        real_stdout.flush()
    except Exception:
        real_stdout.write(json.dumps({"ok": False, "error": traceback.format_exc()}) + "\n")
        real_stdout.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
