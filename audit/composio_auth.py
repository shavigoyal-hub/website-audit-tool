"""Composio-based Google auth for report_sheets / report_slides.

When COMPOSIO_API_KEY is set, exchange it for OAuth tokens on connected
Google accounts (Sheets + Drive) and return google.oauth2.Credentials that
work with the existing google-api-python-client code in report_sheets.py
and report_slides.py.

If COMPOSIO_API_KEY is missing, or Composio's API returns anything we don't
understand, we return None and the caller falls back to
GOOGLE_SERVICE_ACCOUNT_JSON.

Env vars:
    COMPOSIO_API_KEY     — required to enable Composio auth
    COMPOSIO_ENTITY_ID   — Composio entity/user id (defaults to
                            AUDIT_SHARE_EMAIL or shavi.goyal@gushwork.ai)

Composio connections must be configured with the following scopes:
    - GOOGLESHEETS: https://www.googleapis.com/auth/spreadsheets
    - GOOGLEDRIVE:  https://www.googleapis.com/auth/drive.file
"""
import os
import time

import requests

_BASE = "https://backend.composio.dev"
_TIMEOUT = 15


def _api_key():
    return os.environ.get("COMPOSIO_API_KEY", "").strip() or None


def _entity_id():
    return (
        os.environ.get("COMPOSIO_ENTITY_ID")
        or os.environ.get("AUDIT_SHARE_EMAIL")
        or "shavi.goyal@gushwork.ai"
    )


def _headers():
    return {"X-API-Key": _api_key(), "Content-Type": "application/json"}


def _fetch_access_token(app_name):
    """Return an OAuth access token for a Composio-connected Google app.

    app_name examples: 'googlesheets', 'googledrive', 'googleslides'.
    Composio auto-refreshes tokens server-side so the returned token
    should be usable immediately.
    """
    key = _api_key()
    if not key:
        return None

    entity = _entity_id()

    # Try modern v3 endpoint first, fall back to v1.
    for path in (
        f"/api/v3/connected_accounts?entityId={entity}&appName={app_name}",
        f"/api/v1/connectedAccounts?showActiveOnly=true&user_uuid={entity}&appNames={app_name}",
    ):
        try:
            resp = requests.get(_BASE + path, headers=_headers(), timeout=_TIMEOUT)
            if resp.status_code != 200:
                continue
            data = resp.json()
            items = data.get("items") or data.get("connectedAccounts") or []
            if not items:
                continue
            first = items[0]
            params = (
                first.get("connectionParams")
                or first.get("credentials")
                or first.get("params")
                or {}
            )
            token = (
                params.get("access_token")
                or params.get("accessToken")
                or first.get("access_token")
            )
            if token:
                return token
        except Exception as exc:
            print(f"[composio] fetch_access_token error on {path}: {exc}")
    return None


def get_credentials():
    """Return google.oauth2.credentials.Credentials or None.

    The returned credentials work with build('sheets','v4',credentials=…),
    build('drive','v3',…), and build('slides','v1',…).
    """
    if not _api_key():
        return None
    try:
        # We ask for a Drive token because report_slides needs Drive+conversion,
        # and google-api-python-client will happily use a Drive access token
        # against Sheets too if the underlying scope covers spreadsheets.
        # Composio usually shares one Google auth per entity — try sheets first,
        # fall back to drive.
        token = _fetch_access_token("googlesheets") or _fetch_access_token("googledrive")
        if not token:
            print("[composio] no access token returned (no connected Google account?)")
            return None
        from google.oauth2.credentials import Credentials
        return Credentials(token=token)
    except Exception as exc:
        print(f"[composio] credential error: {exc}")
        return None
