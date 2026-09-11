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


def _find_token_in_response(body, target_app_prefix):
    """Given any Composio JSON response, walk it looking for a matching account with a token."""
    if not isinstance(body, dict):
        return None
    for key in ("items", "connectedAccounts", "data", "connections", "accounts"):
        items = body.get(key)
        if isinstance(items, list):
            for item in items:
                # Filter by app name if possible
                app = (item.get("appName") or item.get("app_name")
                       or (item.get("app") or {}).get("name")
                       or (item.get("toolkit") or {}).get("slug") or "").lower()
                if target_app_prefix and target_app_prefix not in app and app != "":
                    continue
                tok = _extract_token(item)
                if tok:
                    return tok
    return None


def _fetch_access_token(app_name):
    """Try multiple endpoint variants to fetch an OAuth token for the app."""
    entity = _entity_id()
    LAST_DEBUG["target_app"] = app_name
    LAST_DEBUG["entity_id"] = entity

    attempts = [
        # v3 - modern
        ("GET", "/api/v3/connected_accounts",
         {"user_ids": entity, "toolkit_slugs": app_name}, "v3 toolkit_slugs+user_ids"),
        ("GET", "/api/v3/connected_accounts",
         {"user_ids": entity, "auth_config_ids": app_name}, "v3 auth_config_ids"),
        ("GET", "/api/v3/connected_accounts",
         {"userIds": entity, "appNames": app_name}, "v3 userIds+appNames"),
        ("GET", "/api/v3/connected_accounts",
         {"entityId": entity, "appName": app_name}, "v3 entityId+appName"),
        ("GET", "/api/v3/connected_accounts",
         {"entityId": entity}, "v3 entity only"),
        ("GET", "/api/v3/connected_accounts", None, "v3 no filter"),

        # v1 - legacy but stable
        ("GET", "/api/v1/connectedAccounts",
         {"user_uuid": entity, "appNames": app_name, "showActiveOnly": "true"},
         "v1 user_uuid+appNames"),
        ("GET", "/api/v1/connectedAccounts",
         {"appNames": app_name, "showActiveOnly": "true"}, "v1 appNames"),
        ("GET", "/api/v1/connectedAccounts",
         {"showActiveOnly": "true"}, "v1 active only"),
    ]

    for method, path, params, note in attempts:
        status, body = _try(method, path, params=params, note=note)
        if status == 200 and body:
            tok = _find_token_in_response(body, app_name.lower().replace("google", ""))
            if tok:
                LAST_DEBUG["token_source"] = f"{note} ({path})"
                return tok
    return None


def get_credentials():
    """Return google.oauth2.credentials.Credentials or None."""
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
        return Credentials(token=token)
    except Exception as exc:
        LAST_DEBUG["error"] = f"exception: {exc}"
        return None
