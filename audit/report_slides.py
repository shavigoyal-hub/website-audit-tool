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
    """Return Google credentials or None.

    Order:
      1. Composio-connected Google account (COMPOSIO_API_KEY env var).
      2. Service account (GOOGLE_SERVICE_ACCOUNT_JSON env var).
    """
    try:
        from audit.composio_auth import get_credentials as _composio_creds
        creds = _composio_creds()
        if creds is not None:
            return creds
    except Exception as exc:
        print(f"[slides] composio unavailable: {exc}")

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
    if priority:
        label = f"[{priority}] {category or 'Finding'}"
    else:
        label = category or "Finding"
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


def _cover_slide(prs, client_display, version=""):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _set_bg(slide, _BLACK)
    _text(slide, _emu_in(0.6), _emu_in(2.0), _emu_in(8.8), _emu_in(1.0),
          client_display, size=36, bold=True, color=_WHITE)
    _text(slide, _emu_in(0.6), _emu_in(3.1), _emu_in(8.8), _emu_in(0.5),
          "Technical SEO Audit", size=20, color=_WHITE)
    _text(slide, _emu_in(0.6), _emu_in(3.7), _emu_in(8.8), _emu_in(0.4),
          datetime.date.today().strftime("%d %B %Y"), size=14, color=_WHITE)
    if version:
        _text(slide, _emu_in(0.6), _emu_in(5.15), _emu_in(8.8), _emu_in(0.3),
              f"v{version}", size=9, color="9CA3AF")


def _intro_slide(prs, client_display, row):
    """Big-hook intro slide styled like PDF page 1."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _text(slide, _emu_in(0.6), _emu_in(0.5), _emu_in(8.8), _emu_in(0.4),
          f"Gushwork Website Audit · {client_display}", size=13, bold=True, color=_MUTED)
    _text(slide, _emu_in(0.6), _emu_in(1.2), _emu_in(8.8), _emu_in(1.2),
          row.get("hook_ctx") or "Increase your leads",
          size=34, bold=True, color=_TEXT)
    _text(slide, _emu_in(0.6), _emu_in(2.7), _emu_in(8.8), _emu_in(0.5),
          row.get("found") or "", size=15, color=_TEXT)
    _text(slide, _emu_in(0.6), _emu_in(3.7), _emu_in(8.8), _emu_in(0.7),
          row.get("costs") or "", size=15, color=_MUTED)


def _ending_slide(prs, client_display, row):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, _BLACK)
    _text(slide, _emu_in(0.6), _emu_in(0.5), _emu_in(8.8), _emu_in(0.4),
          f"Gushwork · {client_display}", size=13, bold=True, color="9CA3AF")
    _text(slide, _emu_in(0.6), _emu_in(1.5), _emu_in(8.8), _emu_in(1.5),
          row.get("hook_ctx") or "Every month you wait, you lose out on extra leads.",
          size=28, bold=True, color=_WHITE)
    _text(slide, _emu_in(0.6), _emu_in(3.5), _emu_in(8.8), _emu_in(0.8),
          row.get("costs") or "Approve the audit fixes.",
          size=20, bold=True, color=_WHITE)


def _lead_math_slide(prs, plan_tier, tier_row, current_spend, sell_price,
                     cpl_reduction_pct):
    """Show projected leads by month + CPL delta + margin math."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _banner(slide, prs, "", "Projected Impact")

    # Left column — leads projection
    _text(slide, _emu_in(0.4), _emu_in(0.95), _emu_in(4.6), _emu_in(0.35),
          f"Expected leads on the ${plan_tier} plan", size=12, bold=True, color=_TEXT)
    lines = (
        f"Month 3-4:   {tier_row['M3-4']} leads / month",
        f"Month 6-7:   {tier_row['M6-7']} leads / month",
        f"Month 9-10:  {tier_row['M9-10']} leads / month",
        "",
        f"Cost per lead expected to drop ~{cpl_reduction_pct}% vs current spend.",
    )
    _text(slide, _emu_in(0.4), _emu_in(1.35), _emu_in(4.6), _emu_in(3.8),
          "\n".join(lines), size=12, color=_TEXT)

    # Right column — pricing
    _text(slide, _emu_in(5.2), _emu_in(0.95), _emu_in(4.4), _emu_in(0.35),
          "Investment", size=12, bold=True, color=_TEXT)
    try:
        cur = float(current_spend) if current_spend else 0
    except (TypeError, ValueError):
        cur = 0
    try:
        sell = float(sell_price) if sell_price else 0
    except (TypeError, ValueError):
        sell = 0
    right = []
    if cur:
        right.append(f"Currently paying: ${cur:,.0f} / month")
    right.append(f"New retainer:     ${plan_tier:,.0f} / month")
    if sell:
        right.append(f"Website build:    ${sell:,.0f} (one-time)")
    if cur:
        try:
            new_cpl_factor = (100 - cpl_reduction_pct) / 100
            month_9 = tier_row['M9-10']
            projected_cpl = (plan_tier / month_9) * new_cpl_factor
            baseline_cpl  = cur / max(month_9, 1)
            right += [
                "",
                f"Projected CPL at M9-10: ${projected_cpl:,.0f}",
                f"vs current baseline:   ${baseline_cpl:,.0f}",
            ]
        except Exception:
            pass
    _text(slide, _emu_in(5.2), _emu_in(1.35), _emu_in(4.4), _emu_in(3.8),
          "\n".join(right), size=12, color=_TEXT)


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
    """Finding slide matching the reference PDF:
       - Header: 'Finding · <Category>' + priority chip
       - Big stat + hook context (top-right)
       - Left column: 'What we found' list (page → status)
       - Bottom: 'What it costs you' with optional supporting stats
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    category = row.get("category", "") or "Finding"
    priority = row.get("priority", "") or ""

    # Header row — 'Finding · Category' left, priority chip right
    _text(slide, _emu_in(0.4), _emu_in(0.35), _emu_in(6.0), _emu_in(0.45),
          f"Finding · {category}", size=14, bold=True, color=_TEXT)
    if priority:
        chip_color = _PRIORITY_COLOR.get(priority, _MUTED)
        _text(slide, _emu_in(8.0), _emu_in(0.35), _emu_in(1.6), _emu_in(0.45),
              priority, size=12, bold=True, color=chip_color, align="right")

    # Big stat block (top area)
    hook_stat = (row.get("hook_stat") or "").strip()
    hook_ctx  = (row.get("hook_ctx") or row.get("observation") or "").strip()
    if hook_stat:
        _text(slide, _emu_in(0.4), _emu_in(1.0), _emu_in(9.2), _emu_in(0.8),
              hook_stat, size=42, bold=True, color=_TEXT)
    if hook_ctx:
        _text(slide, _emu_in(0.4), _emu_in(1.9), _emu_in(9.2), _emu_in(0.6),
              hook_ctx, size=14, color=_MUTED)

    # 'What we found' — left column
    found = (row.get("found") or row.get("reference") or "").strip()
    _text(slide, _emu_in(0.4), _emu_in(2.7), _emu_in(4.6), _emu_in(0.3),
          "What we found", size=11, bold=True, color=_TEXT)
    _text(slide, _emu_in(0.4), _emu_in(3.0), _emu_in(4.6), _emu_in(2.2),
          found or "—", size=10, color=_TEXT)

    # 'What it costs you' — right column
    costs = (row.get("costs") or row.get("impact") or "").strip()
    support = (row.get("support") or "").strip()
    _text(slide, _emu_in(5.2), _emu_in(2.7), _emu_in(4.4), _emu_in(0.3),
          "What it costs you", size=11, bold=True, color=_TEXT)
    _text(slide, _emu_in(5.2), _emu_in(3.0), _emu_in(4.4), _emu_in(1.5),
          costs or "—", size=11, color=_TEXT)
    if support:
        _text(slide, _emu_in(5.2), _emu_in(4.5), _emu_in(4.4), _emu_in(0.7),
              support, size=10, bold=True, color=_MUTED)


def _next_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, _BLACK)
    _text(slide, _emu_in(0.6), _emu_in(2.2), _emu_in(8.8), _emu_in(1.0),
          "Next Steps", size=32, bold=True, color=_WHITE)
    _text(slide, _emu_in(0.6), _emu_in(3.2), _emu_in(8.8), _emu_in(1.0),
          "Let's walk through the fixes and prioritise the roadmap.",
          size=16, color=_WHITE)


def _build_pptx(deck_title, obs_rows, client_display, meta=None):
    from pptx import Presentation
    from pptx.util import Inches
    from audit.version import VERSION, PLAN_TIERS, CPL_REDUCTION_PCT, resolve_plan
    prs = Presentation()
    # 16:9 (10in × 5.625in)
    prs.slide_width  = Inches(10)
    prs.slide_height = Inches(5.625)

    meta = meta or {}
    version = meta.get("version") or VERSION

    # Sheet rows carry slide_type — respect it. Fallback (no type) treats
    # rows as findings and rebuilds cover + intro + ending on the fly.
    intro_rows   = [r for r in obs_rows if r.get("slide_type") == "intro"]
    ending_rows  = [r for r in obs_rows if r.get("slide_type") == "ending"]
    finding_rows = [r for r in obs_rows if r.get("slide_type") not in ("intro", "ending")]

    # Only slides CS approved (checkbox), if any approval columns exist
    approved_any = any("approved" in r for r in obs_rows)
    if approved_any:
        finding_rows = [r for r in finding_rows if r.get("approved")]
        intro_rows   = [r for r in intro_rows   if r.get("approved")] or intro_rows[:1]
        ending_rows  = [r for r in ending_rows  if r.get("approved")] or ending_rows[:1]

    # Cover
    _cover_slide(prs, client_display or deck_title, version=version)

    # Intro (CS-approved messaging)
    if intro_rows:
        _intro_slide(prs, client_display or deck_title, intro_rows[0])
    else:
        _exec_slide(prs, obs_rows,
                    [r for r in finding_rows if r.get("priority") == "Critical"],
                    [r for r in finding_rows if r.get("priority") == "High"],
                    [r for r in finding_rows if r.get("priority") == "Medium"],
                    [r for r in finding_rows if r.get("priority") == "Low"])

    # Findings in the order CS set via Slide #
    for row in finding_rows:
        _finding_slide(prs, row)

    # Plan / lead-math slide
    plan_tier = resolve_plan(meta.get("plan"))
    if plan_tier and plan_tier in PLAN_TIERS:
        _lead_math_slide(
            prs, plan_tier, PLAN_TIERS[plan_tier],
            meta.get("current_spend"), meta.get("sell_price"),
            CPL_REDUCTION_PCT,
        )

    # Ending
    if ending_rows:
        _ending_slide(prs, client_display or deck_title, ending_rows[0])
    else:
        _next_slide(prs)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf


def build(deck_title, obs_rows, client_display="", meta=None, pdf_out_path=None):
    """Create a Google Slides deck. Returns dict {slide_url, pdf_path} or None.

    If pdf_out_path is provided, also exports the deck to PDF via Drive
    files.export and writes the bytes to that path — served by app.py's
    /download endpoint.
    """
    creds = _credentials()
    if creds is None:
        return None

    try:
        pptx_buf = _build_pptx(deck_title, obs_rows, client_display, meta=meta)

        from googleapiclient.http import MediaIoBaseUpload
        drive_svc = _drive(creds)

        media = MediaIoBaseUpload(
            pptx_buf,
            mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            resumable=False,
        )
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

        slide_url = f"https://docs.google.com/presentation/d/{deck_id}"
        pdf_saved = None
        if pdf_out_path:
            try:
                pdf_bytes = drive_svc.files().export(
                    fileId=deck_id, mimeType="application/pdf"
                ).execute()
                with open(pdf_out_path, "wb") as fh:
                    fh.write(pdf_bytes)
                pdf_saved = pdf_out_path
            except Exception as exc:
                print(f"[slides] pdf export failed: {exc}")

        return {"slide_url": slide_url, "pdf_path": pdf_saved}

    except Exception as exc:
        print(f"[slides] error: {exc}")
        return None
