"""Composio tools-execute helper.

Pattern borrowed from the SEO-Reporting project which has this working
against the same Composio account. We POST to
    /api/v3/tools/execute/{SLUG}
with { user_id, arguments } — Composio proxies to Google using the
connected account's OAuth token server-side. No raw tokens leave Composio.
"""
import json
import os
import time

import requests

_BASE = "https://backend.composio.dev/api/v3"
_TIMEOUT = 60

# Diagnostic trace of the last execute (surfaced via /run response).
LAST_TRACE = []


def _api_key():
    return os.environ.get("COMPOSIO_API_KEY", "").strip() or None


def _user_id():
    return (
        os.environ.get("COMPOSIO_ENTITY_ID")
        or os.environ.get("entity_id")
        or "default"
    )


def execute(slug, arguments, retry=3):
    """Call POST /api/v3/tools/execute/{slug}. Returns response_data or raises."""
    key = _api_key()
    if not key:
        raise RuntimeError("COMPOSIO_API_KEY not set")

    # Pick a user_id — Composio auto-resolves the ACTIVE connection under it.
    # Try our env user first, then 'default' (that's where the Sheets/Drive
    # connections actually live per the earlier debug).
    candidate_uids = [_user_id()]
    if "default" not in candidate_uids:
        candidate_uids.append("default")

    last_err = None
    for uid in candidate_uids:
        body = {"user_id": uid, "arguments": arguments}
        for attempt in range(1, retry + 1):
            try:
                resp = requests.post(
                    f"{_BASE}/tools/execute/{slug}",
                    headers={"x-api-key": key, "Content-Type": "application/json"},
                    data=json.dumps(body),
                    timeout=_TIMEOUT,
                )
                LAST_TRACE.append({
                    "slug": slug, "user_id": uid, "status": resp.status_code,
                    "body_preview": resp.text[:300],
                })
                if resp.status_code in (502, 503, 504) and attempt < retry:
                    time.sleep(0.5 * attempt)
                    continue
                parsed = resp.json()
                if resp.ok and parsed.get("successful", True) and not parsed.get("error"):
                    data = parsed.get("data") or {}
                    if isinstance(data, dict) and "response_data" in data:
                        return data["response_data"]
                    return data
                # Composio returned an error — capture and try next user_id
                err = parsed.get("error")
                if isinstance(err, dict):
                    last_err = f"{slug}: {err.get('message', err)} [{err.get('slug', '')}]"
                else:
                    last_err = f"{slug}: {err or resp.text[:300]}"
                break  # don't retry the same uid — try next
            except Exception as exc:
                last_err = f"{slug}: {exc}"
                if attempt < retry:
                    time.sleep(0.5 * attempt)
    raise RuntimeError(last_err or f"{slug} failed with no error message")


def reset_trace():
    LAST_TRACE.clear()
