"""Build a technical-audit Google Slides deck from audit rows.

Auth: reuses GOOGLE_SERVICE_ACCOUNT_JSON (same service account as
report_sheets). Deck is shared with AUDIT_SHARE_EMAIL as writer and the
URL is returned. If credentials are missing, returns None.

Deck structure (kept intentionally lean — one findings slide per
Critical + High row):
  1. Cover — client name + audit date
  2. Executive summary — counts by priority
  3..N. One slide per Critical + High finding — Observation left,
        Impact right, coloured category chip in a black banner header
  N+1. Next steps / thank-you slide

Style matches the Vantage / Garofano decks built by hand:
- Proxima Nova
- Bold black banner header
- No em dashes, no extra background fills
- Slide is 720 x 405 pt (16:9), positions in EMU
"""
import datetime
import json
import os

_SHARE_EMAIL = os.environ.get("AUDIT_SHARE_EMAIL", "shavi.goyal@gushwork.ai")

# Slide size (Slides API default 10in × 5.63in @ 914400 EMU/in = 9144000 × 5143500)
_W = 9144000
_H = 5143500

_PRIORITY_CHIP = {
    "Critical": {"red": 0.949, "green": 0.278, "blue": 0.278},
    "High":     {"red": 0.949, "green": 0.549, "blue": 0.278},
    "Medium":   {"red": 0.949, "green": 0.780, "blue": 0.278},
    "Low":      {"red": 0.412, "green": 0.749, "blue": 0.416},
}
_BLACK = {"red": 0.0, "green": 0.0, "blue": 0.0}
_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
_GREY  = {"red": 0.95, "green": 0.95, "blue": 0.95}


def _credentials():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        from google.oauth2.service_account import Credentials
        info = json.loads(raw)
        scopes = [
            "https://www.googleapis.com/auth/presentations",
            "https://www.googleapis.com/auth/drive.file",
        ]
        return Credentials.from_service_account_info(info, scopes=scopes)
    except Exception as exc:
        print(f"[slides] credential error: {exc}")
        return None


def _services(creds):
    from googleapiclient.discovery import build
    return (
        build("slides", "v1", credentials=creds, cache_discovery=False),
        build("drive",  "v3", credentials=creds, cache_discovery=False),
    )


def _emu(inches):
    return int(inches * 914400)


def _shape(oid, page_id, x, y, w, h):
    return {
        "createShape": {
            "objectId": oid,
            "shapeType": "TEXT_BOX",
            "elementProperties": {
                "pageObjectId": page_id,
                "size": {"width": {"magnitude": w, "unit": "EMU"},
                         "height": {"magnitude": h, "unit": "EMU"}},
                "transform": {"scaleX": 1, "scaleY": 1,
                              "translateX": x, "translateY": y, "unit": "EMU"},
            },
        }
    }


def _fill(oid, color):
    return {"updateShapeProperties": {
        "objectId": oid,
        "shapeProperties": {"shapeBackgroundFill": {
            "solidFill": {"color": {"rgbColor": color}}}},
        "fields": "shapeBackgroundFill.solidFill.color"}}


def _insert(oid, text):
    return {"insertText": {"objectId": oid, "insertionIndex": 0, "text": text}}


def _style(oid, start, end, size, bold=False, color=None, family="Proxima Nova"):
    tf = {"fontFamily": family, "fontSize": {"magnitude": size, "unit": "PT"}, "bold": bold}
    fields = "fontFamily,fontSize,bold"
    if color is not None:
        tf["foregroundColor"] = {"opaqueColor": {"rgbColor": color}}
        fields += ",foregroundColor"
    return {"updateTextStyle": {
        "objectId": oid,
        "textRange": {"type": "FIXED_RANGE", "startIndex": start, "endIndex": end},
        "style": tf,
        "fields": fields}}


def _create_page(idx):
    pid = f"slide_{idx:03d}"
    return {"createSlide": {
        "objectId": pid,
        "insertionIndex": idx,
        "slideLayoutReference": {"predefinedLayout": "BLANK"}}}, pid


def _findings_slide(reqs, idx, row, total_critical, total_high):
    """Build a single findings slide. Returns the page id."""
    page_req, pid = _create_page(idx)
    reqs.append(page_req)

    # Banner header (full width, black)
    banner_id = f"banner_{idx}"
    reqs.append(_shape(banner_id, pid, 0, 0, _W, _emu(0.7)))
    reqs.append(_fill(banner_id, _BLACK))
    banner_text = f"[{row.get('priority','')}] {row.get('category','') or 'Finding'}"
    reqs.append(_insert(banner_id, banner_text))
    reqs.append(_style(banner_id, 0, len(banner_text), 18, bold=True, color=_WHITE))

    # Left column — Observation
    left_head_id = f"lh_{idx}"
    reqs.append(_shape(left_head_id, pid, _emu(0.4), _emu(0.9), _emu(4.5), _emu(0.35)))
    reqs.append(_insert(left_head_id, "Observation"))
    reqs.append(_style(left_head_id, 0, len("Observation"), 12, bold=True, color=_BLACK))

    left_body_id = f"lb_{idx}"
    reqs.append(_shape(left_body_id, pid, _emu(0.4), _emu(1.3), _emu(4.5), _emu(4.0)))
    obs_text = row.get("observation", "").strip() or " "
    reqs.append(_insert(left_body_id, obs_text))
    reqs.append(_style(left_body_id, 0, len(obs_text), 11, color=_BLACK))

    # Right column — Impact
    right_head_id = f"rh_{idx}"
    reqs.append(_shape(right_head_id, pid, _emu(5.1), _emu(0.9), _emu(4.5), _emu(0.35)))
    reqs.append(_insert(right_head_id, "Impact"))
    reqs.append(_style(right_head_id, 0, len("Impact"), 12, bold=True, color=_BLACK))

    right_body_id = f"rb_{idx}"
    reqs.append(_shape(right_body_id, pid, _emu(5.1), _emu(1.3), _emu(4.5), _emu(4.0)))
    impact_text = row.get("impact", "").strip() or " "
    reqs.append(_insert(right_body_id, impact_text))
    reqs.append(_style(right_body_id, 0, len(impact_text), 11, color=_BLACK))

    return pid


def build(deck_title, obs_rows, client_display=""):
    """Create a slides deck from obs_rows. Returns URL or None.

    Only Critical + High findings become their own slide; Medium/Low are
    summarised in the executive slide.
    """
    creds = _credentials()
    if creds is None:
        return None

    try:
        slides_svc, drive_svc = _services(creds)

        # Create presentation
        pres = slides_svc.presentations().create(body={"title": deck_title}).execute()
        pid_deck = pres["presentationId"]

        # Delete the default first slide (we control layout)
        default_slide_id = pres["slides"][0]["objectId"]

        # Split findings
        crits = [r for r in obs_rows if r.get("priority") == "Critical"]
        highs = [r for r in obs_rows if r.get("priority") == "High"]
        meds  = [r for r in obs_rows if r.get("priority") == "Medium"]
        lows  = [r for r in obs_rows if r.get("priority") == "Low"]
        findings = crits + highs  # slide-worthy

        reqs = []

        # ── 1. Cover slide ────────────────────────────────────────────────
        cover_req, cover_pid = _create_page(0)
        reqs.append(cover_req)

        cover_bg = f"cbg_0"
        reqs.append(_shape(cover_bg, cover_pid, 0, 0, _W, _H))
        reqs.append(_fill(cover_bg, _BLACK))

        title_id = "cover_title"
        reqs.append(_shape(title_id, cover_pid, _emu(0.6), _emu(2.0), _emu(8.8), _emu(1.0)))
        title_text = client_display or deck_title.split(" — ")[0]
        reqs.append(_insert(title_id, title_text))
        reqs.append(_style(title_id, 0, len(title_text), 36, bold=True, color=_WHITE))

        sub_id = "cover_sub"
        reqs.append(_shape(sub_id, cover_pid, _emu(0.6), _emu(3.1), _emu(8.8), _emu(0.5)))
        sub_text = "Technical SEO Audit"
        reqs.append(_insert(sub_id, sub_text))
        reqs.append(_style(sub_id, 0, len(sub_text), 20, color=_WHITE))

        date_id = "cover_date"
        reqs.append(_shape(date_id, cover_pid, _emu(0.6), _emu(3.7), _emu(8.8), _emu(0.4)))
        date_text = datetime.date.today().strftime("%d %B %Y")
        reqs.append(_insert(date_id, date_text))
        reqs.append(_style(date_id, 0, len(date_text), 14, color=_WHITE))

        # ── 2. Executive summary slide ────────────────────────────────────
        exec_req, exec_pid = _create_page(1)
        reqs.append(exec_req)

        exec_banner = "exec_banner"
        reqs.append(_shape(exec_banner, exec_pid, 0, 0, _W, _emu(0.7)))
        reqs.append(_fill(exec_banner, _BLACK))
        reqs.append(_insert(exec_banner, "Executive Summary"))
        reqs.append(_style(exec_banner, 0, len("Executive Summary"), 20, bold=True, color=_WHITE))

        exec_body_id = "exec_body"
        reqs.append(_shape(exec_body_id, exec_pid, _emu(0.6), _emu(1.2), _emu(9.0), _emu(4.0)))
        exec_text = (
            f"Total observations: {len(obs_rows)}\n"
            f"\n"
            f"Critical: {len(crits)}\n"
            f"High:     {len(highs)}\n"
            f"Medium:   {len(meds)}\n"
            f"Low:      {len(lows)}\n"
            f"\n"
            f"The following slides walk through each Critical and High finding, "
            f"with the observation on the left and the business impact on the right. "
            f"Medium and Low priority findings are captured in the audit sheet."
        )
        reqs.append(_insert(exec_body_id, exec_text))
        reqs.append(_style(exec_body_id, 0, len(exec_text), 13, color=_BLACK))

        # ── 3..N. One slide per finding (Critical + High) ─────────────────
        for i, row in enumerate(findings, start=2):
            _findings_slide(reqs, i, row, len(crits), len(highs))

        # ── Last: Thank-you / next-steps slide ────────────────────────────
        last_idx = 2 + len(findings)
        ty_req, ty_pid = _create_page(last_idx)
        reqs.append(ty_req)

        ty_bg = "ty_bg"
        reqs.append(_shape(ty_bg, ty_pid, 0, 0, _W, _H))
        reqs.append(_fill(ty_bg, _BLACK))

        ty_title = "ty_title"
        reqs.append(_shape(ty_title, ty_pid, _emu(0.6), _emu(2.2), _emu(8.8), _emu(1.0)))
        reqs.append(_insert(ty_title, "Next Steps"))
        reqs.append(_style(ty_title, 0, len("Next Steps"), 32, bold=True, color=_WHITE))

        ty_sub = "ty_sub"
        reqs.append(_shape(ty_sub, ty_pid, _emu(0.6), _emu(3.2), _emu(8.8), _emu(1.0)))
        ty_text = "Let's walk through the fixes and prioritise the roadmap."
        reqs.append(_insert(ty_sub, ty_text))
        reqs.append(_style(ty_sub, 0, len(ty_text), 16, color=_WHITE))

        # ── Delete the default blank slide the API created ────────────────
        reqs.append({"deleteObject": {"objectId": default_slide_id}})

        # Apply everything in one batch (Slides API accepts many requests)
        # Chunk into batches of 250 requests to stay well under limits.
        BATCH = 200
        for start in range(0, len(reqs), BATCH):
            slides_svc.presentations().batchUpdate(
                presentationId=pid_deck,
                body={"requests": reqs[start:start + BATCH]}
            ).execute()

        # Share
        if _SHARE_EMAIL:
            drive_svc.permissions().create(
                fileId=pid_deck,
                sendNotificationEmail=False,
                body={"type": "user", "role": "writer", "emailAddress": _SHARE_EMAIL},
            ).execute()

        return f"https://docs.google.com/presentation/d/{pid_deck}"

    except Exception as exc:
        print(f"[slides] error: {exc}")
        return None
