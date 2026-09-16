"""Server-side rendered HTML deck that mirrors the Arizona Home Grants
reference PDF as closely as browsers allow.

Users open the URL in a browser (Inter font via Google Fonts, full CSS
control), and Print → Save as PDF gives the exact designed result. No
reportlab, no Slides — pure HTML/CSS with a landscape @page rule.
"""
import html as _html

from audit.hook_copy import STATUS_LABEL


# ── Status pill palette based on label wording ────────────────────────────
def _pill_class(label):
    low = (label or "").lower()
    if any(k in low for k in ("no ", "missing", "404", "5xx", "noindex",
                              "render error", "critical", "cls high",
                              "lcp >", "perf <", "error")):
        return "pill-red"
    if any(k in low for k in ("competing", "duplicate", "long", "truncated",
                              "stuffed", "medium", "heavy", "blocking",
                              "wrong", "few", "over-length", "js-only",
                              "warning")):
        return "pill-amber"
    if any(k in low for k in ("ok", "1 h1", "single", "good", "passed", "single h1")):
        return "pill-green"
    return "pill-amber"


def _priority_class(p):
    return {
        "Critical": "chip-critical",
        "High":     "chip-high",
        "Medium":   "chip-medium",
        "Low":      "chip-low",
    }.get(p or "", "chip-medium")


def _fmt_hook_ctx(ctx, hook_stat):
    """Return HTML with any leading number in `ctx` wrapped in <span class='blue'>."""
    import re
    if not ctx:
        return ""
    ctx_esc = _html.escape(ctx)
    m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?)(\s+.*)$", ctx_esc)
    if m:
        return f"<span class='blue'>{m.group(1)}</span>{m.group(2)}"
    return ctx_esc


def _split_lines(cell):
    return [l.strip() for l in (cell or "").split("\n") if l.strip()]


def _render_intro(row, client_display):
    hook_stat = row.get("hook_stat") or "+33%"
    hook_ctx  = row.get("hook_ctx") or "Increase your leads"
    subtitle  = row.get("observation") or "Same pages. Same website."
    formula   = row.get("found") or ""
    example   = row.get("costs") or ""

    # Try to color-highlight the stat portion inline
    ctx_html = _html.escape(hook_ctx)
    if hook_stat and hook_stat in hook_ctx:
        parts = hook_ctx.split(hook_stat, 1)
        ctx_html = (_html.escape(parts[0])
                    + f"<span class='blue'>{_html.escape(hook_stat)}</span>"
                    + _html.escape(parts[1] if len(parts) > 1 else ""))

    return f"""
    <section class="page intro">
      <div class="head-line">Gushwork Website audit · {_html.escape(client_display)}</div>
      <div class="intro-hero">
        <div class="hero-heading">{ctx_html}</div>
        <div class="hero-sub">{_html.escape(subtitle)}</div>
      </div>
      <div class="intro-formula">{_html.escape(formula)}</div>
      <div class="intro-example">{_html.escape(example)}</div>
      <div class="intro-footer">
        <div class="foot-col"><div class="foot-label">Site audited</div><div class="foot-val">{_html.escape(client_display)}</div></div>
        <div class="foot-col right"><div class="foot-label">Prepared by</div><div class="foot-val">Gushwork</div></div>
      </div>
    </section>
    """


def _render_finding(row, page_no, total_pages, client_display):
    category = row.get("category", "")
    priority = row.get("priority", "")
    hook_stat = row.get("hook_stat", "")
    hook_ctx  = row.get("hook_ctx", "")
    costs     = row.get("costs", "")
    support   = row.get("support", "")

    # URL rows with pills
    rows_html = []
    for entry in _split_lines(row.get("found", ""))[:6]:
        if " | " in entry:
            url, label = entry.split(" | ", 1)
        else:
            url, label = entry, "Issue"
        pcls = _pill_class(label)
        rows_html.append(
            f"<li><span class='wf-url'>{_html.escape(url)}</span>"
            f"<span class='pill {pcls}'>{_html.escape(label)}</span></li>"
        )

    # Supporting stat split
    sup_html = ""
    if support:
        import re
        m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?)\s*(.*)$", support)
        if m and m.group(1):
            sup_html = (f"<div class='sup-num'>{_html.escape(m.group(1))}</div>"
                        f"<div class='sup-rest'>{_html.escape(m.group(2))}</div>")
        else:
            sup_html = f"<div class='sup-rest'>{_html.escape(support)}</div>"

    prio_chip = ""
    if priority:
        prio_chip = (f"<span class='chip {_priority_class(priority)}'>"
                     f"<span class='dot'></span>{_html.escape(priority)}</span>")

    return f"""
    <section class="page finding">
      <div class="head-row">
        <div class="head-line">Finding · {_html.escape(category)}</div>
        <div class="head-right">{prio_chip}</div>
      </div>
      <div class="hero">
        <div class="hero-stat">{_html.escape(hook_stat)}</div>
        <div class="hero-ctx">{_fmt_hook_ctx(hook_ctx, hook_stat)}</div>
      </div>
      <div class="cards">
        <div class="card card-wf">
          <div class="card-head">
            <div class="card-label">What we found</div>
            <div class="card-label right">{_html.escape(category)}</div>
          </div>
          <ul class="wf-list">{"".join(rows_html)}</ul>
        </div>
        <div class="card-col">
          <div class="card card-costs">
            <div class="card-label">What it costs you</div>
            <div class="card-body">{_html.escape(costs)}</div>
          </div>
          {f"<div class='card card-sup'>{sup_html}</div>" if sup_html else ""}
        </div>
      </div>
      <div class="footer">
        <div>{_html.escape(client_display)} · Website audit</div>
        <div>Gushwork &nbsp; {page_no:02d} / {total_pages:02d}</div>
      </div>
    </section>
    """


def _render_ending(row, client_display):
    ctx  = row.get("hook_ctx") or "Approve the audit fixes."
    cta  = row.get("costs") or "Approve the audit fixes."
    import re
    m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?)\s+(.*)$", ctx)
    ctx_html = _html.escape(ctx)
    if m:
        ctx_html = (f"<span class='blue'>{_html.escape(m.group(1))}</span> "
                    f"{_html.escape(m.group(2))}")
    return f"""
    <section class="page ending">
      <div class="head-line">Gushwork · {_html.escape(client_display)}</div>
      <div class="ending-hero">{ctx_html}</div>
      <div class="ending-cta">{_html.escape(cta)}</div>
    </section>
    """


def _render_impact(plan_tier, tier, client_display):
    return f"""
    <section class="page impact">
      <div class="head-line">Projected Impact</div>
      <div class="impact-title">Expected leads on the ${plan_tier} / month plan</div>
      <div class="impact-rows">
        <div class="impact-row"><span class='label'>Month 3-4</span><span class='num blue'>{tier['M3-4']}</span><span class='per'>leads / month</span></div>
        <div class="impact-row"><span class='label'>Month 6-7</span><span class='num blue'>{tier['M6-7']}</span><span class='per'>leads / month</span></div>
        <div class="impact-row"><span class='label'>Month 9-10</span><span class='num blue'>{tier['M9-10']}</span><span class='per'>leads / month</span></div>
      </div>
      <div class="impact-foot">Cost per lead expected to drop ~5% vs current spend.</div>
    </section>
    """


CSS = """
:root {
  --blue: #0057ff;
  --blue-2: #0044cc;
  --text: #0b0b0f;
  --muted: #6b7280;
  --card: #f5f5f7;
  --sep: #e5e7eb;
  --white: #ffffff;
}
@page { size: 13.33in 7.5in; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  background: #eef0f4;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  color: var(--text);
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
  font-feature-settings: "ss01","cv11";
}
.deck {
  display: flex; flex-direction: column; gap: 40px; align-items: center;
  padding: 40px 16px; min-height: 100vh;
}
.page {
  width: 13.33in; height: 7.5in;
  background: var(--white);
  position: relative;
  padding: 0.7in 0.85in;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0,0,0,0.10);
  border-radius: 6px;
}
@media print {
  html, body { background: #fff; }
  .deck { padding: 0; gap: 0; }
  .page { box-shadow: none; page-break-after: always; border-radius: 0; }
}

.head-line { font-size: 14pt; font-weight: 700; color: var(--muted); letter-spacing: -0.01em; }
.blue { color: var(--blue); }

/* Intro — centered hero, big and airy */
.intro-hero { margin: 90px 0 24px; text-align: center; }
.hero-heading {
  font-size: 76pt; font-weight: 800; line-height: 1.05; letter-spacing: -0.03em;
}
.hero-sub {
  font-size: 26pt; color: var(--muted); margin-top: 20px;
  font-weight: 500; letter-spacing: -0.01em;
}
.intro-formula {
  font-size: 20pt; font-weight: 700; text-align: center; margin-top: 44px;
  color: var(--text); letter-spacing: -0.01em;
}
.intro-example {
  font-size: 22pt; font-weight: 700; text-align: center; margin-top: 26px;
  color: var(--text); letter-spacing: -0.01em;
}
.intro-footer {
  position: absolute; bottom: 0.55in; left: 0.85in; right: 0.85in;
  display: flex; justify-content: space-between;
}
.foot-col.right { text-align: right; }
.foot-label { font-size: 10pt; color: var(--muted); margin-bottom: 6px; }
.foot-val { font-size: 15pt; font-weight: 700; }

/* Finding */
.head-row { display: flex; justify-content: space-between; align-items: center; }
.head-right { display: flex; gap: 10px; }
.chip {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 999px;
  font-size: 11pt; font-weight: 700; line-height: 1;
}
.chip .dot { width: 9px; height: 9px; border-radius: 50%; }
.chip-critical { background: #fee2e2; color: #b91c1c; } .chip-critical .dot { background: #dc2626; }
.chip-high     { background: #ffedd5; color: #c2410c; } .chip-high     .dot { background: #f97316; }
.chip-medium   { background: #fef3c7; color: #b45309; } .chip-medium   .dot { background: #f59e0b; }
.chip-low      { background: #dbeafe; color: #2563eb; } .chip-low      .dot { background: #3b82f6; }

.hero {
  display: flex; align-items: flex-start; gap: 40px;
  margin: 40px 0 34px;
}
.hero-stat {
  font-size: 132pt; font-weight: 800; color: var(--blue);
  line-height: 0.95; letter-spacing: -0.045em;
}
.hero-ctx  {
  font-size: 30pt; font-weight: 800; line-height: 1.15; flex: 1;
  letter-spacing: -0.02em; padding-top: 26px;
}

.cards { display: flex; gap: 20px; }
.card {
  background: var(--card);
  border-radius: 18px;
  padding: 24px 26px;
}
.card-wf { flex: 1.25; min-height: 3in; }
.card-col { flex: 1; display: flex; flex-direction: column; gap: 20px; }
.card-head { display: flex; justify-content: space-between; margin-bottom: 12px; }
.card-label {
  font-size: 11pt; font-weight: 700; color: var(--muted); letter-spacing: -0.01em;
}
.card-body {
  font-size: 15pt; font-weight: 700; line-height: 1.35;
  letter-spacing: -0.01em;
}
.wf-list { list-style: none; }
.wf-list li {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0; border-top: 1px solid var(--sep);
}
.wf-list li:first-child { border-top: 0; }
.wf-url {
  font-size: 12.5pt; color: var(--text); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; padding-right: 16px;
  font-family: 'Inter', 'JetBrains Mono', monospace;
}
.pill {
  display: inline-block; padding: 5px 12px; border-radius: 999px;
  font-size: 10pt; font-weight: 700; white-space: nowrap; letter-spacing: -0.01em;
}
.pill-red   { background: #fee2e2; color: #b91c1c; }
.pill-amber { background: #fef3c7; color: #b45309; }
.pill-green { background: #d1fae5; color: #065f46; }
.card-sup { display: flex; align-items: baseline; gap: 18px; }
.sup-num  {
  font-size: 46pt; font-weight: 800; color: var(--blue); line-height: 1;
  letter-spacing: -0.03em;
}
.sup-rest {
  font-size: 13pt; font-weight: 700; line-height: 1.35;
  letter-spacing: -0.01em;
}
.footer {
  position: absolute; bottom: 0.45in; left: 0.85in; right: 0.85in;
  display: flex; justify-content: space-between;
  font-size: 10pt; color: var(--muted);
}

/* Ending */
.ending-hero {
  position: absolute; top: 42%; left: 0.85in; right: 0.85in;
  transform: translateY(-50%);
  font-size: 46pt; font-weight: 800; line-height: 1.1; text-align: center;
  letter-spacing: -0.025em;
}
.ending-cta {
  position: absolute; bottom: 1.2in; left: 0; right: 0;
  text-align: center; font-size: 22pt; font-weight: 700; color: var(--muted);
  letter-spacing: -0.01em;
}

/* Impact */
.impact-title {
  margin-top: 60px; font-size: 30pt; font-weight: 800; letter-spacing: -0.02em;
}
.impact-rows { margin-top: 60px; }
.impact-row {
  display: flex; align-items: center; gap: 20px;
  padding: 16px 0; border-bottom: 1px solid var(--sep);
}
.impact-row .label { font-size: 16pt; color: var(--muted); width: 180px; }
.impact-row .num   { font-size: 32pt; font-weight: 800; width: 140px; letter-spacing: -0.02em; }
.impact-row .per   { font-size: 15pt; font-weight: 500; }
.impact-foot {
  position: absolute; bottom: 0.6in; left: 0.85in; right: 0.85in;
  font-size: 14pt; color: var(--muted);
}
"""


def render(obs_rows, client_display, meta=None):
    """Return full HTML string for the deck."""
    from audit.version import PLAN_TIERS, resolve_plan
    intro   = [r for r in obs_rows if r.get("slide_type") == "intro"]
    ending  = [r for r in obs_rows if r.get("slide_type") == "ending"]
    finds   = [r for r in obs_rows if r.get("slide_type") not in ("intro", "ending")]

    total_pages = (1 if intro else 0) + len(finds) + \
                  (1 if resolve_plan((meta or {}).get("plan")) in PLAN_TIERS else 0) + \
                  (1 if ending else 0)

    parts = []
    page_no = 0
    if intro:
        page_no += 1
        parts.append(_render_intro(intro[0], client_display))
    for r in finds:
        page_no += 1
        parts.append(_render_finding(r, page_no, total_pages, client_display))
    pt = resolve_plan((meta or {}).get("plan"))
    if pt in PLAN_TIERS:
        page_no += 1
        parts.append(_render_impact(pt, PLAN_TIERS[pt], client_display))
    if ending:
        page_no += 1
        parts.append(_render_ending(ending[0], client_display))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Gushwork Audit · {_html.escape(client_display)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="deck">
{''.join(parts)}
</div>
</body>
</html>
"""
