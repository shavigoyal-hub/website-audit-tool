"""Upload chatbot-attached screenshots to Drive and return public URLs.

Screenshots land in a shared 'Gushwork Audit Screenshots' folder (auto-created
on first use). Each upload:
  1. Base64-encodes the image.
  2. Uploads via Composio's GOOGLEDRIVE_UPLOAD_FILE (falls back to raw REST
     via proxy when the named action doesn't accept binary content).
  3. Sets sharing = anyone-with-link can view.
  4. Returns the direct-view URL that Sheets IMAGE() and <img src=...> both
     understand: https://lh3.googleusercontent.com/d/<id>=w800

Fails soft: returns None on any error so a chatbot append still succeeds.
"""
import base64
import os
import uuid

from audit.composio_exec import execute as _cx


_FOLDER_NAME = "Gushwork Audit Screenshots"
_FOLDER_ID_CACHE = None


def _find_or_create_folder():
    global _FOLDER_ID_CACHE
    if _FOLDER_ID_CACHE:
        return _FOLDER_ID_CACHE
    env_id = os.environ.get("SCREENSHOT_FOLDER_ID", "").strip()
    if env_id:
        _FOLDER_ID_CACHE = env_id
        return env_id
    try:
        r = _cx("GOOGLEDRIVE_FIND_FILE", {
            "query": f"name = '{_FOLDER_NAME}' and trashed = false and "
                     f"mimeType = 'application/vnd.google-apps.folder'",
        })
        files = (r.get("files") if isinstance(r, dict) else None) or []
        if files:
            fid = files[0].get("id") or files[0].get("fileId")
            if fid:
                _FOLDER_ID_CACHE = fid
                return fid
    except Exception as exc:
        print(f"[drive] find folder failed: {exc}")
    # Create it
    try:
        created = _cx("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {
            "file_name": _FOLDER_NAME,
            "text_content": " ",
            "mime_type": "application/vnd.google-apps.folder",
        }) or {}
        fid = created.get("id") or created.get("fileId")
        if fid:
            _FOLDER_ID_CACHE = fid
            _make_public(fid)
            return fid
    except Exception as exc:
        print(f"[drive] create folder failed: {exc}")
    return None


def _make_public(file_id):
    try:
        _cx("GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE", {
            "file_id": file_id,
            "role": "reader",
            "type": "anyone",
            "sendNotificationEmail": False,
        })
        return True
    except Exception as exc:
        print(f"[drive] make public failed for {file_id}: {exc}")
        return False


def upload_image(filename, content_bytes, mime_type="image/png"):
    """Upload one image, return its public direct URL (or None).

    Uses Composio's GOOGLEDRIVE_UPLOAD_FILE if it exists on this account,
    else falls back to a raw multipart POST via the proxy.
    """
    folder = _find_or_create_folder()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    safe_name = f"{uuid.uuid4().hex[:8]}_{filename[:60]}"
    b64 = base64.b64encode(content_bytes).decode("ascii")
    file_id = None
    # Path A: named action (if the tool supports it on this account)
    try:
        r = _cx("GOOGLEDRIVE_UPLOAD_FILE", {
            "file_name": safe_name,
            "file_content_base64": b64,
            "mime_type": mime_type,
            "parent_folder_id": folder,
        }) or {}
        file_id = r.get("id") or r.get("fileId")
    except Exception as exc:
        print(f"[drive] UPLOAD_FILE named action failed: {exc}")

    # Path B: raw REST multipart upload via proxy
    if not file_id:
        try:
            from audit.composio_exec import proxy as _proxy
            boundary = "----GushworkFormBoundary" + uuid.uuid4().hex[:12]
            metadata = ('{"name":"%s","mimeType":"%s","parents":["%s"]}'
                        % (safe_name.replace('"', "'"), mime_type, folder))
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{metadata}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: {mime_type}\r\n"
                f"Content-Transfer-Encoding: base64\r\n\r\n"
                f"{b64}\r\n"
                f"--{boundary}--\r\n"
            )
            r = _proxy(
                endpoint=("https://www.googleapis.com/upload/drive/v3/files"
                          "?uploadType=multipart"),
                method="POST",
                body={
                    "_raw_body": body,
                    "_headers": {"Content-Type": f"multipart/related; boundary={boundary}"},
                },
                toolkit="googledrive",
            )
            if isinstance(r, dict):
                file_id = r.get("id") or r.get("fileId")
        except Exception as exc:
            print(f"[drive] raw upload failed: {exc}")

    if not file_id:
        return None
    # Sharing: primary path via Composio action, fallback to raw REST proxy.
    ok = _make_public(file_id)
    if not ok:
        try:
            from audit.composio_exec import proxy as _proxy
            _proxy(
                endpoint=f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
                method="POST",
                body={"role": "reader", "type": "anyone"},
                toolkit="googledrive",
            )
        except Exception as exc:
            print(f"[drive] proxy permissions fallback failed: {exc}")
    # drive.google.com/thumbnail is the endpoint Drive itself uses for
    # inline previews. It respects file sharing, works from any origin,
    # and reliably serves an image (unlike ?export=view which sometimes
    # 302s to a Drive viewer page for logged-out clients).
    return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1200"
