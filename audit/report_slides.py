"""Build a technical-audit deck via python-pptx and upload as Google Slides.

Auth: reuses GOOGLE_SERVICE_ACCOUNT_JSON. The .pptx is generated locally
with python-pptx, then uploaded to Drive with mimeType conversion to
application/vnd.google-apps.presentation — Drive auto-converts it into a
native Google Slides deck. Drive-only scope (drive.file) is enough, so
the Google Slides API does NOT need to be enabled in the GCP project.

Deck structure (kept intentionally lean — one slide per Critical + High
finding):
  1. Cover — client name + audit date (black background)
  2. Executive summary — counts by priority
  3..N. One slide per finding — banner header with [Priority] Category,
        two-column layout: Observation left / Impact right
  N+1. Next-steps slide

Style matches the Vantage / Garofano decks:
- Proxima Nova
- Bold black banner header
- No em dashes, no extra background fills
"""
import datetime
import io
import json
import os

_SHARE_EMAIL = os.environ.get("AUDIT_SHARE_EMAIL", "shavi.goyal@gushwork.ai")


def _credentials():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        from google.oauth2.service_account import Credentials
        info = json.loads(raw)
        scopes = ["https://www.googleapis.com/auth/drive.file"]
        return Credentials.from_service_account_info(info, scopes=scopes)
    except Exception as exc:
        print(f"[slides] credential error: {exc}")
        return None


def _drive(creds):
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── Colors ────────────────────────────────────────────────────────────────
def _rgb(hexstr):
    from pptx.dml.color import RGBColor
    return RGBColor.from_string(hexstr)


_BLACK  = "000000"
_WHITE  = "FFFFFF"
_TEXT   = "1A1A1A"
_MUTED  = "6B7280"
_CRIT   = "F26F6F"   # red
_HIGH   = "F28C46"   # orange
_MED    = "F2C746"   # amber
_LOW    = "69BF6A"   # green

_PRIORITY_COLOR = {"Critical": _CRIT, "High": _HIGH, "Medium": _MED, "Low": _LOW}


def _set_bg(slide, hexstr):
    """Fill a slide with a solid colour."""
    from pptx.dml.color import RGBColor
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(hexstr)


def _text(slide, x, y, w, h, text, *, size=14, bold=False, color=_TEXT,
          font="Proxima Nova", align="left"):
    """Add a text box with a single paragraph."""
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.util import Emu
    tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(60000)
    tf.margin_top = tf.margin_bottom = Emu(30000)
    tf.vertical_anchor = MSO_ANCHOR.TOP

    lines = str(text).splitlines() or [""]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
                       "right": PP_ALIGN.RIGHT}[align]
        run = p.add_run()
        run.text = line
        f = run.font
        f.name = font
        f.size = _pt(size)
        f.bold = bold
        f.color.rgb = _rgb(color)
    return tb


def _pt(n):
    from pptx.util import Pt
    return Pt(n)


def _emu_in(v):
    from pptx.util import Inches
    return Inches(v)


def _banner(slide, prs, priority, category):
    """Full-width black banner header."""
    from pptx.util import Emu
    label = f"[{priority}] {category or 'Finding'}"
    bar = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Emu(700000))
    bar.line.fill.background()
    bar.fill.solid()
    bar.fill.fore_color.rgb = _rgb(_BLACK)
    tf = bar.text_frame
    tf.margin_left = Emu(360000)
    tf.margin_top = Emu(180000)
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = label
    run.font.name = "Proxima Nova"
    run.font.size = _pt(18)
    run.font.bold = True
    run.font.color.rgb = _rgb(_WHITE)


def _cover_slide(prs, client_display):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _set_bg(slide, _BLACK)
    _text(slide, _emu_in(0.6), _emu_in(2.0), _emu_in(8.8), _emu_in(1.0),
          client_display, size=36, bold=True, color=_WHITE)
    _text(slide, _emu_in(0.6), _emu_in(3.1), _emu_in(8.8), _emu_in(0.5),
          "Technical SEO Audit", size=20, color=_WHITE)
    _text(slide, _emu_in(0.6), _emu_in(3.7), _emu_in(8.8), _emu_in(0.4),
          datetime.date.today().strftime("%d %B %Y"), size=14, color=_WHITE)


def _exec_slide(prs, obs_rows, crits, highs, meds, lows):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _banner(slide, prs, "", "Executive Summary")
    lines = (
        f"Total observations: {len(obs_rows)}",
        "",
        f"Critical: {len(crits)}",
        f"High:     {len(highs)}",
        f"Medium:   {len(meds)}",
        f"Low:      {len(lows)}",
        "",
        "The following slides walk through each Critical and High finding, with the observation on the left and the business impact on the right. Medium and Low priority findings are captured in the audit sheet.",
    )
    _text(slide, _emu_in(0.6), _emu_in(1.1), _emu_in(9.0), _emu_in(4.5),
          "\n".join(lines), size=13, color=_TEXT)


def _finding_slide(prs, row):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _banner(slide, prs, row.get("priority", ""), row.get("category", ""))

    # Left — Observation
    _text(slide, _emu_in(0.4), _emu_in(0.95), _emu_in(4.5), _emu_in(0.35),
          "Observation", size=12, bold=True, color=_TEXT)
    _text(slide, _emu_in(0.4), _emu_in(1.35), _emu_in(4.5), _emu_in(4.0),
          row.get("observation", "").strip() or " ", size=11, color=_TEXT)

    # Right — Impact
    _text(slide, _emu_in(5.1), _emu_in(0.95), _emu_in(4.5), _emu_in(0.35),
          "Impact", size=12, bold=True, color=_TEXT)
    _text(slide, _emu_in(5.1), _emu_in(1.35), _emu_in(4.5), _emu_in(4.0),
          row.get("impact", "").strip() or " ", size=11, color=_TEXT)


def _next_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, _BLACK)
    _text(slide, _emu_in(0.6), _emu_in(2.2), _emu_in(8.8), _emu_in(1.0),
          "Next Steps", size=32, bold=True, color=_WHITE)
    _text(slide, _emu_in(0.6), _emu_in(3.2), _emu_in(8.8), _emu_in(1.0),
          "Let's walk through the fixes and prioritise the roadmap.",
          size=16, color=_WHITE)


def _build_pptx(deck_title, obs_rows, client_display):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    # 16:9 (10in × 5.625in)
    prs.slide_width  = Inches(10)
    prs.slide_height = Inches(5.625)

    crits = [r for r in obs_rows if r.get("priority") == "Critical"]
    highs = [r for r in obs_rows if r.get("priority") == "High"]
    meds  = [r for r in obs_rows if r.get("priority") == "Medium"]
    lows  = [r for r in obs_rows if r.get("priority") == "Low"]

    _cover_slide(prs, client_display or deck_title)
    _exec_slide(prs, obs_rows, crits, highs, meds, lows)
    for row in crits + highs:
        _finding_slide(prs, row)
    _next_slide(prs)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf


def build(deck_title, obs_rows, client_display=""):
    """Create a Google Slides deck. Returns URL or None.

    Only Critical + High findings become their own slide; Medium/Low are
    summarised in the executive slide.
    """
    creds = _credentials()
    if creds is None:
        return None

    try:
        pptx_buf = _build_pptx(deck_title, obs_rows, client_display)

        from googleapiclient.http import MediaIoBaseUpload
        drive_svc = _drive(creds)

        media = MediaIoBaseUpload(
            pptx_buf,
            mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            resumable=False,
        )
        # Ask Drive to convert into a native Google Slides deck
        file_meta = {
            "name": deck_title,
            "mimeType": "application/vnd.google-apps.presentation",
        }
        f = drive_svc.files().create(
            body=file_meta,
            media_body=media,
            fields="id",
        ).execute()
        deck_id = f["id"]

        if _SHARE_EMAIL:
            drive_svc.permissions().create(
                fileId=deck_id,
                sendNotificationEmail=False,
                body={"type": "user", "role": "writer",
                      "emailAddress": _SHARE_EMAIL},
            ).execute()

        return f"https://docs.google.com/presentation/d/{deck_id}"

    except Exception as exc:
        print(f"[slides] error: {exc}")
        return None
