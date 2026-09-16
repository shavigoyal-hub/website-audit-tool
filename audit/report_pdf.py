"""Direct PDF generation matching the Arizona Home Grants reference PDF.

DESIGN RULES (strict — mirrors the reference deck):

Page: 16:9 landscape (10in × 5.625in), white background.
Margins: 0.6in on all sides.

Colors:
    BLUE   = #0057ff   primary accent, big stats
    TEXT   = #0a0a0a   near-black body text
    MUTED  = #6b7280   grey secondary text
    CARD   = #f5f5f7   card background
    SEP    = #e5e7eb   row separator

Priority chip (top-right):
    Critical  bg=#fee2e2 text=#b91c1c dot=#dc2626
    High      bg=#ffedd5 text=#c2410c dot=#f97316
    Medium    bg=#fef3c7 text=#b45309 dot=#f59e0b
    Low       bg=#dbeafe text=#2563eb dot=#3b82f6

Status pill (in "What we found"):
    color of pill picked from status text:
       "No X" / "Missing" / "404" / "5xx" / "Noindex" / "critical"  -> RED_PILL
       "competing" / "duplicate" / "Long" / "Truncated"            -> AMBER_PILL
       "OK" / "1 X" / "green"                                       -> GREEN_PILL
    RED_PILL   bg=#fee2e2 text=#b91c1c
    AMBER_PILL bg=#fef3c7 text=#b45309
    GREEN_PILL bg=#d1fae5 text=#065f46

Typography (Helvetica shipped with reportlab):
    HUGE_STAT   Helvetica-Bold 60-72pt BLUE
    BIG         Helvetica-Bold 22-28pt TEXT
    H2          Helvetica-Bold 18pt TEXT
    BODY_BOLD   Helvetica-Bold 14pt TEXT
    BODY        Helvetica 12pt TEXT
    LABEL       Helvetica 10pt MUTED
    FOOTER      Helvetica 9pt MUTED

Intro layout:
    Header: "Gushwork Website audit · <domain>" small muted top-left.
    Hero centered (large "Increase your leads by 33%" with 33% in blue).
    Subtitle "Same pages. Same website." muted below.
    Formula line: "+5.8% Meta descriptions × +25% Structured data = +33%".
    Example: "10 leads → 14 leads" in bold.
    Footer bottom: "Site audited · <domain>" left, "Prepared by · Gushwork" right.

Finding layout:
    Header: "Finding · <Category>" left; priority chip right.
    Hero: huge blue stat left, bold context wraps right (with any % highlighted blue).
    "What we found" card left half:
        label row "What we found" | "<category>" right-aligned
        rows: URL (left) + colored status pill (right)
        subtle separator between rows
    "What it costs you" card right, bold text
    Supporting card bottom-right with big blue number + bold rest
    Footer: "<domain> · Website audit" left, "Gushwork <n>/<total>" right.

Ending layout:
    Header: "Gushwork · <domain>" small muted.
    Center hero: "Every month you wait, you lose out on 4 extra leads / month..."
        with the number highlighted in blue.
    CTA muted bold at bottom.

Sheet "What We Found" convention:
    Each line is either "URL" or "URL | STATUS_LABEL".
    We parse each line, split on " | ", first part is URL, second (optional)
    is the status label used verbatim on the pill.
"""
import os
import re

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas as rl_canvas

from audit.hook_copy import STATUS_LABEL
from audit.version import PLAN_TIERS, resolve_plan

# ── Constants ─────────────────────────────────────────────────────────────
PAGE_W = 10 * 72
PAGE_H = 5.625 * 72
MARGIN = 0.6 * 72

BLUE   = HexColor("#0057ff")
TEXT   = HexColor("#0a0a0a")
MUTED  = HexColor("#6b7280")
CARD   = HexColor("#f5f5f7")
SEP    = HexColor("#e5e7eb")
WHITE  = HexColor("#ffffff")

PRIO = {
    "Critical": {"bg": HexColor("#fee2e2"), "fg": HexColor("#b91c1c"), "dot": HexColor("#dc2626")},
    "High":     {"bg": HexColor("#ffedd5"), "fg": HexColor("#c2410c"), "dot": HexColor("#f97316")},
    "Medium":   {"bg": HexColor("#fef3c7"), "fg": HexColor("#b45309"), "dot": HexColor("#f59e0b")},
    "Low":      {"bg": HexColor("#dbeafe"), "fg": HexColor("#2563eb"), "dot": HexColor("#3b82f6")},
}
RED_PILL   = {"bg": HexColor("#fee2e2"), "fg": HexColor("#b91c1c")}
AMBER_PILL = {"bg": HexColor("#fef3c7"), "fg": HexColor("#b45309")}
GREEN_PILL = {"bg": HexColor("#d1fae5"), "fg": HexColor("#065f46")}
BLUE_PILL  = {"bg": HexColor("#dbeafe"), "fg": HexColor("#1d4ed8")}


def _pt(inches): return inches * 72


# ── Text helpers ──────────────────────────────────────────────────────────
def _wrap(c, text, font, size, max_w):
    if not text:
        return []
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if c.stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines


def _pill(c, x, y, text, font, size, fg, bg, pad_x=8, pad_y=4, radius=None):
    text_w = c.stringWidth(text, font, size)
    w = text_w + pad_x * 2
    h = size + pad_y * 2
    r = radius if radius is not None else h / 2
    c.setFillColor(bg)
    c.setStrokeColor(bg)
    c.roundRect(x, y, w, h, r, stroke=1, fill=1)
    c.setFillColor(fg)
    c.setFont(font, size)
    c.drawString(x + pad_x, y + pad_y + 1, text)
    return w, h


def _priority_chip(c, x_right, y, priority):
    """Draw a priority pill with a leading colored dot, right-aligned so its
    right edge is at x_right. Returns the leftmost x used."""
    if priority not in PRIO:
        return x_right
    conf = PRIO[priority]
    # Measure
    font, size = "Helvetica-Bold", 10
    label = priority
    text_w = c.stringWidth(label, font, size)
    dot_r = 4
    pad_x, pad_y = 10, 4
    inner = dot_r * 2 + 5 + text_w  # dot + gap + text
    total_w = inner + pad_x * 2
    total_h = size + pad_y * 2
    x = x_right - total_w
    # bg
    c.setFillColor(conf["bg"]); c.setStrokeColor(conf["bg"])
    c.roundRect(x, y, total_w, total_h, total_h / 2, stroke=1, fill=1)
    # dot
    c.setFillColor(conf["dot"])
    c.circle(x + pad_x + dot_r, y + total_h / 2, dot_r, stroke=0, fill=1)
    # text
    c.setFillColor(conf["fg"])
    c.setFont(font, size)
    c.drawString(x + pad_x + dot_r * 2 + 5, y + pad_y + 1, label)
    return x


def _pill_color_for(label):
    """Pick a pill palette based on the status label wording."""
    if not label:
        return AMBER_PILL
    low = label.lower()
    if any(k in low for k in ("no ", "missing", "404", "5xx", "noindex",
                              "error", "critical", "render error", "cls high",
                              "lcp >", "perf <")):
        return RED_PILL
    if any(k in low for k in ("competing", "duplicate", "long", "truncated",
                              "stuffed", "medium", "heavy", "blocking",
                              "wrong", "few", "over-length", "js-only")):
        return AMBER_PILL
    if any(k in low for k in ("ok", "1 h1", "single", "one", "good", "passed")):
        return GREEN_PILL
    return AMBER_PILL


def _split_lead_number(text):
    if not text: return None, ""
    m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?)\s*(.*)$", str(text))
    if m and m.group(1):
        return m.group(1).strip(), m.group(2).strip()
    return None, str(text).strip()


def _footer(c, left, right):
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED)
    c.drawString(MARGIN, _pt(0.35), left)
    c.drawRightString(PAGE_W - MARGIN, _pt(0.35), right)


def _draw_stat_and_context(c, stat, context, x, y_top, w, stat_font_size=54):
    """Draw a big blue stat with a bold-black context beside/below it,
    highlighting any leading number in the context in blue. Returns the y
    below which the block ended.
    """
    # stat
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", stat_font_size)
    stat_w = c.stringWidth(stat or "", "Helvetica-Bold", stat_font_size)
    if stat:
        c.drawString(x, y_top - stat_font_size, stat)

    # context: split leading number, draw as two-tone
    pct, rest = _split_lead_number(context)
    ctx_x = x + stat_w + (14 if stat else 0)
    ctx_w = w - (stat_w + (14 if stat else 0))
    ctx_font_size = 18
    if pct:
        # pct in blue
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", ctx_font_size)
        pct_w = c.stringWidth(pct + " ", "Helvetica-Bold", ctx_font_size)
        # Wrap the rest of the sentence starting after pct
        lines = _wrap(c, rest, "Helvetica-Bold", ctx_font_size, ctx_w - pct_w)
        # First line: pct then rest starts
        if lines:
            c.drawString(ctx_x, y_top - stat_font_size + 12, pct)
            c.setFillColor(TEXT)
            c.drawString(ctx_x + pct_w, y_top - stat_font_size + 12, lines[0])
            for i, ln in enumerate(lines[1:], start=1):
                c.drawString(ctx_x, y_top - stat_font_size + 12 - i * 22, ln)
        else:
            c.drawString(ctx_x, y_top - stat_font_size + 12, pct)
    else:
        c.setFillColor(TEXT)
        c.setFont("Helvetica-Bold", ctx_font_size)
        lines = _wrap(c, context or "", "Helvetica-Bold", ctx_font_size, ctx_w)
        for i, ln in enumerate(lines):
            c.drawString(ctx_x, y_top - stat_font_size + 12 - i * 22, ln)


# ── Intro page ────────────────────────────────────────────────────────────
def _draw_intro(c, row, client_display):
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # Header
    c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, PAGE_H - _pt(0.45),
                 f"Gushwork Website audit · {client_display}")

    # Centered hero
    hook_ctx = row.get("hook_ctx") or "Increase your leads by 33%"
    hook_stat = row.get("hook_stat") or "+33%"
    # Split the hook_ctx to highlight the stat portion in blue
    stat_in_ctx = hook_stat.strip("+ %")
    # Try to build "Increase your leads by <stat>" split
    parts = hook_ctx.split(hook_stat) if hook_stat and hook_stat in hook_ctx else [hook_ctx]

    # Big heading centered
    heading_size = 44
    c.setFont("Helvetica-Bold", heading_size)
    hh = PAGE_H - _pt(1.9)
    text_w = c.stringWidth(hook_ctx, "Helvetica-Bold", heading_size)
    max_w = PAGE_W - MARGIN * 2
    if text_w <= max_w and hook_stat in hook_ctx:
        left, right = parts[0], parts[-1]
        left_w  = c.stringWidth(left,  "Helvetica-Bold", heading_size)
        stat_w  = c.stringWidth(hook_stat, "Helvetica-Bold", heading_size)
        right_w = c.stringWidth(right, "Helvetica-Bold", heading_size)
        total = left_w + stat_w + right_w
        x = (PAGE_W - total) / 2
        c.setFillColor(TEXT); c.drawString(x, hh, left)
        c.setFillColor(BLUE); c.drawString(x + left_w, hh, hook_stat)
        c.setFillColor(TEXT); c.drawString(x + left_w + stat_w, hh, right)
    else:
        # Wrap
        lines = _wrap(c, hook_ctx, "Helvetica-Bold", heading_size, max_w)
        for i, ln in enumerate(lines):
            w = c.stringWidth(ln, "Helvetica-Bold", heading_size)
            c.setFillColor(TEXT)
            c.drawString((PAGE_W - w) / 2, hh - i * (heading_size + 4), ln)

    # Subtitle "Same pages. Same website."
    subtitle = row.get("observation") or "Same pages. Same website."
    if subtitle and subtitle != hook_ctx:
        c.setFillColor(MUTED); c.setFont("Helvetica", 18)
        w = c.stringWidth(subtitle, "Helvetica", 18)
        c.drawString((PAGE_W - w) / 2, PAGE_H - _pt(2.6), subtitle)

    # Formula centered
    formula = row.get("found") or ""
    if formula:
        c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 15)
        lines = _wrap(c, formula, "Helvetica-Bold", 15, PAGE_W - MARGIN * 2)
        for i, ln in enumerate(lines):
            w = c.stringWidth(ln, "Helvetica-Bold", 15)
            c.drawString((PAGE_W - w) / 2, PAGE_H - _pt(3.3) - i * 20, ln)

    # Example uplift bold centered
    example = row.get("costs") or ""
    if example:
        c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 16)
        lines = _wrap(c, example, "Helvetica-Bold", 16, PAGE_W - MARGIN * 2)
        for i, ln in enumerate(lines):
            w = c.stringWidth(ln, "Helvetica-Bold", 16)
            c.drawString((PAGE_W - w) / 2, PAGE_H - _pt(4.1) - i * 22, ln)

    # Footer split
    c.setFillColor(MUTED); c.setFont("Helvetica", 9)
    c.drawString(MARGIN, _pt(0.8), "Site audited")
    c.drawRightString(PAGE_W - MARGIN, _pt(0.8), "Prepared by")
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGIN, _pt(0.5), client_display)
    c.drawRightString(PAGE_W - MARGIN, _pt(0.5), "Gushwork")


# ── Finding page ──────────────────────────────────────────────────────────
def _draw_finding(c, row, page_no, total_pages, client_display):
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # Header line
    c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, PAGE_H - _pt(0.45),
                 f"Finding · {row.get('category','')}")
    # Priority chip right
    prio = row.get("priority", "")
    _priority_chip(c, PAGE_W - MARGIN, PAGE_H - _pt(0.55), prio)

    # Hero: big stat + bold context, upper block
    _draw_stat_and_context(
        c,
        row.get("hook_stat", ""), row.get("hook_ctx", ""),
        x=MARGIN, y_top=PAGE_H - _pt(0.9),
        w=PAGE_W - MARGIN * 2, stat_font_size=54,
    )

    # Layout: What we found card LEFT, What it costs you card RIGHT
    card_top_y   = _pt(2.75)      # top of cards from bottom of page
    left_x, left_w  = MARGIN, _pt(5.0)
    right_x        = MARGIN + left_w + _pt(0.2)
    right_w        = PAGE_W - MARGIN - right_x

    # LEFT CARD
    left_h = _pt(2.5)
    c.setFillColor(CARD); c.setStrokeColor(CARD)
    c.roundRect(left_x, card_top_y - left_h, left_w, left_h, 10, stroke=1, fill=1)
    # Label row
    c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 10)
    c.drawString(left_x + 16, card_top_y - _pt(0.28), "What we found")
    cat_lbl = row.get("category", "")
    c.drawRightString(left_x + left_w - 16, card_top_y - _pt(0.28), cat_lbl)
    # URL rows with pills
    raw_urls = [u.strip() for u in (row.get("found") or "").split("\n") if u.strip()][:6]
    row_h = _pt(0.36)
    for i, entry in enumerate(raw_urls):
        y = card_top_y - _pt(0.6) - i * row_h
        # Split on " | " or double space for status label
        if " | " in entry:
            url, label = entry.split(" | ", 1)
        else:
            url, label = entry, _default_status_for(row)
        # separator (light line above row 2+)
        if i > 0:
            c.setStrokeColor(SEP); c.setLineWidth(0.5)
            c.line(left_x + 16, y + row_h - 6, left_x + left_w - 16, y + row_h - 6)
        # url text (trimmed if long)
        c.setFillColor(TEXT); c.setFont("Helvetica", 10)
        max_url_w = left_w - 16 - _pt(1.5)
        while c.stringWidth(url, "Helvetica", 10) > max_url_w and len(url) > 25:
            url = url[:-2]
        if not url.endswith("…") and url != entry.split(" | ", 1)[0].strip():
            url = url + "…"
        c.drawString(left_x + 16, y + 2, url)
        # pill right-aligned
        palette = _pill_color_for(label)
        pill_w, pill_h = _pill(c, 0, 0, label, "Helvetica-Bold", 9,
                                 palette["fg"], palette["bg"])  # dry
        # actually redraw at correct position
        # undo previous rect+text: simplest is to redraw all at correct x
        # But _pill wrote something at (0,0). Overpaint that rectangle with white:
        c.setFillColor(WHITE); c.setStrokeColor(WHITE)
        c.roundRect(0, 0, pill_w, pill_h, pill_h/2, stroke=1, fill=1)
        _pill(c, left_x + left_w - 16 - pill_w, y - 1, label,
              "Helvetica-Bold", 9, palette["fg"], palette["bg"])

    # RIGHT CARD - What it costs you
    right_h_top = _pt(1.35)
    c.setFillColor(CARD); c.setStrokeColor(CARD)
    c.roundRect(right_x, card_top_y - right_h_top, right_w, right_h_top, 10, stroke=1, fill=1)
    c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 10)
    c.drawString(right_x + 16, card_top_y - _pt(0.28), "What it costs you")
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 13)
    for i, ln in enumerate(_wrap(c, row.get("costs", ""),
                                 "Helvetica-Bold", 13, right_w - 32)):
        c.drawString(right_x + 16, card_top_y - _pt(0.6) - i * 16, ln)

    # SUPPORTING STAT CARD (below Costs)
    if row.get("support"):
        sup_top = card_top_y - right_h_top - _pt(0.12)
        sup_h = _pt(1.0)
        c.setFillColor(CARD); c.setStrokeColor(CARD)
        c.roundRect(right_x, sup_top - sup_h, right_w, sup_h, 10, stroke=1, fill=1)
        pct, rest = _split_lead_number(row["support"])
        if pct:
            c.setFillColor(BLUE); c.setFont("Helvetica-Bold", 32)
            c.drawString(right_x + 16, sup_top - _pt(0.55), pct)
            c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 11)
            for i, ln in enumerate(_wrap(c, rest,
                                         "Helvetica-Bold", 11, right_w - 32)):
                c.drawString(right_x + 16, sup_top - _pt(0.8) - i * 13, ln)
        else:
            c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 12)
            for i, ln in enumerate(_wrap(c, row["support"],
                                         "Helvetica-Bold", 12, right_w - 32)):
                c.drawString(right_x + 16, sup_top - _pt(0.35) - i * 15, ln)

    # Footer
    _footer(c, f"{client_display} · Website audit",
            f"Gushwork  {page_no:02d} / {total_pages:02d}")


def _default_status_for(row):
    """When a URL line has no explicit '| status' suffix, invent a sensible one."""
    cat = (row.get("category") or "").lower()
    for _, (label, _color) in STATUS_LABEL.items():
        if _  and _.replace("_", " ") in cat:  # never taken (leading _)
            return label
    for key, (label, _color) in STATUS_LABEL.items():
        if key.replace("_", " ") in cat or label.lower() in cat:
            return label
    prio = row.get("priority", "")
    return {"Critical": "Critical",
            "High":     "Issue",
            "Medium":   "Warning",
            "Low":      "Minor"}.get(prio, "Issue")


# ── Ending page ───────────────────────────────────────────────────────────
def _draw_ending(c, row, client_display):
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # Header
    c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, PAGE_H - _pt(0.45), f"Gushwork · {client_display}")

    ctx = row.get("hook_ctx") or "Approve the audit fixes."
    pct, rest = _split_lead_number(ctx)
    # Big centred sentence with pct highlighted blue
    heading_size = 34
    c.setFont("Helvetica-Bold", heading_size)
    if pct and rest:
        pct_w = c.stringWidth(pct + " ", "Helvetica-Bold", heading_size)
        rest_lines = _wrap(c, rest, "Helvetica-Bold", heading_size, PAGE_W - MARGIN * 2 - pct_w)
        if rest_lines:
            first = rest_lines[0]
            first_w = c.stringWidth(first, "Helvetica-Bold", heading_size)
            total = pct_w + first_w
            x = (PAGE_W - total) / 2
            y = PAGE_H - _pt(2.4)
            c.setFillColor(BLUE); c.drawString(x, y, pct)
            c.setFillColor(TEXT); c.drawString(x + pct_w, y, first)
            for i, ln in enumerate(rest_lines[1:], start=1):
                w = c.stringWidth(ln, "Helvetica-Bold", heading_size)
                c.drawString((PAGE_W - w) / 2, y - i * (heading_size + 4), ln)
    else:
        c.setFillColor(TEXT)
        lines = _wrap(c, ctx, "Helvetica-Bold", heading_size, PAGE_W - MARGIN * 2)
        y = PAGE_H - _pt(2.4)
        for i, ln in enumerate(lines):
            w = c.stringWidth(ln, "Helvetica-Bold", heading_size)
            c.drawString((PAGE_W - w) / 2, y - i * (heading_size + 4), ln)

    # CTA
    cta = row.get("costs") or "Approve the audit fixes."
    c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 18)
    lines = _wrap(c, cta, "Helvetica-Bold", 18, PAGE_W - MARGIN * 2)
    y = _pt(1.5)
    for i, ln in enumerate(lines):
        w = c.stringWidth(ln, "Helvetica-Bold", 18)
        c.drawString((PAGE_W - w) / 2, y - i * 22, ln)


# ── Projected impact page ─────────────────────────────────────────────────
def _draw_impact(c, plan_tier, client_display):
    tier = PLAN_TIERS[plan_tier]
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, PAGE_H - _pt(0.45), "Projected Impact")
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 24)
    c.drawString(MARGIN, PAGE_H - _pt(1.1),
                 f"Expected leads on the ${plan_tier} / month plan")
    y = PAGE_H - _pt(2.1)
    for label, val in [("Month 3-4", tier["M3-4"]),
                       ("Month 6-7", tier["M6-7"]),
                       ("Month 9-10", tier["M9-10"])]:
        c.setFillColor(MUTED); c.setFont("Helvetica", 14)
        c.drawString(MARGIN + _pt(0.2), y, label)
        c.setFillColor(BLUE); c.setFont("Helvetica-Bold", 20)
        c.drawString(MARGIN + _pt(1.8), y, f"{val} leads / month")
        y -= _pt(0.55)
    c.setFillColor(MUTED); c.setFont("Helvetica", 12)
    c.drawString(MARGIN, _pt(0.7),
                 "Cost per lead expected to drop ~5% vs current spend.")


# ── Public entry point ────────────────────────────────────────────────────
def build(pdf_path, obs_rows, client_display, meta=None):
    """Write the audit PDF; returns pdf_path on success or None on failure."""
    try:
        c = rl_canvas.Canvas(pdf_path, pagesize=(PAGE_W, PAGE_H))
        intro   = [r for r in obs_rows if r.get("slide_type") == "intro"]
        ending  = [r for r in obs_rows if r.get("slide_type") == "ending"]
        finds   = [r for r in obs_rows if r.get("slide_type") not in ("intro","ending")]

        total_pages = (1 if intro else 0) + len(finds) + \
                      (1 if resolve_plan((meta or {}).get("plan")) in PLAN_TIERS else 0) + \
                      (1 if ending else 0)
        page_no = 0

        if intro:
            page_no += 1
            _draw_intro(c, intro[0], client_display)
            c.showPage()
        for r in finds:
            page_no += 1
            _draw_finding(c, r, page_no, total_pages, client_display)
            c.showPage()
        pt = resolve_plan((meta or {}).get("plan"))
        if pt in PLAN_TIERS:
            page_no += 1
            _draw_impact(c, pt, client_display)
            c.showPage()
        if ending:
            page_no += 1
            _draw_ending(c, ending[0], client_display)
            c.showPage()

        c.save()
        return pdf_path
    except Exception:
        import traceback as _tb
        print(f"[pdf] error: {_tb.format_exc()[:1500]}")
        return None
