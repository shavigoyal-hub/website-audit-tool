"""Build the tech-audit PDF directly with reportlab — no Slides intermediate.

Layout mirrors the Arizona Home Grants reference PDF: 16:9 landscape,
one page per row, big blue stat, colored priority chip, 'What we found'
list with per-URL status pills, 'What it costs you' + supporting-stat cards.
"""
import os
import re

from reportlab.lib.colors import Color, HexColor
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader

from audit.hook_copy import STATUS_LABEL
from audit.version import PLAN_TIERS, resolve_plan

# 16:9 landscape @ 96 DPI equivalent (10in × 5.625in)
PAGE_W = 10 * 72
PAGE_H = 5.625 * 72

# Colors (approximating the reference PDF)
BLUE     = HexColor("#0e59fa")
TEXT     = HexColor("#101014")
MUTED    = HexColor("#6a7280")
CARD_BG  = HexColor("#f4f4f8")
PRIO = {
    "Critical": {"fg": HexColor("#dc2626"), "bg": HexColor("#fee2e2")},
    "High":     {"fg": HexColor("#ea580c"), "bg": HexColor("#ffedd5")},
    "Medium":   {"fg": HexColor("#d97706"), "bg": HexColor("#fef3c7")},
    "Low":      {"fg": HexColor("#2563eb"), "bg": HexColor("#dbeafe")},
}
STATUS = {
    "critical": {"fg": HexColor("#b91c1c"), "bg": HexColor("#fecaca")},
    "high":     {"fg": HexColor("#c2410c"), "bg": HexColor("#fed7aa")},
    "medium":   {"fg": HexColor("#b45309"), "bg": HexColor("#fde68a")},
    "low":      {"fg": HexColor("#1d4ed8"), "bg": HexColor("#bfdbfe")},
    "ok":       {"fg": HexColor("#166534"), "bg": HexColor("#bbf7d0")},
}


def _in(inches): return inches * 72   # 1 inch = 72 points


def _wrap(c, text, font, size, max_w):
    """Word-wrap text to fit max_w. Returns list of lines."""
    if not text:
        return []
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if c.stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur: lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _pill(c, x, y, text, font, size, fg, bg, pad_x=6, pad_y=3, radius=6):
    """Draw a rounded rectangle 'pill' and return its width."""
    text_w = c.stringWidth(text, font, size)
    w = text_w + pad_x * 2
    h = size + pad_y * 2
    c.setFillColor(bg)
    c.setStrokeColor(bg)
    c.roundRect(x, y, w, h, radius, stroke=1, fill=1)
    c.setFillColor(fg)
    c.setFont(font, size)
    c.drawString(x + pad_x, y + pad_y + 1, text)
    return w


def _status_for(row):
    """Choose a (label, colorname) for the per-URL status pill.

    Tries to map from the finding category (or key if present) to
    STATUS_LABEL. Falls back to ('Issue', priority-based colour).
    """
    cat = (row.get("category") or "").lower()
    prio = row.get("priority", "")
    for key, (label, color) in STATUS_LABEL.items():
        if key.replace("_", " ") in cat or label.lower() in cat:
            return label, color
    prio_color = {"Critical": "critical", "High": "high",
                  "Medium": "medium", "Low": "low"}.get(prio, "medium")
    return "Issue", prio_color


def _split_stat(text):
    """Pull off a leading number like '67%' or '4' from `text`."""
    if not text: return None, ""
    m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?\s*%?)\s*(.*)$", text)
    if m and m.group(1):
        return m.group(1).strip(), m.group(2).strip()
    return None, text.strip()


# ── Slide-drawing primitives ───────────────────────────────────────────────
def _draw_intro(c, row, client_display):
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # Header
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(MUTED)
    c.drawString(_in(0.5), PAGE_H - _in(0.55),
                 f"Gushwork Website Audit · {client_display}")
    # Big blue stat
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 64)
    stat = row.get("hook_stat", "+33%")
    c.drawString(_in(0.5), PAGE_H - _in(2.0), stat)
    # Hook context bold black
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 22)
    for i, ln in enumerate(_wrap(c, row.get("hook_ctx", ""),
                                 "Helvetica-Bold", 22, _in(9.0))):
        c.drawString(_in(0.5), PAGE_H - _in(2.8) - i * 26, ln)
    # Formula muted
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 12)
    for i, ln in enumerate(_wrap(c, row.get("found", ""),
                                 "Helvetica", 12, _in(9.0))):
        c.drawString(_in(0.5), PAGE_H - _in(3.7) - i * 16, ln)
    # Cost line bold
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 15)
    for i, ln in enumerate(_wrap(c, row.get("costs", ""),
                                 "Helvetica-Bold", 15, _in(9.0))):
        c.drawString(_in(0.5), PAGE_H - _in(4.5) - i * 20, ln)


def _draw_finding(c, row):
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # Header
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(MUTED)
    c.drawString(_in(0.4), PAGE_H - _in(0.5),
                 f"Finding · {row.get('category','')}")
    # Priority chip (right)
    prio = row.get("priority", "")
    if prio in PRIO:
        _pill(c, _in(9.0) - c.stringWidth(prio, "Helvetica-Bold", 10) - 40,
              PAGE_H - _in(0.62),
              prio, "Helvetica-Bold", 10,
              PRIO[prio]["fg"], PRIO[prio]["bg"])

    # Big blue stat (left)
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 60)
    stat = row.get("hook_stat", "")
    c.drawString(_in(0.4), PAGE_H - _in(1.9), stat)

    # Hook context bold black (right of stat, wraps)
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 18)
    for i, ln in enumerate(_wrap(c, row.get("hook_ctx", ""),
                                 "Helvetica-Bold", 18, _in(5.0))):
        c.drawString(_in(4.6), PAGE_H - _in(1.35) - i * 22, ln)

    # LEFT CARD — What we found
    c.setFillColor(CARD_BG)
    c.setStrokeColor(CARD_BG)
    c.roundRect(_in(0.4), _in(0.35), _in(5.4), _in(2.6), 8, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(MUTED)
    c.drawString(_in(0.6), _in(2.65), "What we found")
    cat_text = row.get("category", "")
    c.drawRightString(_in(5.6), _in(2.65), cat_text)

    # URL rows with status pills
    urls = [u.strip() for u in (row.get("found", "") or "").split("\n") if u.strip()][:6]
    status_label, status_color = _status_for(row)
    st = STATUS.get(status_color, STATUS["medium"])
    for i, u in enumerate(urls):
        y = _in(2.25) - i * _in(0.32)
        # subtle row separator
        if i > 0:
            c.setStrokeColorRGB(0.9, 0.9, 0.93)
            c.setLineWidth(0.5)
            c.line(_in(0.6), y + _in(0.28), _in(5.6), y + _in(0.28))
        c.setFillColor(TEXT)
        c.setFont("Helvetica", 10)
        # trim URL if too long
        max_w = _in(3.5)
        line = u
        while c.stringWidth(line, "Helvetica", 10) > max_w and len(line) > 20:
            line = line[:-2]
        if line != u: line = line + "…"
        c.drawString(_in(0.6), y, line)
        # pill
        _pill(c, _in(4.3), y - 2, status_label, "Helvetica-Bold", 8,
              st["fg"], st["bg"], pad_x=6, pad_y=2, radius=5)

    # RIGHT CARD — What it costs you
    c.setFillColor(CARD_BG)
    c.setStrokeColor(CARD_BG)
    c.roundRect(_in(6.0), _in(1.65), _in(3.6), _in(1.3), 8, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(MUTED)
    c.drawString(_in(6.2), _in(2.65), "What it costs you")
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 12)
    for i, ln in enumerate(_wrap(c, row.get("costs", ""),
                                 "Helvetica-Bold", 12, _in(3.3))):
        c.drawString(_in(6.2), _in(2.35) - i * 15, ln)

    # SUPPORTING CARD
    if row.get("support"):
        c.setFillColor(CARD_BG)
        c.setStrokeColor(CARD_BG)
        c.roundRect(_in(6.0), _in(0.35), _in(3.6), _in(1.2), 8, stroke=1, fill=1)
        pct, rest = _split_stat(row["support"])
        if pct:
            c.setFillColor(BLUE)
            c.setFont("Helvetica-Bold", 30)
            c.drawString(_in(6.2), _in(1.05), pct)
            c.setFillColor(TEXT)
            c.setFont("Helvetica-Bold", 11)
            for i, ln in enumerate(_wrap(c, rest,
                                         "Helvetica-Bold", 11, _in(3.3))):
                c.drawString(_in(6.2), _in(0.75) - i * 13, ln)
        else:
            c.setFillColor(TEXT)
            c.setFont("Helvetica-Bold", 12)
            for i, ln in enumerate(_wrap(c, row["support"],
                                         "Helvetica-Bold", 12, _in(3.3))):
                c.drawString(_in(6.2), _in(1.2) - i * 15, ln)


def _draw_ending(c, row, client_display):
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(MUTED)
    c.drawString(_in(0.5), PAGE_H - _in(0.55), f"Gushwork · {client_display}")
    ctx = row.get("hook_ctx") or "Approve the audit fixes."
    pct, rest = _split_stat(ctx)
    if pct:
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", 60)
        c.drawString(_in(0.5), PAGE_H - _in(2.0), pct)
        c.setFillColor(TEXT)
        c.setFont("Helvetica-Bold", 22)
        for i, ln in enumerate(_wrap(c, rest, "Helvetica-Bold", 22, _in(9.0))):
            c.drawString(_in(0.5), PAGE_H - _in(2.8) - i * 26, ln)
    else:
        c.setFillColor(TEXT)
        c.setFont("Helvetica-Bold", 28)
        for i, ln in enumerate(_wrap(c, ctx, "Helvetica-Bold", 28, _in(9.0))):
            c.drawString(_in(0.5), PAGE_H - _in(2.4) - i * 32, ln)
    # CTA muted bottom
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 18)
    for i, ln in enumerate(_wrap(c, row.get("costs", ""),
                                 "Helvetica-Bold", 18, _in(9.0))):
        c.drawString(_in(0.5), _in(0.8) - i * 22, ln)


def _draw_impact(c, plan_tier):
    tier = PLAN_TIERS[plan_tier]
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(MUTED)
    c.drawString(_in(0.5), PAGE_H - _in(0.55), "Projected Impact")
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(_in(0.5), PAGE_H - _in(1.2),
                 f"Expected leads on the ${plan_tier} / month plan")
    c.setFont("Helvetica", 14)
    y = PAGE_H - _in(2.0)
    for label, val in [("Month 3-4", tier["M3-4"]),
                       ("Month 6-7", tier["M6-7"]),
                       ("Month 9-10", tier["M9-10"])]:
        c.drawString(_in(0.7), y, f"{label}:")
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(_in(2.2), y, f"{val} leads / month")
        c.setFillColor(TEXT)
        c.setFont("Helvetica", 14)
        y -= _in(0.5)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 12)
    c.drawString(_in(0.5), _in(0.6),
                 "Cost per lead expected to drop ~5% vs current spend.")


# ── Public API ────────────────────────────────────────────────────────────
def build(pdf_path, obs_rows, client_display, meta=None):
    """Write the audit PDF. Returns pdf_path or None on failure."""
    try:
        c = rl_canvas.Canvas(pdf_path, pagesize=(PAGE_W, PAGE_H))
        # Split rows
        intro   = [r for r in obs_rows if r.get("slide_type") == "intro"]
        ending  = [r for r in obs_rows if r.get("slide_type") == "ending"]
        finds   = [r for r in obs_rows if r.get("slide_type") not in ("intro","ending")]

        # Intro
        if intro:
            _draw_intro(c, intro[0], client_display); c.showPage()
        # Findings, in row order
        for r in finds:
            _draw_finding(c, r); c.showPage()
        # Impact
        pt = resolve_plan((meta or {}).get("plan"))
        if pt and pt in PLAN_TIERS:
            _draw_impact(c, pt); c.showPage()
        # Ending
        if ending:
            _draw_ending(c, ending[0], client_display); c.showPage()

        c.save()
        return pdf_path
    except Exception as exc:
        import traceback as _tb
        print(f"[pdf] error: {_tb.format_exc()[:1200]}")
        return None
