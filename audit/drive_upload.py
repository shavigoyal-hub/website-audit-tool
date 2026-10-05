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
    """Return an inline data: URI for the image.

    We USED to upload to Drive and serve through a /img/<id> proxy, but
    Composio's proxy wraps request bodies in JSON, so the uploaded Drive
    file ended up being the multipart wrapper, not the image. Rather than
    fight that, we skip Drive entirely: shrink the image to ~15KB, encode
    as base64, store the data URI directly in the sheet cell. The deck
    renders data: URIs natively — no network, no auth, no breakage.

    Cell limit is 50k chars; a 500px-wide JPEG @ Q70 lands comfortably
    under that.
    """
    import base64 as _b64
    import io as _io
    try:
        from PIL import Image as _Image
        img = _Image.open(_io.BytesIO(content_bytes))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        # Shrink to fit cell budget. Try progressively smaller widths /
        # qualities until the base64 string is under ~45k chars. If even
        # the smallest preset doesn't fit (tall mobile screenshots do
        # this), harder-downscale rather than returning an oversize URI
        # that would blow Sheets' 50 000-char cell limit.
        presets = [(640, 78), (500, 72), (420, 68), (360, 60),
                   (280, 55), (220, 50), (180, 45)]
        b64 = ""
        for max_w, quality in presets:
            buf = _io.BytesIO()
            if img.width > max_w:
                work = img.copy()
                work.thumbnail((max_w, max_w * 4))
            else:
                work = img
            work.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            b64 = _b64.b64encode(data).decode("ascii")
            if len(b64) < 45_000:
                return f"data:image/jpeg;base64,{b64}"
        # Last preset was still too big. Return None so the caller doesn't
        # try to write a 50k+ URI into a Sheets cell (which would fail
        # BATCH_UPDATE and lose the attach entirely).
        print(f"[drive_upload] image too large to inline ({len(b64)} chars "
              "after smallest preset); skipping attach")
        return None
    except Exception as exc:
        print(f"[drive_upload] inline encode failed ({exc}); "
              "falling back to Drive upload path")

    # Legacy Drive upload path (kept as a backup even though it's known
    # unreliable right now):
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
    # Return a marker URL that the app proxies through /img/<file_id>.
    # This is the ONLY endpoint we control end-to-end — no more relying on
    # Drive's shifting inline-image URL rules. The app fetches the file
    # authenticated (via Composio) and streams the bytes back.
    return f"GDRIVE_IMG:{file_id}"


def fetch_bytes(file_id):
    """Fetch a Drive file's binary content via Composio.

    Returns (bytes, mime_type) or (None, None) on failure. Used by the
    /img/<file_id> proxy so deck screenshots always render regardless of
    Drive's public-sharing propagation delay.
    """
    import base64
    try:
        from audit.composio_exec import proxy as _proxy
        # Get metadata first for the mime type
        meta = _proxy(
            endpoint=f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=mimeType",
            method="GET",
            toolkit="googledrive",
        )
        mime = (meta or {}).get("mimeType") if isinstance(meta, dict) else None
        # alt=media returns the raw bytes; Composio proxy will pass them back
        body = _proxy(
            endpoint=f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
            method="GET",
            toolkit="googledrive",
        )
        # Composio's proxy sometimes returns the body as base64 or as a
        # bytes-like blob depending on content-type handling.
        if isinstance(body, dict):
            raw = body.get("_raw_body") or body.get("data") or body.get("content")
            if isinstance(raw, str):
                try:
                    return base64.b64decode(raw), mime or "image/png"
                except Exception:
                    return raw.encode(), mime or "image/png"
        if isinstance(body, (bytes, bytearray)):
            return bytes(body), mime or "image/png"
        if isinstance(body, str):
            try:
                return base64.b64decode(body), mime or "image/png"
            except Exception:
                return body.encode(), mime or "image/png"
    except Exception as exc:
        print(f"[drive] fetch_bytes failed for {file_id}: {exc}")
    return None, None
