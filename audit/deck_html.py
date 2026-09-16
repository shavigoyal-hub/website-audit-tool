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


def _fmt_leading_num(num_str):
    """Clean a stat string. Old sheets have '-0.12' where a % is meant.
      '-0.12'  -> '-12%'
      '0.544'  -> '54%'
      '-12%'   -> '-12%'
      '+32.3%' -> '+32.3%'
    Also trims trailing '.0' or '.X0' from percentages.
    """
    import re
    s = (num_str or "").strip()
    if s.endswith("%"):
        core = s[:-1]
        sign = ""
        if core.startswith("+"):
            sign = "+"; core = core[1:]
        elif core.startswith("-"):
            sign = "-"; core = core[1:]
        try:
            f = float(core)
            if f == int(f):
                core = str(int(f))
            else:
                core = f"{f:.1f}".rstrip("0").rstrip(".")
        except ValueError:
            pass
        return sign + core + "%"
    m = re.fullmatch(r"([+\-]?)(\d+(?:\.\d+)?)", s)
    if not m:
        return s
    sign, num = m.group(1), m.group(2)
    try:
        f = float(num)
    except ValueError:
        return s
    if abs(f) < 1 and "." in num:
        pct = f * 100
        if pct == int(pct):
            return f"{sign}{int(abs(pct))}%"
        return f"{sign}{abs(pct):.1f}".rstrip("0").rstrip(".") + "%"
    return s


def _fmt_hook_ctx(ctx, hook_stat):
    """Return HTML with any leading number in `ctx` wrapped in <span class='blue'>."""
    import re
    if not ctx:
        return ""
    m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?)(\s+.*)$", ctx)
    if m:
        num_clean = _fmt_leading_num(m.group(1))
        return f"<span class='blue'>{_html.escape(num_clean)}</span>{_html.escape(m.group(2))}"
    return _html.escape(ctx)


def _split_lines(cell):
    return [l.strip() for l in (cell or "").split("\n") if l.strip()]


def _domain_from(client_display):
    """Best-effort site domain, e.g. 'Gushwork' -> 'gushwork.ai'."""
    d = (client_display or "").strip().lower()
    if not d: return ""
    if "." in d: return d
    return d.replace(" ", "") + ".ai" if d == "gushwork" else d + ".com"


def _parse_formula_terms(formula):
    """Split '+5.8% Meta descriptions × +25% Structured data = +33% More leads'
    into a list of (kind, text) tuples:
        ('num', '+5.8%'), ('label', 'Meta descriptions'), ('op', '×'),
        ('num', '+25%'), ('label', 'Structured data'), ('op', '='),
        ('num', '+33%'), ('label', 'More leads').
    """
    import re
    if not formula:
        return []
    # Split on × or = (with surrounding spaces)
    parts = re.split(r'\s*([×=])\s*', formula)
    terms = []
    for i, p in enumerate(parts):
        p = p.strip()
        if not p: continue
        if p in ('×', '='):
            terms.append(('op', p))
        else:
            m = re.match(r'^([+\-]?\d+(?:\.\d+)?%?)\s+(.+)$', p)
            if m:
                terms.append(('term', m.group(1), m.group(2)))
            else:
                terms.append(('term', '', p))
    return terms


def _render_intro(row, client_display):
    hook_stat = row.get("hook_stat") or "+33%"
    hook_ctx  = row.get("hook_ctx") or "Increase your leads"
    subtitle  = row.get("observation") or "Same pages. Same website."
    formula   = row.get("found") or ""
    example   = row.get("costs") or ""

    # Intro headline: number stays BLACK (matches PDF).
    heading_html = _html.escape(hook_ctx)

    # Formula: stacked with big blue numbers and grey labels
    formula_html = ""
    for t in _parse_formula_terms(formula):
        if t[0] == 'op':
            formula_html += f"<div class='formula-op'>{_html.escape(t[1])}</div>"
        else:
            num, label = t[1], t[2]
            formula_html += (
                f"<div class='formula-term'>"
                f"<div class='formula-num'>{_html.escape(num)}</div>"
                f"<div class='formula-label'>{_html.escape(label)}</div>"
                f"</div>"
            )

    # Example: split at "→ N leads" — pull out the blue "N → N leads" phrase.
    import re
    ex_html = ""
    m = re.match(r'^(.*?)\s*(\d+\s+leads\s*[→\-→>]+\s*\d+\s+leads)\.?\s*(.*)$', example)
    if m:
        lead, blue_bit, tail = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        ex_html = (
            f"<div class='intro-example-lead'>{_html.escape(lead) or 'If you get 10 leads a month today'}</div>"
            f"<div class='intro-example-big'>{_html.escape(blue_bit)}</div>"
            f"<div class='intro-example-tail'>{_html.escape(tail) or 'With the same pages and website. Before any ranking gains.'}</div>"
        )
    else:
        ex_html = f"<div class='intro-example-lead'>{_html.escape(example)}</div>"

    site_domain = _domain_from(client_display)
    return f"""
    <section class="page intro">
      <div class="head-line">Gushwork Website audit · {_html.escape(site_domain or client_display)}</div>
      <div class="intro-hero">
        <div class="hero-heading">{heading_html}</div>
        <div class="hero-sub">{_html.escape(subtitle)}</div>
      </div>
      <div class="intro-formula">{formula_html}</div>
      <div class="intro-example">{ex_html}</div>
      <div class="intro-footer">
        <div class="foot-col"><div class="foot-label">Site audited</div><div class="foot-val">{_html.escape(site_domain or client_display)}</div></div>
        <div class="foot-col right"><div class="foot-label">Prepared by</div><div class="foot-val">Gushwork</div></div>
      </div>
    </section>
    """


def _split_headline(ctx):
    """Return (headline_html_dark, rest_html_muted) — the first sentence
    (up to the first period) stays dark, the remainder is muted grey.
    """
    if not ctx: return "", ""
    idx = ctx.find(".")
    if idx == -1:
        return _html.escape(ctx), ""
    headline = ctx[:idx + 1]
    rest     = ctx[idx + 1:].lstrip()
    return _html.escape(headline), _html.escape(rest)


def _render_finding(row, page_no, total_pages, client_display):
    category = row.get("category", "")
    priority = row.get("priority", "")
    hook_stat = row.get("hook_stat", "")
    hook_ctx  = row.get("hook_ctx", "")
    costs     = row.get("costs", "")
    support   = row.get("support", "")

    # Strip the duplicated leading number from hook_ctx if it repeats hook_stat.
    if hook_stat and hook_ctx.startswith(hook_stat):
        hook_ctx = hook_ctx[len(hook_stat):].lstrip()

    # URL rows with pills. Skip generic "- Issue" rows.
    rows_html = []
    for entry in _split_lines(row.get("found", ""))[:6]:
        if entry.strip() == "-" or entry.strip().startswith("- |"):
            continue
        if " | " in entry:
            url, label = entry.split(" | ", 1)
        else:
            url, label = entry, ""
        if not url.strip(): continue
        pcls = _pill_class(label or "Issue")
        rows_html.append(
            f"<li><span class='wf-url'>{_html.escape(url)}</span>"
            f"<span class='pill {pcls}'>{_html.escape(label or 'Issue')}</span></li>"
        )

    # Supporting stat split
    sup_html = ""
    if support:
        import re
        m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?)\s*(.*)$", support)
        if m and m.group(1):
            num_clean = _fmt_leading_num(m.group(1))
            sup_html = (f"<div class='sup-num'>{_html.escape(num_clean)}</div>"
                        f"<div class='sup-rest'>{_html.escape(m.group(2))}</div>")
        else:
            sup_html = f"<div class='sup-rest'>{_html.escape(support)}</div>"

    # Empty stat → don't show a placeholder; keep the hero-stat column empty
    # and let the hook context fill the width.
    hook_stat_clean = _fmt_leading_num(hook_stat) if hook_stat else ""
    stat_cls = "hero-stat"
    if hook_stat_clean.startswith("0"):
        stat_cls += " zero"

    # hook_ctx: first sentence dark, rest muted
    hl, rest = _split_headline(hook_ctx)
    ctx_html = f"<span class='headline'>{hl}</span>"
    if rest:
        ctx_html += f" {rest}"

    prio_chip = ""
    if priority:
        prio_chip = (f"<span class='chip {_priority_class(priority)}'>"
                     f"<span class='dot'></span>{_html.escape(priority)}</span>")

    stat_block = (f"<div class='{stat_cls}'>{_html.escape(hook_stat_clean)}</div>"
                  if hook_stat_clean else "")

    site_domain = _domain_from(client_display)
    return f"""
    <section class="page finding">
      <div class="head-row">
        <div class="head-line">Finding · {_html.escape(category)}</div>
        <div class="head-right">{prio_chip}</div>
      </div>
      <div class="hero">
        {stat_block}
        <div class="hero-ctx">{ctx_html}</div>
      </div>
      <div class="cards">
        <div class="card card-wf">
          <div class="card-head">
            <div class="card-label">What we found</div>
            <div class="card-label right">{_html.escape(category)}</div>
          </div>
          <ul class="wf-list">{"".join(rows_html) or "<li><span class='wf-url'>Site-wide</span><span class='pill pill-amber'>Issue</span></li>"}</ul>
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
        <div>{_html.escape(site_domain or client_display)} · Website audit</div>
        <div class="brand">Gushwork</div>
        <div>{page_no:02d} / {total_pages:02d}</div>
      </div>
    </section>
    """


def _render_ending(row, client_display):
    ctx  = row.get("hook_ctx") or "Approve the audit fixes."
    cta  = row.get("costs") or "Approve the audit fixes"
    cta  = cta.rstrip(".")   # button label — no trailing period
    site_domain = _domain_from(client_display)
    # Ending headline pattern: first sentence dark, rest of ctx as muted subline
    hl, rest = _split_headline(ctx)
    # Within the headline, highlight the leading number phrase in blue
    import re
    m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?\s+(?:extra\s+)?(?:\w+\s+){0,4}(?:leads|traffic|clicks|rankings|conversions))\b(.*)$",
                 ctx, re.IGNORECASE)
    if m:
        hero_html = (f"<span class='blue'>{_html.escape(m.group(1))}</span>"
                     f"<span class='headline'>{_html.escape(m.group(2))}</span>")
    else:
        hero_html = f"<span class='headline'>{hl}</span>"

    header_label = site_domain or client_display
    header_line = ("Gushwork" if header_label.lower().startswith("gushwork")
                   else f"Gushwork · {header_label}")
    subline = (rest or
               "The searchers are already there. Let's make sure they land with you.")
    return f"""
    <section class="page ending">
      <div class="head-line">{_html.escape(header_line)}</div>
      <div class="ending-hero">{hero_html}</div>
      <div class="ending-sub">{_html.escape(subline)}</div>
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
  --red:  #d63b3b;
  --text: #0b0b0f;
  --muted: #6b7280;
  --sep: #e5e7eb;
  --white: #ffffff;
}
@page { size: 13.33in 7.5in; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  background: #eef0f4;
  font-family: 'Instrument Sans', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  color: var(--text);
  font-weight: 400;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
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

/* Small grey header row — regular weight, not bold. */
.head-line { font-size: 11pt; font-weight: 500; color: var(--muted); letter-spacing: -0.005em; }
.blue { color: var(--blue); }
.red  { color: var(--red); }

/* ── Intro — LEFT aligned, black stat inline ────────────────────────── */
.intro-hero { margin: 60px 0 18px; text-align: left; }
.hero-heading {
  font-size: 68pt; font-weight: 700; line-height: 1.02; letter-spacing: -0.035em;
  color: var(--text); max-width: 11.5in;
}
.hero-heading .stat-inline { color: var(--text); }  /* number stays black in PDF */
.hero-sub {
  font-size: 22pt; color: var(--muted); margin-top: 14px;
  font-weight: 500; letter-spacing: -0.01em;
}
.intro-formula {
  margin-top: 46px;
  display: flex; align-items: baseline; gap: 22px; flex-wrap: wrap;
}
.formula-term { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.formula-num { font-size: 32pt; font-weight: 700; color: var(--blue); line-height: 1; letter-spacing: -0.02em; }
.formula-label { font-size: 12pt; color: var(--muted); font-weight: 500; }
.formula-op { font-size: 26pt; color: var(--muted); font-weight: 500; padding-bottom: 18px; }
.intro-example { margin-top: 46px; }
.intro-example-lead { font-size: 14pt; color: var(--muted); }
.intro-example-big {
  font-size: 34pt; font-weight: 700; color: var(--blue); letter-spacing: -0.02em; line-height: 1.1;
  margin-top: 4px;
}
.intro-example-tail { font-size: 14pt; color: var(--muted); margin-top: 8px; }
.intro-footer {
  position: absolute; bottom: 0.55in; left: 0.85in; right: 0.85in;
  display: flex; justify-content: space-between;
  border-top: 1px solid var(--sep); padding-top: 14px;
}
.foot-col.right { text-align: right; }
.foot-label { font-size: 9pt; color: var(--muted); margin-bottom: 4px; font-weight: 500; }
.foot-val { font-size: 12pt; font-weight: 600; color: var(--text); }

/* ── Finding page ───────────────────────────────────────────────────── */
.head-row { display: flex; justify-content: space-between; align-items: center; }
.head-right { display: flex; gap: 8px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 6px;
  font-size: 10pt; font-weight: 600; line-height: 1;
  background: transparent;
  border: 1px solid;
}
.chip .dot { width: 7px; height: 7px; border-radius: 50%; }
.chip-critical { color: #b91c1c; border-color: #f5b6b6; } .chip-critical .dot { background: #dc2626; }
.chip-high     { color: #c2410c; border-color: #fbd0a5; } .chip-high     .dot { background: #f97316; }
.chip-medium   { color: #6b7280; border-color: #d1d5db; } .chip-medium   .dot { background: #9ca3af; }
.chip-low      { color: #2563eb; border-color: #bfdbfe; } .chip-low      .dot { background: #3b82f6; }

.hero {
  display: flex; align-items: flex-start; gap: 40px;
  margin: 34px 0 30px;
}
.hero-stat {
  font-size: 116pt; font-weight: 700; color: var(--blue);
  line-height: 0.95; letter-spacing: -0.045em;
}
.hero-stat.zero { color: var(--red); }
.hero-ctx  {
  font-size: 26pt; font-weight: 600; line-height: 1.2; flex: 1;
  letter-spacing: -0.018em; padding-top: 18px;
  color: var(--muted);       /* grey secondary — matches PDF */
}
.hero-ctx .headline { color: var(--text); }   /* first sentence in dark */

.cards { display: flex; gap: 20px; }
/* WHITE card with thin grey border and smaller radius */
.card {
  background: var(--white);
  border: 1px solid var(--sep);
  border-radius: 10px;
  padding: 22px 24px;
}
.card-wf { flex: 1.25; min-height: 3in; }
.card-col { flex: 1; display: flex; flex-direction: column; gap: 16px; }
.card-head { display: flex; justify-content: space-between; margin-bottom: 10px; }
.card-label {
  font-size: 10pt; font-weight: 500; color: var(--muted); letter-spacing: 0;
}
.card-body {
  font-size: 14pt; font-weight: 500; line-height: 1.4;
  color: var(--text);
}
.wf-list { list-style: none; }
.wf-list li {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 0; border-top: 1px solid var(--sep);
}
.wf-list li:first-child { border-top: 0; }
.wf-url {
  font-size: 11pt; color: var(--text); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; padding-right: 16px;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, monospace;
  font-weight: 400;
}
/* Bordered pills, small radius (~6px) — matches PDF */
.pill {
  display: inline-block; padding: 3px 10px; border-radius: 6px;
  font-size: 9pt; font-weight: 600; white-space: nowrap;
  background: transparent; border: 1px solid;
}
.pill-red   { background: #fdecec; color: #b91c1c; border-color: #f5b6b6; }
.pill-amber { background: #fef5e2; color: #b45309; border-color: #fbd08a; }
.pill-green { background: #e8f7ec; color: #166534; border-color: #a7d9b3; }

.card-sup { display: flex; align-items: baseline; gap: 18px; }
.sup-num  {
  font-size: 40pt; font-weight: 700; color: var(--blue); line-height: 1;
  letter-spacing: -0.03em;
}
.sup-rest {
  font-size: 12pt; font-weight: 500; line-height: 1.35;
  color: var(--muted);
}
/* Footer bar with hairline top border */
.footer {
  position: absolute; bottom: 0.42in; left: 0.85in; right: 0.85in;
  display: flex; justify-content: space-between; align-items: center;
  padding-top: 12px; border-top: 1px solid var(--sep);
  font-size: 9pt; color: var(--muted); font-weight: 500;
}
.footer .brand { text-align: center; flex: 1; font-weight: 600; color: var(--text); }

/* ── Ending — left aligned, blue inline, subline, button CTA ────────── */
.ending-hero {
  position: absolute; top: 1.4in; left: 0.85in; right: 0.85in;
  font-size: 44pt; font-weight: 700; line-height: 1.15;
  letter-spacing: -0.025em; color: var(--muted);
  max-width: 11in;
}
.ending-hero .headline { color: var(--text); }
.ending-sub {
  position: absolute; top: 4.4in; left: 0.85in;
  font-size: 16pt; color: var(--muted); font-weight: 500;
  max-width: 10.5in; line-height: 1.4;
}
.ending-cta {
  position: absolute; bottom: 1.2in; left: 0.85in;
  display: inline-block; padding: 14px 26px; border-radius: 8px;
  background: var(--text); color: var(--white);
  font-size: 15pt; font-weight: 600; letter-spacing: -0.005em;
}

/* ── Impact ─────────────────────────────────────────────────────────── */
.impact-title {
  margin-top: 40px; font-size: 26pt; font-weight: 700; letter-spacing: -0.02em;
  color: var(--text);
}
.impact-rows { margin-top: 42px; }
.impact-row {
  display: flex; align-items: center; gap: 20px;
  padding: 14px 0; border-bottom: 1px solid var(--sep);
}
.impact-row .label { font-size: 14pt; color: var(--muted); width: 160px; font-weight: 500; }
.impact-row .num   { font-size: 28pt; font-weight: 700; width: 130px; letter-spacing: -0.02em; }
.impact-row .per   { font-size: 13pt; font-weight: 500; color: var(--muted); }
.impact-foot {
  position: absolute; bottom: 0.6in; left: 0.85in; right: 0.85in;
  font-size: 12pt; color: var(--muted); font-weight: 500;
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
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400;0,500;0,600;0,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="deck">
{''.join(parts)}
</div>
</body>
</html>
"""
