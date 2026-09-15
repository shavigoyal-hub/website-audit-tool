"""Composio-based Google auth for report_sheets / report_slides.

When COMPOSIO_API_KEY is set, fetches the OAuth access token for a
connected Google account (Sheets or Drive) via Composio's REST API and
returns google.oauth2.credentials.Credentials that plug into the existing
google-api-python-client code paths.

If it doesn't work we return None and the caller falls back to
GOOGLE_SERVICE_ACCOUNT_JSON. The last-attempt debug info is stored in
LAST_DEBUG so /health can display it.

Env vars:
    COMPOSIO_API_KEY     — required
    COMPOSIO_ENTITY_ID   — Composio entity/user id; defaults to
                            AUDIT_SHARE_EMAIL or shavi.goyal@gushwork.ai
"""
import os

import requests

_BASE = "https://backend.composio.dev"
_TIMEOUT = 15

# Last debug trace — /health reads this
LAST_DEBUG = {}


def _api_key():
    return os.environ.get("COMPOSIO_API_KEY", "").strip() or None


def _entity_id():
    return (
        os.environ.get("COMPOSIO_ENTITY_ID")
        or os.environ.get("AUDIT_SHARE_EMAIL")
        or "shavi.goyal@gushwork.ai"
    )


def _try(method, path, params=None, note=""):
    """Hit a Composio endpoint. Return (status, json_or_text). Log to LAST_DEBUG."""
    url = _BASE + path
    key = _api_key()
    if not key:
        LAST_DEBUG.setdefault("attempts", []).append({"note": note, "error": "no api key"})
        return None, None
    try:
        resp = requests.request(
            method, url,
            headers={"X-API-Key": key, "Content-Type": "application/json"},
            params=params, timeout=_TIMEOUT,
        )
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:400]
        LAST_DEBUG.setdefault("attempts", []).append({
            "note": note, "path": path, "params": params,
            "status": resp.status_code,
            "body_preview": str(body)[:400],
        })
        return resp.status_code, body
    except Exception as exc:
        LAST_DEBUG.setdefault("attempts", []).append({
            "note": note, "path": path, "error": str(exc)[:200],
        })
        return None, None


def _extract_token(item):
    """Try to pull an access_token out of a connected-account item, whatever schema."""
    if not isinstance(item, dict):
        return None
    # Common shapes across Composio API versions
    for path in (
        ("connectionParams", "access_token"),
        ("connectionParams", "accessToken"),
        ("credentials", "access_token"),
        ("credentials", "accessToken"),
        ("params", "access_token"),
        ("meta", "access_token"),
        ("data", "access_token"),
    ):
        node = item
        ok = True
        for k in path:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                ok = False; break
        if ok and isinstance(node, str) and node:
            return node
    # Top-level
    for k in ("access_token", "accessToken"):
        if isinstance(item.get(k), str) and item[k]:
            return item[k]
    return None


def _find_connection_id(body, target_slug):
    """Return the connection id (ca_...) whose toolkit slug matches target_slug."""
    target = (target_slug or "").lower().strip()
    if not isinstance(body, dict):
        return None
    for key in ("items", "connectedAccounts", "data", "connections", "accounts"):
        items = body.get(key)
        if isinstance(items, list):
            for item in items:
                app = (item.get("appName") or item.get("app_name")
                       or (item.get("app") or {}).get("name")
                       or (item.get("toolkit") or {}).get("slug") or "").lower().strip()
                if target and app != target:
                    continue
                # Composio v3 uses `id` (ca_...) for connection id
                cid = item.get("id") or item.get("connectionId") or item.get("connection_id")
                if cid:
                    return cid
    return None


def _find_token_in_response(body, target_slug):
    """Fallback: find an access token directly in the response body."""
    target = (target_slug or "").lower().strip()
    if not isinstance(body, dict):
        return None
    for key in ("items", "connectedAccounts", "data", "connections", "accounts"):
        items = body.get(key)
        if isinstance(items, list):
            for item in items:
                app = (item.get("appName") or item.get("app_name")
                       or (item.get("app") or {}).get("name")
                       or (item.get("toolkit") or {}).get("slug") or "").lower().strip()
                if target and app != target:
                    continue
                tok = _extract_token(item)
                if tok:
                    return tok
    # Direct look at top-level (single-connection GET response)
    return _extract_token(body)


def _fetch_access_token(app_name):
    """Fetch a fresh OAuth access token via Composio.

    Composio's LIST endpoint returns cached/stale tokens that Google
    rejects with 401. The correct pattern is:
      1. List connections → find the connection id (ca_...)
      2. GET /api/v3/connected_accounts/{id} → returns the fresh token

    We fall back to token-in-list if the individual GET doesn't yield one.
    """
    entity = _entity_id()
    LAST_DEBUG["target_app"] = app_name
    LAST_DEBUG["entity_id"] = entity

    user_ids = [entity]
    if entity != "default":
        user_ids.append("default")

    # Step 1 — find the connection id
    conn_id = None
    for uid in user_ids:
        for params, note in [
            ({"user_ids": uid, "toolkit_slugs": app_name},
             f"list toolkit+user_ids({uid})"),
            ({"toolkit_slugs": app_name},
             f"list toolkit_slugs only (attempt for {uid})"),
        ]:
            status, body = _try("GET", "/api/v3/connected_accounts",
                                params=params, note=note)
            if status == 200 and body:
                conn_id = _find_connection_id(body, app_name)
                if conn_id:
                    LAST_DEBUG["connection_id"] = conn_id
                    break
        if conn_id:
            break

    if not conn_id:
        return None

    # Step 2 — GET the individual connection to get a fresh token.
    # Composio v3 supports a few variants; try each until one returns 200.
    for path, note in [
        (f"/api/v3/connected_accounts/{conn_id}",           "get connection detail"),
        (f"/api/v3/connected_accounts/{conn_id}/token",     "get connection token"),
        (f"/api/v3/connected_accounts/{conn_id}/refresh",   "refresh connection"),
    ]:
        method = "POST" if path.endswith("/refresh") else "GET"
        status, body = _try(method, path, note=note)
        if status == 200 and body:
            tok = _find_token_in_response(body, app_name)
            if tok:
                LAST_DEBUG["token_source"] = f"{note} ({path})"
                return tok
    return None


def get_credentials():
    """Return google.oauth2.credentials.Credentials with refresh disabled.

    Composio manages the token lifecycle server-side and doesn't hand out
    a refresh_token/client_id/client_secret. If we return a stock
    Credentials, google-auth tries to refresh on every request and blows
    up with RefreshError. We subclass to no-op refresh and always report
    valid, so google-auth just sends the token as-is.
    """
    LAST_DEBUG.clear()
    if not _api_key():
        LAST_DEBUG["error"] = "COMPOSIO_API_KEY not set"
        return None
    try:
        token = _fetch_access_token("googlesheets") or _fetch_access_token("googledrive")
        if not token:
            LAST_DEBUG["error"] = "no access token found in any connected-accounts response"
            return None
        from google.oauth2.credentials import Credentials

        class _NoRefreshCreds(Credentials):
            def refresh(self, request):
                return  # Composio owns the token; never refresh.
            @property
            def expired(self):
                return False
            @property
            def valid(self):
                return True

        return _NoRefreshCreds(token=token)
    except Exception as exc:
        LAST_DEBUG["error"] = f"exception: {exc}"
        return None
