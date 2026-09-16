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
        # PDF export via Composio isn't available as a named action; skip.
        return {"slide_url": slide_url, "pdf_path": None}

    except Exception as exc:
        import traceback as _tb
        print(f"[slides] error: {_tb.format_exc()[:2000]}")
        return None


def _build_slides_requests(obs_rows, client_display, meta):
    """Build a Slides deck mirroring the Arizona Home Grants reference PDF.

    Every slide uses a BLANK layout with explicit text boxes so the PDF's
    visual hierarchy comes through:
      • Header line: "Finding · <Category>" + priority tag right-aligned
      • BIG STAT (48pt bold) top-left
      • Hook context (14pt muted) directly under the stat
      • "What we found" (left column, 11pt with 9pt bold section label)
      • "What it costs you" (right column) + optional supporting stat
      • Footer: client domain and slide number
    """
    from audit.version import VERSION, PLAN_TIERS, resolve_plan
    reqs = []

    # Coordinate helpers — Slides page is 10in × 5.625in (widescreen).
    def emu(inches): return int(inches * 914400)

    slide_counter = [0]
    def _slide_id():
        slide_counter[0] += 1
        # Slides API requires objectId length >= 5.
        return f"slide{slide_counter[0]:04d}"

    def _text_box(page_id, box_id, x, y, w, h):
        reqs.append({"createShape": {
            "objectId": box_id, "shapeType": "TEXT_BOX",
            "elementProperties": {
                "pageObjectId": page_id,
                "size":       {"width":  {"magnitude": emu(w), "unit": "EMU"},
                               "height": {"magnitude": emu(h), "unit": "EMU"}},
                "transform":  {"scaleX": 1, "scaleY": 1,
                               "translateX": emu(x), "translateY": emu(y),
                               "unit": "EMU"}}}})

    def _write(box_id, text, size=12, bold=False, color=None, align=None):
        if not text:
            return
        reqs.append({"insertText": {"objectId": box_id, "text": str(text)[:1600]}})
        style = {"fontFamily": "Proxima Nova",
                 "fontSize": {"magnitude": size, "unit": "PT"},
                 "bold": bool(bold)}
        fields = "fontFamily,fontSize,bold"
        if color:
            style["foregroundColor"] = {"opaqueColor": {"rgbColor": color}}
            fields += ",foregroundColor"
        reqs.append({"updateTextStyle": {
            "objectId": box_id,
            "textRange": {"type": "ALL"},
            "style": style,
            "fields": fields}})
        if align:
            reqs.append({"updateParagraphStyle": {
                "objectId": box_id,
                "textRange": {"type": "ALL"},
                "style": {"alignment": align},
                "fields": "alignment"}})

    # ── Intro slide (client + hook stat + hook context + formula + costs) ──
    def _intro(row):
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        # Small header line
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.5, 0.35, 9.0, 0.4)
        _write(hdr, f"Gushwork Website audit · {client_display}",
               size=12, bold=True, color={"red": 0.42, "green": 0.45, "blue": 0.5})
        # Big stat
        stat = f"{sid}_stat"
        _text_box(sid, stat, 0.5, 1.0, 9.0, 1.1)
        _write(stat, row.get("hook_stat") or "+33%",
               size=48, bold=True, color={"red": 0.1, "green": 0.1, "blue": 0.11})
        # Hook context
        ctx = f"{sid}_ctx"
        _text_box(sid, ctx, 0.5, 2.2, 9.0, 0.9)
        _write(ctx, row.get("hook_ctx") or "Increase your leads.",
               size=22, bold=True)
        # Formula (What We Found for intro)
        if row.get("found"):
            fd = f"{sid}_found"
            _text_box(sid, fd, 0.5, 3.3, 9.0, 0.6)
            _write(fd, row["found"], size=14,
                   color={"red": 0.42, "green": 0.45, "blue": 0.5})
        # Cost / example uplift
        if row.get("costs"):
            cs = f"{sid}_costs"
            _text_box(sid, cs, 0.5, 4.0, 9.0, 1.0)
            _write(cs, row["costs"], size=15, bold=True)

    # ── Finding slide (matches PDF page 2/3/4/5/6 layout) ─────────────────
    def _finding(row):
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        # Top: Finding · Category   [priority right-aligned]
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.5, 0.35, 6.5, 0.45)
        _write(hdr, f"Finding · {row.get('category','')}",
               size=13, bold=True,
               color={"red": 0.42, "green": 0.45, "blue": 0.5})
        prio_box = f"{sid}_prio"
        _text_box(sid, prio_box, 7.0, 0.35, 2.5, 0.45)
        prio = row.get("priority", "")
        prio_color = {
            "Critical": {"red": 0.86, "green": 0.15, "blue": 0.15},
            "High":     {"red": 0.9,  "green": 0.4,  "blue": 0.1},
            "Medium":   {"red": 0.85, "green": 0.6,  "blue": 0.05},
            "Low":      {"red": 0.2,  "green": 0.55, "blue": 0.3},
        }.get(prio, {"red": 0.4, "green": 0.4, "blue": 0.4})
        _write(prio_box, prio, size=12, bold=True, color=prio_color, align="END")

        # Right side big stat + subtitle (matches PDF hero block)
        stat = f"{sid}_stat"
        _text_box(sid, stat, 4.8, 1.05, 4.7, 1.0)
        _write(stat, row.get("hook_stat") or "",
               size=44, bold=True, color={"red": 0.1, "green": 0.1, "blue": 0.11})
        ctx = f"{sid}_ctx"
        _text_box(sid, ctx, 4.8, 2.15, 4.7, 1.0)
        _write(ctx, row.get("hook_ctx") or "", size=14,
               color={"red": 0.42, "green": 0.45, "blue": 0.5})

        # Left side "What we found" — section label + list
        wf_lbl = f"{sid}_wflbl"
        _text_box(sid, wf_lbl, 0.5, 1.05, 4.0, 0.35)
        _write(wf_lbl, "What we found", size=10, bold=True,
               color={"red": 0.42, "green": 0.45, "blue": 0.5})
        wf_body = f"{sid}_wf"
        _text_box(sid, wf_body, 0.5, 1.4, 4.0, 2.5)
        _write(wf_body, row.get("found") or "—", size=11)

        # Bottom "What it costs you"
        cost_lbl = f"{sid}_costlbl"
        _text_box(sid, cost_lbl, 0.5, 4.05, 9.0, 0.35)
        _write(cost_lbl, "What it costs you", size=10, bold=True,
               color={"red": 0.42, "green": 0.45, "blue": 0.5})
        cost_body = f"{sid}_cost"
        _text_box(sid, cost_body, 0.5, 4.4, 9.0, 0.9)
        _write(cost_body, row.get("costs") or "", size=12, bold=True)
        # Supporting stat (small, muted, right)
        if row.get("support"):
            sup = f"{sid}_sup"
            _text_box(sid, sup, 0.5, 5.15, 9.0, 0.35)
            _write(sup, row["support"], size=10,
                   color={"red": 0.42, "green": 0.45, "blue": 0.5})

    # ── Ending slide ───────────────────────────────────────────────────────
    def _ending(row):
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.5, 0.4, 9.0, 0.4)
        _write(hdr, f"Gushwork · {client_display}", size=13, bold=True,
               color={"red": 0.42, "green": 0.45, "blue": 0.5})
        big = f"{sid}_big"
        _text_box(sid, big, 0.5, 1.4, 9.0, 2.5)
        _write(big, row.get("hook_ctx") or "Approve the audit fixes.",
               size=28, bold=True)
        cta = f"{sid}_cta"
        _text_box(sid, cta, 0.5, 4.1, 9.0, 0.9)
        _write(cta, row.get("costs") or "Approve the audit fixes.",
               size=20, bold=True, color={"red": 0.42, "green": 0.45, "blue": 0.5})

    # ── Projected Impact slide (from plan tier) ────────────────────────────
    def _impact(plan_tier):
        tier = PLAN_TIERS[plan_tier]
        sid = _slide_id()
        reqs.append({"createSlide": {"objectId": sid,
                                     "slideLayoutReference": {"predefinedLayout": "BLANK"}}})
        hdr = f"{sid}_hdr"
        _text_box(sid, hdr, 0.5, 0.4, 9.0, 0.4)
        _write(hdr, "Projected Impact", size=13, bold=True,
               color={"red": 0.42, "green": 0.45, "blue": 0.5})
        body = f"{sid}_b"
        _text_box(sid, body, 0.5, 1.1, 9.0, 4.0)
        _write(body,
               f"Expected leads on the ${plan_tier} / month plan\n\n"
               f"Month 3-4:   {tier['M3-4']} leads / month\n"
               f"Month 6-7:   {tier['M6-7']} leads / month\n"
               f"Month 9-10:  {tier['M9-10']} leads / month\n\n"
               "Cost per lead expected to drop ~5% vs current spend.",
               size=14)

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
