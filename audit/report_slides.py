"""Build a technical-audit deck via python-pptx and upload as Google Slides.

Auth: uses Composio's tools-execute proxy (POST /api/v3/tools/execute/{slug}).
Composio doesn't hand out raw OAuth tokens; we go through
GOOGLEDRIVE_CREATE_FILE_FROM_TEXT-style actions.

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


def _composio_available():
    return bool(os.environ.get("COMPOSIO_API_KEY"))


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
    """Create a Google Slides deck via Composio actions.

    Composio has no upload-binary Drive action, so we can't push a
    python-pptx blob and let Drive convert it. Instead we:
      1. Create a blank presentation via Drive CREATE_FILE_FROM_TEXT
         (mime = google-apps.presentation).
      2. Use GOOGLESLIDES_PRESENTATIONS_BATCH_UPDATE to add slides.

    Returns dict {slide_url, pdf_path} or None.
    """
    if not _composio_available():
        return None
    from audit.composio_exec import execute as _cx, proxy as _cx_proxy

    try:
        # 1) Create the blank presentation via Slides API (Drive's
        #    CREATE_FILE_FROM_TEXT ignores the presentation mime_type and
        #    creates a Google Doc, which then 404s on Slides batchUpdate).
        try:
            result = _cx_proxy(
                endpoint="https://slides.googleapis.com/v1/presentations",
                method="POST",
                body={"title": deck_title},
                toolkit="googleslides",
            )
        except Exception:
            # Fallback: try Drive as it used to be, in case proxy scope is missing
            result = _cx("GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", {
                "file_name": deck_title,
                "text_content": " ",
                "mime_type": "application/vnd.google-apps.presentation",
            })
        deck_id = None
        if isinstance(result, dict):
            deck_id = (result.get("presentationId") or result.get("id")
                       or result.get("fileId"))
        if not deck_id:
            raise RuntimeError(f"presentation create returned no id: {str(result)[:300]}")

        # 2) Build the batchUpdate requests from obs_rows
        requests = _build_slides_requests(obs_rows, client_display, meta)
        if requests:
            _cx("GOOGLESLIDES_PRESENTATIONS_BATCH_UPDATE", {
                "presentationId": deck_id,
                "requests": requests,
            })

        # 3) Share (non-fatal)
        try:
            _cx("GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE", {
                "file_id": deck_id, "role": "writer", "type": "domain",
                "domain": "gushwork.ai", "sendNotificationEmail": False,
            })
        except Exception as exc:
            print(f"[slides] share failed (non-fatal): {exc}")

        slide_url = f"https://docs.google.com/presentation/d/{deck_id}"

        # PDF export via Drive's files.export endpoint (via proxy).
        # Composio has no named action for binary export, so we go raw.
        pdf_saved = None
        if pdf_out_path:
            try:
                import requests as _rq
                from audit.composio_exec import (
                    _api_key as _get_key, _find_connection_id,
                    LAST_TRACE as _trace,
                )
                key = _get_key()
                conn = _find_connection_id("googledrive") or _find_connection_id("googleslides")
                if key and conn:
                    payload = {
                        "endpoint": f"https://www.googleapis.com/drive/v3/files/{deck_id}/export?mimeType=application/pdf",
                        "method": "GET",
                        "connected_account_id": conn,
                    }
                    resp = _rq.post(
                        "https://backend.composio.dev/api/v3.1/tools/execute/proxy",
                        headers={"x-api-key": key, "Content-Type": "application/json"},
                        json=payload, timeout=90,
                    )
                    _trace.append({"slug": "PROXY GET drive/export pdf",
                                   "connected_account_id": conn,
                                   "status": resp.status_code,
                                   "body_preview": resp.text[:200]})
                    if resp.ok:
                        # Composio wraps the response — the raw file bytes come
                        # back inside data.data as a base64 string (or hex).
                        parsed = resp.json()
                        raw = ((parsed or {}).get("data") or {}).get("data")
                        if isinstance(raw, str):
                            import base64
                            try:
                                pdf_bytes = base64.b64decode(raw)
                            except Exception:
                                pdf_bytes = raw.encode("latin-1", errors="ignore")
                            with open(pdf_out_path, "wb") as fh:
                                fh.write(pdf_bytes)
                            pdf_saved = pdf_out_path
            except Exception as exc:
                print(f"[slides] pdf export (non-fatal): {exc}")

        return {"slide_url": slide_url, "pdf_path": pdf_saved}

    except Exception as exc:
        import traceback as _tb
        print(f"[slides] error: {_tb.format_exc()[:2000]}")
        return None


def _build_slides_requests(obs_rows, client_display, meta):
    """Build a Slides deck mirroring the Arizona Home Grants reference PDF.

    Slide layout (finding): grey background off-white; header line with
    'Finding · Category' left and a colored priority chip right; a huge
    blue stat with the hook context beside it in bold black; a card on
    the left labelled 'What we found' listing URL + colored status pill
    per line; a card on the right labelled 'What it costs you' with the
    consequence sentence and an optional supporting stat.
    """
    from audit.version import VERSION, PLAN_TIERS, resolve_plan
    from audit.hook_copy import STATUS_LABEL
    reqs = []

    def emu(inches): return int(inches * 914400)

    slide_counter = [0]
    def _slide_id():
        slide_counter[0] += 1
        return f"slide{slide_counter[0]:04d}"

    # ── Colors ────────────────────────────────────────────────────────────
    BLUE     = {"red": 0.055, "green": 0.35, "blue": 0.98}   # #0e59fa
    TEXT     = {"red": 0.06,  "green": 0.06, "blue": 0.09}
    MUTED    = {"red": 0.44,  "green": 0.46, "blue": 0.52}
    WHITE    = {"red": 1.0,   "green": 1.0,  "blue": 1.0}
    PRIO_TEXT = {
        "Critical": {"red": 0.86, "green": 0.15, "blue": 0.15},
        "High":     {"red": 0.94, "green": 0.44, "blue": 0.10},
        "Medium":   {"red": 0.85, "green": 0.58, "blue": 0.05},
        "Low":      {"red": 0.20, "green": 0.55, "blue": 0.30},
    }
    STATUS_TEXT = {
        "critical": {"red": 0.72, "green": 0.13, "blue": 0.13},
        "high":     {"red": 0.85, "green": 0.44, "blue": 0.10},
        "medium":   {"red": 0.72, "green": 0.50, "blue": 0.05},
        "low":      {"red": 0.20, "green": 0.55, "blue": 0.30},
        "ok":       {"red": 0.20, "green": 0.55, "blue": 0.30},
    }
    STATUS_BG = {
        "critical": {"red": 1.0,  "green": 0.87, "blue": 0.87},
        "high":     {"red": 1.0,  "green": 0.90, "blue": 0.80},
        "medium":   {"red": 1.0,  "green": 0.95, "blue": 0.80},
        "low":      {"red": 0.85, "green": 0.92, "blue": 1.0},
        "ok":       {"red": 0.85, "green": 0.94, "blue": 0.86},
    }
    CARD_BG  = {"red": 0.96, "green": 0.96, "blue": 0.98}

    def _text_box(page_id, box_id, x, y, w, h, shape="TEXT_BOX", fill=None):
        reqs.append({"createShape": {
            "objectId": box_id, "shapeType": shape,
            "elementProperties": {
                "pageObjectId": page_id,
                "size":       {"width":  {"magnitude": emu(w), "unit": "EMU"},
                               "height": {"magnitude": emu(h), "unit": "EMU"}},
                "transform":  {"scaleX": 1, "scaleY": 1,
                               "translateX": emu(x), "translateY": emu(y),
                               "unit": "EMU"}}}})
        if fill:
            reqs.append({"updateShapeProperties": {
                "objectId": box_id,
                "shapeProperties": {
                    "shapeBackgroundFill": {"solidFill": {
                        "color": {"rgbColor": fill}}},
                    "outline": {"outlineFill": {"solidFill": {
                        "color": {"rgbColor": fill}}}},
                },
                "fields": "shapeBackgroundFill.solidFill.color,outline.outlineFill.solidFill.color",
            }})

    def _write(box_id, text, size=12, bold=False, color=None, align=None):
        if not text:
            return
        reqs.append({"insertText": {"objectId": box_id, "text": str(text)[:1800]}})
        style = {"fontFamily": "Inter",
                 "fontSize": {"magnitude": size, "unit": "PT"},
                 "bold": bool(bold)}
        fields = "fontFamily,fontSize,bold"
        if color:
            style["foregroundColor"] = {"opaqueColor": {"rgbColor": color}}
            fields += ",foregroundColor"
        reqs.append({"updateTextStyle": {
            "objectId": box_id, "textRange": {"type": "ALL"},
            "style": style, "fields": fields}})
        if align:
            reqs.append({"updateParagraphStyle": {
                "objectId": box_id, "textRange": {"type": "ALL"},
                "style": {"alignment": align}, "fields": "alignment"}})

    def _write_runs(box_id, runs):
        """runs: [(text, {size, bold, color?})...] concatenated in order.

        Uses one insertText for the joined string, then updateTextStyle
        per range to apply per-run styling.
        """
        if not runs:
            return
        joined = "".join(r[0] for r in runs)
        reqs.append({"insertText": {"objectId": box_id, "text": joined[:1800]}})
        pos = 0
        for text, style_hint in runs:
            end = pos + len(text)
            style = {"fontFamily": "Inter",
                     "fontSize": {"magnitude": style_hint.get("size", 11), "unit": "PT"},
                     "bold": bool(style_hint.get("bold"))}
            fields = "fontFamily,fontSize,bold"
            color = style_hint.get("color")
            if color:
                style["foregroundColor"] = {"opaqueColor": {"rgbColor": color}}
                fields += ",foregroundColor"
            reqs.append({"updateTextStyle": {
                "objectId": box_id,
                "textRange": {"type": "FIXED_RANGE",
                              "startIndex": pos, "endIndex": end},
                "style": style, "fields": fields}})
            pos = end

    def _split_stat(hook_ctx):
        """Split hook_ctx like '67% of pages...' into ('67%', ' of pages...').

        If no %/number leads the string, returns (None, hook_ctx).
        """
        import re
        m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?%?)\s*(.*)$", hook_ctx or "")
        if m and m.group(1) and ("%" in m.group(1) or m.group(2)):
            return m.group(1), m.group(2)
        return None, hook_ctx or ""

    # ── Intro slide ──────────────────────────────────────────────────────
    def _intro(row):
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.5, 0.35, 9.0, 0.4)
        _write(hdr, f"Gushwork Website audit · {client_display}",
               size=12, bold=True, color=MUTED)

        # Big blue stat
        stat = f"{sid}_stat"
        _text_box(sid, stat, 0.5, 0.95, 9.0, 1.4)
        _write(stat, row.get("hook_stat") or "+33%",
               size=64, bold=True, color=BLUE)

        # Hook context bold black
        ctx = f"{sid}_ctx"
        _text_box(sid, ctx, 0.5, 2.4, 9.0, 0.8)
        _write(ctx, row.get("hook_ctx") or "Increase your leads by 33%.",
               size=22, bold=True, color=TEXT)

        # Formula line
        if row.get("found"):
            fd = f"{sid}_found"
            _text_box(sid, fd, 0.5, 3.3, 9.0, 0.6)
            _write(fd, row["found"], size=14, color=MUTED)
        if row.get("costs"):
            cs = f"{sid}_costs"
            _text_box(sid, cs, 0.5, 4.0, 9.0, 1.0)
            _write(cs, row["costs"], size=16, bold=True, color=TEXT)

    # ── Finding slide (PDF-matched) ──────────────────────────────────────
    def _finding(row):
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        # Header: Finding · Category
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.4, 0.3, 6.0, 0.4)
        _write(hdr, f"Finding · {row.get('category','')}",
               size=13, bold=True, color=MUTED)
        # Priority chip (right)
        prio = row.get("priority", "")
        if prio in PRIO_TEXT:
            pcol = PRIO_TEXT[prio]
            chip = f"{sid}_chip"
            _text_box(sid, chip, 7.4, 0.3, 2.2, 0.4)
            _write(chip, f"● {prio}", size=12, bold=True, color=pcol, align="END")

        # Big blue stat (left) + hook context wrapping to right (bold black)
        stat = f"{sid}_stat"
        _text_box(sid, stat, 0.4, 0.85, 4.0, 1.6)
        _write(stat, row.get("hook_stat") or "",
               size=64, bold=True, color=BLUE)

        # Hook context: bold text with the initial number highlighted in muted
        ctx = f"{sid}_ctx"
        _text_box(sid, ctx, 4.6, 0.9, 5.1, 1.6)
        pct, rest = _split_stat(row.get("hook_ctx") or "")
        if pct:
            _write_runs(ctx, [
                (row.get("hook_ctx",""), {"size": 18, "bold": True, "color": TEXT}),
            ])
        else:
            _write(ctx, row.get("hook_ctx") or "", size=18, bold=True, color=TEXT)

        # Left card: What we found
        wf_card = f"{sid}_wfcard"
        _text_box(sid, wf_card, 0.4, 2.7, 5.4, 2.65,
                  shape="RECTANGLE", fill=CARD_BG)
        wf_lbl = f"{sid}_wflbl"
        _text_box(sid, wf_lbl, 0.6, 2.85, 5.0, 0.3)
        _write(wf_lbl, "What we found", size=10, bold=True, color=MUTED)
        # Category-right label
        cat_lbl = f"{sid}_catlbl"
        _text_box(sid, cat_lbl, 3.6, 2.85, 2.0, 0.3)
        _write(cat_lbl, row.get("category",""), size=10, bold=True,
               color=MUTED, align="END")

        # URL list with status labels (right-aligned pill text)
        urls_str = (row.get("found") or "").strip()
        urls = [u.strip() for u in urls_str.split("\n") if u.strip()][:6]
        # look up status label + color for this finding
        # We only have (category, priority) in read_for_deck rows —
        # infer key from status labels dict via category text.
        # Since we don't preserve the finding key across the sheet round-trip,
        # derive a status label from priority.
        default_status = {
            "Critical": ("Issue", "critical"),
            "High":     ("Issue", "high"),
            "Medium":   ("Issue", "medium"),
            "Low":      ("Issue", "low"),
        }.get(prio, ("Issue", "medium"))
        status_text, status_color = default_status
        # Try to find a better label matching the category text
        cat_lc = (row.get("category","") or "").lower()
        for key, (label, color) in STATUS_LABEL.items():
            if key.replace("_", " ") in cat_lc or label.lower() in cat_lc:
                status_text, status_color = label, color
                break

        row_y = 3.25
        for u in urls:
            uid = f"{sid}_u{urls.index(u)}"
            _text_box(sid, uid, 0.7, row_y, 3.8, 0.32)
            _write(uid, u, size=10, color=TEXT)
            # status pill (small rounded rect look via colored text)
            pill = f"{sid}_p{urls.index(u)}"
            _text_box(sid, pill, 4.4, row_y - 0.02, 1.3, 0.32,
                      shape="RECTANGLE", fill=STATUS_BG.get(status_color, CARD_BG))
            _write(pill, status_text, size=9, bold=True,
                   color=STATUS_TEXT.get(status_color, TEXT), align="CENTER")
            row_y += 0.34

        # Right card: What it costs you
        cs_card = f"{sid}_cscard"
        _text_box(sid, cs_card, 6.0, 2.7, 3.6, 1.55,
                  shape="RECTANGLE", fill=CARD_BG)
        cs_lbl = f"{sid}_cslbl"
        _text_box(sid, cs_lbl, 6.2, 2.85, 3.2, 0.3)
        _write(cs_lbl, "What it costs you", size=10, bold=True, color=MUTED)
        cs_body = f"{sid}_csbody"
        _text_box(sid, cs_body, 6.2, 3.2, 3.2, 1.1)
        _write(cs_body, row.get("costs","") or "", size=12, bold=True, color=TEXT)

        # Supporting stat card (below Costs card)
        if row.get("support"):
            sup_card = f"{sid}_supcard"
            _text_box(sid, sup_card, 6.0, 4.35, 3.6, 1.0,
                      shape="RECTANGLE", fill=CARD_BG)
            sup_txt = f"{sid}_sup"
            _text_box(sid, sup_txt, 6.2, 4.45, 3.2, 0.85)
            sup_pct, sup_rest = _split_stat(row["support"])
            if sup_pct:
                _write_runs(sup_txt, [
                    (sup_pct + " ", {"size": 26, "bold": True, "color": BLUE}),
                    (sup_rest,      {"size": 11, "bold": True, "color": TEXT}),
                ])
            else:
                _write(sup_txt, row["support"], size=12, bold=True, color=TEXT)

    # ── Ending slide ─────────────────────────────────────────────────────
    def _ending(row):
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.5, 0.4, 9.0, 0.4)
        _write(hdr, f"Gushwork · {client_display}", size=13, bold=True, color=MUTED)
        big = f"{sid}_big"
        _text_box(sid, big, 0.5, 1.3, 9.0, 2.0)
        pct, rest = _split_stat(row.get("hook_ctx") or "")
        if pct:
            _write_runs(big, [
                (pct + " ", {"size": 60, "bold": True, "color": BLUE}),
                (rest,      {"size": 22, "bold": True, "color": TEXT}),
            ])
        else:
            _write(big, row.get("hook_ctx") or "Approve the audit fixes.",
                   size=28, bold=True, color=TEXT)
        cta = f"{sid}_cta"
        _text_box(sid, cta, 0.5, 4.0, 9.0, 1.0)
        _write(cta, row.get("costs") or "Approve the audit fixes.",
               size=18, bold=True, color=MUTED)

    # ── Projected Impact slide ────────────────────────────────────────────
    def _impact(plan_tier):
        tier = PLAN_TIERS[plan_tier]
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.5, 0.4, 9.0, 0.4)
        _write(hdr, "Projected Impact", size=13, bold=True, color=MUTED)
        body = f"{sid}_b"
        _text_box(sid, body, 0.5, 1.1, 9.0, 4.0)
        _write(body,
               f"Expected leads on the ${plan_tier} / month plan\n\n"
               f"Month 3-4:   {tier['M3-4']} leads / month\n"
               f"Month 6-7:   {tier['M6-7']} leads / month\n"
               f"Month 9-10:  {tier['M9-10']} leads / month\n\n"
               "Cost per lead expected to drop ~5% vs current spend.",
               size=14, color=TEXT)

    # Order by Slide # from the sheet; only rows marked Approved
    approved = [r for r in obs_rows if r.get("approved")]
    if not approved:
        approved = obs_rows

    for r in approved:
        stype = r.get("slide_type", "finding")
        if stype == "intro":
            _intro(r)
        elif stype == "ending":
            _ending(r)
        else:
            _finding(r)

    plan_tier = resolve_plan((meta or {}).get("plan"))
    if plan_tier and plan_tier in PLAN_TIERS:
        _impact(plan_tier)
    return reqs
