"""Composio-based Google auth for report_sheets / report_slides.

Uses the official `composio` Python SDK so token refresh + retrieval
follows Composio's supported path. LIST returns cached (often stale)
tokens that Google rejects with 401; the RETRIEVE call on a specific
connection returns the fresh token Composio has cached internally.
"""
import os

LAST_DEBUG = {}


def _api_key():
    return os.environ.get("COMPOSIO_API_KEY", "").strip() or None


def _entity_id():
    return (
        os.environ.get("COMPOSIO_ENTITY_ID")
        or os.environ.get("entity_id")
        or os.environ.get("AUDIT_SHARE_EMAIL")
        or "shavi.goyal@gushwork.ai"
    )


def _walk_for_token(node, depth=0):
    """Recursively walk any nested dict/pydantic model looking for a plausible
    OAuth access token field. Returns (token, path_str) or (None, None).
    """
    if depth > 6 or node is None:
        return None, None
    # pydantic model → dict
    if hasattr(node, "model_dump"):
        try:
            node = node.model_dump()
        except Exception:
            pass
    if isinstance(node, dict):
        for k in ("access_token", "accessToken", "oauth_token", "token"):
            v = node.get(k)
            if isinstance(v, str) and len(v) > 20:
                return v, k
        for k, v in node.items():
            tok, p = _walk_for_token(v, depth + 1)
            if tok:
                return tok, f"{k}.{p}"
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            tok, p = _walk_for_token(v, depth + 1)
            if tok:
                return tok, f"[{i}].{p}"
    return None, None


def _fetch_token_via_sdk(app_slug):
    """Use the Composio SDK to list connections + retrieve fresh token."""
    try:
        from composio import Composio
    except Exception as exc:
        LAST_DEBUG["sdk_import_error"] = str(exc)[:200]
        return None

    key = _api_key()
    if not key:
        LAST_DEBUG["error"] = "COMPOSIO_API_KEY not set"
        return None
    entity = _entity_id()
    LAST_DEBUG["target_app"] = app_slug
    LAST_DEBUG["entity_id"] = entity

    c = Composio(api_key=key)

    # Step 1 — list connections for this toolkit
    user_id_variants = [entity, "default"] if entity != "default" else ["default"]
    conn_id = None
    for uid in user_id_variants:
        try:
            resp = c.connected_accounts.list(
                toolkit_slugs=[app_slug], user_ids=[uid],
            )
            items = getattr(resp, "items", None) or []
            LAST_DEBUG.setdefault("sdk_list", []).append(
                {"user_id": uid, "count": len(items),
                 "ids": [getattr(x, "id", None) for x in items[:3]]}
            )
            for it in items:
                slug = getattr(getattr(it, "toolkit", None), "slug", "") or ""
                if slug.lower() == app_slug.lower():
                    conn_id = getattr(it, "id", None)
                    if conn_id:
                        break
            if conn_id:
                break
        except Exception as exc:
            LAST_DEBUG.setdefault("sdk_list_errors", []).append(
                {"user_id": uid, "error": str(exc)[:250]}
            )

    if not conn_id:
        # Also try listing without user filter
        try:
            resp = c.connected_accounts.list(toolkit_slugs=[app_slug])
            items = getattr(resp, "items", None) or []
            for it in items:
                slug = getattr(getattr(it, "toolkit", None), "slug", "") or ""
                if slug.lower() == app_slug.lower():
                    conn_id = getattr(it, "id", None)
                    if conn_id:
                        break
        except Exception as exc:
            LAST_DEBUG["sdk_list_all_error"] = str(exc)[:250]

    if not conn_id:
        LAST_DEBUG["error"] = f"no connection found for {app_slug}"
        return None
    LAST_DEBUG["connection_id"] = conn_id

    # Step 2 — retrieve fresh connection details (SDK auto-handles refresh)
    try:
        detail = c.connected_accounts.get(conn_id)
    except Exception as exc:
        LAST_DEBUG["sdk_get_error"] = str(exc)[:250]
        return None

    tok, path = _walk_for_token(detail)
    if tok:
        LAST_DEBUG["token_source"] = f"sdk.get({conn_id}) → {path}"
        return tok
    # dump top-level field names so we can see what came back
    try:
        LAST_DEBUG["detail_fields"] = list(detail.model_dump().keys())
    except Exception:
        pass
    LAST_DEBUG["error"] = "connection retrieved but no access_token found in any field"
    return None


def get_credentials():
    """Return google.oauth2.credentials.Credentials with refresh disabled.

    Composio manages token lifecycle server-side and doesn't hand out
    refresh_token/client_id/client_secret. Overriding refresh + expired
    so google-auth never tries to refresh (which would raise RefreshError).
    """
    LAST_DEBUG.clear()
    if not _api_key():
        LAST_DEBUG["error"] = "COMPOSIO_API_KEY not set"
        return None
    try:
        token = _fetch_token_via_sdk("googlesheets") or _fetch_token_via_sdk("googledrive")
        if not token:
            return None
        from google.oauth2.credentials import Credentials

        class _NoRefreshCreds(Credentials):
            def refresh(self, request):
                return
            @property
            def expired(self):
                return False
            @property
            def valid(self):
                return True

        return _NoRefreshCreds(token=token)
    except Exception as exc:
        import traceback as _tb
        LAST_DEBUG["error"] = f"exception: {_tb.format_exc()[:500]}"
        return None
