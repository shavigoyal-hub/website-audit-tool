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
    key = (p or "").strip().title()
    return {
        "Critical": "chip-critical",
        "High":     "chip-high",
        "Medium":   "chip-medium",
        "Low":      "chip-low",
    }.get(key, "chip-medium")


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
    # Normalize both Windows-style and Mac-classic line endings.
    text = (cell or "").replace("\r\n", "\n").replace("\r", "\n")
    return [l.strip() for l in text.split("\n") if l.strip()]


def _domain_from(client_display):
    """Return the site domain if `client_display` looks like one, else the
    label unchanged. We don't invent TLDs anymore — /build-deck extracts the
    real domain from the sheet title.
    """
    return (client_display or "").strip().lower()


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


GUSHWORK_LOGO_SVG = (
    '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="0" y="0" width="100" height="100" rx="22" fill="#1868ff"/>'
    # White "document with folded corner" outline — matches the reference.
    # Vertical left edge, horizontal top edge, diagonal from top-right down,
    # vertical right edge, horizontal bottom.
    '<path d="M28 28 L58 28 L72 42 L72 72 L28 72 Z" '
    'fill="none" stroke="#ffffff" stroke-width="5.5" '
    'stroke-linejoin="round" stroke-linecap="round"/>'
    # Small triangle indicating the folded corner at top-right
    '<path d="M58 28 L58 42 L72 42 Z" fill="#ffffff"/>'
    '</svg>'
)
BRAND_MARK = ('<span class="brand-mark">'
              f'<span class="logo">{GUSHWORK_LOGO_SVG}</span>Gushwork</span>')


def _render_intro(row, client_display):
    hook_stat = row.get("hook_stat") or "+33%"
    hook_ctx  = row.get("hook_ctx") or "Increase your leads by 33%"
    subtitle  = row.get("observation") or "Same pages. Same website."
    formula   = row.get("found") or ""
    example   = row.get("costs") or ""

    # Intro headline — highlight the stat portion in blue.
    # Strip a leading '+' from the stat when it appears inline in the heading.
    heading_html = _html.escape(hook_ctx)
    for candidate in (hook_stat, hook_stat.lstrip("+")):
        if candidate and candidate in hook_ctx:
            parts = hook_ctx.split(candidate, 1)
            heading_html = (_html.escape(parts[0])
                            + f"<span class='blue'>{_html.escape(candidate)}</span>"
                            + _html.escape(parts[1] if len(parts) > 1 else ""))
            break

    # Formula cards — last one highlighted
    terms = [t for t in _parse_formula_terms(formula)]
    total_cards = sum(1 for t in terms if t[0] == 'term')
    formula_html = ""
    card_i = 0
    for t in terms:
        if t[0] == 'op':
            formula_html += f"<div class='formula-op'>{_html.escape(t[1])}</div>"
        else:
            card_i += 1
            num, label = t[1], t[2]
            hi = " hi" if card_i == total_cards else ""
            formula_html += (
                f"<div class='formula-card{hi}'>"
                f"<div class='formula-num'>{_html.escape(num)}</div>"
                f"<div class='formula-label'>{_html.escape(label)}</div>"
                f"</div>"
            )

    # Uplift card
    import re
    lead_text = "If you get 10 leads a month today"
    tail_text = "With the same pages and website. Before any ranking gains."
    blue_bit  = "10 leads &nbsp;<span class='arrow'>→</span>&nbsp; <span class='blue'>14 leads</span>"
    m = re.match(r'^(.*?)\s*(\d+)\s+leads\s*[→\-→>]+\s*(\d+)\s+leads\.?\s*(.*)$', example)
    if m:
        if m.group(1).strip(): lead_text = m.group(1).strip()
        if m.group(4).strip(): tail_text = m.group(4).strip()
        blue_bit = (f"{_html.escape(m.group(2))} leads &nbsp;<span class='arrow'>→</span>&nbsp; "
                    f"<span class='blue'>{_html.escape(m.group(3))} leads</span>")

    site_domain = _domain_from(client_display)
    return f"""
    <section class="page intro">
      <div class="top-nav">
        {BRAND_MARK}
        <div class="domain">Website audit · <b>{_html.escape(site_domain or client_display)}</b></div>
      </div>
      <div class="intro-body">
        <div class="intro-left">
          <div class="hero-heading">{heading_html}</div>
          <div class="hero-sub">{_html.escape(subtitle)}</div>
        </div>
        <div class="intro-right">
          <div class="intro-formula">{formula_html}</div>
          <div class="uplift-card">
            <div class="uplift-lead">{_html.escape(lead_text)}</div>
            <div class="uplift-big">{blue_bit}</div>
            <div class="uplift-tail">{_html.escape(tail_text)}</div>
          </div>
        </div>
      </div>
      <div class="intro-footer">
        <div class="foot-col"><div class="foot-label">Site audited</div><div class="foot-val">{_html.escape(site_domain or client_display)}</div></div>
        <div class="foot-col right"><div class="foot-label">Prepared by</div><div class="foot-val">Gushwork</div></div>
      </div>
    </section>
    """


def _split_headline(ctx):
    """Return (headline, rest) — first sentence in dark, rest in muted.

    A sentence boundary is a period that:
      • is preceded by at least THREE word chars (not 'e.g.', not 'i.e.', not '3.14'),
      • and is followed by whitespace + [A-Z0-9] (a new sentence start),
        or end of string.
    """
    if not ctx: return "", ""
    import re as _re
    m = _re.search(r"(?<=\w{3})\.(?=\s+[A-Z0-9]|\s*$)", ctx)
    if not m:
        return _html.escape(ctx), ""
    end = m.start() + 1  # include the period
    return _html.escape(ctx[:end]), _html.escape(ctx[end:].lstrip())


def _render_finding(row, page_no, total_pages, client_display):
    category = row.get("category", "")
    priority = row.get("priority", "")
    hook_stat = row.get("hook_stat", "")
    hook_ctx  = row.get("hook_ctx", "")
    costs     = row.get("costs", "")
    support   = row.get("support", "")

    # Strip a duplicated leading number from hook_ctx. Handles the raw stat
    # ('-15%'), its Sheets-formatted variant ('-15.0%') and odd spacing
    # from Sheets ('-15. 0%').
    import re as _re
    hook_ctx = _re.sub(r"^\s*[+\-]?\d[\d.,\s]*%\s+", "", hook_ctx)

    # URL rows with pills. Render as PATH ONLY (matches reference PDF style).
    import re as _ure
    def _to_path(u):
        m = _ure.match(r"^https?://[^/]+(/.*)?$", u.strip())
        if m:
            path = m.group(1) or ""
            return "/ (homepage)" if path in ("", "/") else path
        return u.strip()

    rows_html = []
    for entry in _split_lines(row.get("found", ""))[:8]:
        stripped = entry.strip()
        if stripped in ("-", "") or stripped.startswith("- |") or stripped.startswith("-|"):
            continue
        # Split on '|' with or without spaces; whichever the sheet uses
        if "|" in stripped:
            parts = stripped.split("|", 1)
            url   = parts[0].strip()
            label = parts[1].strip()
        else:
            url, label = stripped, ""
        if not url or url == "-":
            continue
        display_url = _to_path(url)
        pcls = _pill_class(label or "Issue")
        rows_html.append(
            f"<li><span class='wf-url'>{_html.escape(display_url)}</span>"
            f"<span class='pill {pcls}'>{_html.escape(label or 'Issue')}</span></li>"
        )

    # Supporting stat — big blue number, first sentence dark bold, rest muted
    sup_html = ""
    if support:
        import re
        m = re.match(r"^\s*([+\-]?\d+(?:\.\d+)?%?)\s*(.*)$", support)
        if m and m.group(1):
            num_clean = _fmt_leading_num(m.group(1))
            rest_hl, rest_tail = _split_headline(m.group(2))
            sup_rest_html = f"<span class='headline'>{rest_hl}</span>"
            if rest_tail:
                sup_rest_html += f" {rest_tail}"
            sup_html = (f"<span class='sup-num'>{_html.escape(num_clean)}</span>"
                        f"<div class='sup-rest'>{sup_rest_html}</div>")
        else:
            sup_html = f"<div class='sup-rest'>{_html.escape(support)}</div>"

    # Empty stat → fall back to a priority-based number so the hero stays
    # visually balanced (matches the reference's every-finding-has-a-stat rule).
    if not hook_stat:
        hook_stat = {"Critical": "-25%", "High": "-15%",
                     "Medium":   "-8%",  "Low":  "-3%"}.get(priority, "!")
    hook_stat_clean = _fmt_leading_num(hook_stat)
    stat_cls = "hero-stat"
    if hook_stat_clean and (hook_stat_clean.startswith("0")
                             or hook_stat_clean.startswith("-")
                             or hook_stat_clean == "!"):
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

    stat_block = f"<div class='{stat_cls}'>{_html.escape(hook_stat_clean)}</div>"

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
        {BRAND_MARK}
        <div class="page-no">{page_no:02d} / {total_pages:02d}</div>
      </div>
    </section>
    """


def _render_ending(row, client_display):
    ctx  = row.get("hook_ctx") or "Every month you wait, you lose out on extra leads from the same pages."
    cta  = row.get("costs") or "Approve the audit fixes"
    cta  = cta.rstrip(".")
    site_domain = _domain_from(client_display)
    subtitle = row.get("observation") or "The searchers are already there. Let's make sure they land with you."

    # Highlight the "N extra leads" phrase in blue (or leading number).
    import re
    m = re.search(r"(\d+(?:\.\d+)?%?\s+(?:extra\s+)?(?:\w+\s+){0,3}(?:leads|traffic|clicks|rankings|conversions))",
                  ctx, re.IGNORECASE)
    if m:
        s, e = m.start(1), m.end(1)
        hero_html = (_html.escape(ctx[:s])
                     + f"<span class='blue'>{_html.escape(ctx[s:e])}</span>"
                     + _html.escape(ctx[e:]))
    else:
        hero_html = _html.escape(ctx)

    return f"""
    <section class="page ending">
      <div class="top-nav">
        {BRAND_MARK}
        <div class="domain"><b>{_html.escape(site_domain or client_display)}</b></div>
      </div>
      <div class="ending-body">
        <div class="ending-hero">{hero_html}</div>
        <div class="ending-sub">{_html.escape(subtitle)}</div>
        <a class="ending-cta">{_html.escape(cta)}</a>
      </div>
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
  --blue: #1868ff;
  --red:  #c8102e;
  --text: #0d1421;
  --muted: #7f8695;
  --card:  #f4f5f7;
  --card-blue: #dfeaff;
  --sep:  #e8ebee;
  --dark: #0e1526;
  --dark-2: #171e2e;
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

.blue { color: var(--blue); }
.red  { color: var(--red); }

/* Top nav header (intro + ending) — logo left, domain right */
.top-nav {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 24px;
}
.brand-mark {
  display: inline-flex; align-items: center; gap: 10px;
  font-size: 16pt; font-weight: 700; letter-spacing: -0.015em;
  color: var(--text);
}
.brand-mark .logo { width: 30px; height: 30px; display: block; }
.brand-mark .logo svg { width: 100%; height: 100%; display: block; }
.top-nav .domain {
  font-size: 12pt; color: var(--muted); font-weight: 500;
}
.top-nav .domain b {
  color: var(--text); font-weight: 700;
}
/* Small grey line for finding pages */
.head-line { font-size: 13pt; font-weight: 500; color: var(--muted); letter-spacing: -0.005em; }

/* ── Intro ──────────────────────────────────────────────────────────── */
.intro-body { display: flex; gap: 60px; align-items: flex-start; margin-top: 30px; }
.intro-left { flex: 1; }
.hero-heading {
  font-size: 66pt; font-weight: 700; line-height: 1.0; letter-spacing: -0.04em;
  color: var(--text);
}
.hero-heading .blue { color: var(--blue); }
.hero-sub {
  font-size: 17pt; color: var(--muted); margin-top: 18px;
  font-weight: 500; letter-spacing: -0.01em;
}

.intro-right { flex: 0 0 5.6in; }
.intro-formula {
  display: flex; align-items: stretch; gap: 12px; flex-wrap: nowrap;
  margin-bottom: 22px;
}
.formula-card {
  flex: 1; border: 1px solid var(--sep); border-radius: 12px;
  padding: 16px 18px; background: var(--white);
  display: flex; flex-direction: column; gap: 4px;
}
.formula-card.hi { background: var(--card-blue); border-color: #cadaff; }
.formula-num { font-size: 18pt; font-weight: 700; color: var(--blue); line-height: 1; letter-spacing: -0.02em; }
.formula-label { font-size: 9pt; color: var(--muted); font-weight: 500; }
.formula-op { display: flex; align-items: center; padding: 0 2px; color: var(--muted); font-size: 15pt; }

.uplift-card {
  border: 1px solid var(--sep); border-radius: 12px;
  padding: 18px 22px; background: var(--white);
}
.uplift-lead { font-size: 9pt; color: var(--muted); font-weight: 500; }
.uplift-big {
  font-size: 34pt; font-weight: 700; letter-spacing: -0.03em; line-height: 1;
  margin-top: 6px;
  color: var(--muted);
}
.uplift-big .blue { color: var(--blue); }
.uplift-big .arrow { color: var(--muted); padding: 0 8px; }
.uplift-tail { font-size: 10pt; color: var(--muted); font-weight: 500; margin-top: 8px; }

.intro-footer {
  position: absolute; bottom: 0.55in; left: 0.85in; right: 0.85in;
  display: flex; justify-content: space-between;
  border-top: 1px solid var(--sep); padding-top: 16px;
}
.foot-col.right { text-align: right; }
.foot-label { font-size: 10pt; color: var(--muted); margin-bottom: 4px; font-weight: 500; }
.foot-val { font-size: 14pt; font-weight: 700; color: var(--text); letter-spacing: -0.005em; }

/* ── Finding page ───────────────────────────────────────────────────── */
.head-row { display: flex; justify-content: space-between; align-items: center; }
.head-right { display: flex; gap: 8px; }
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 5px 12px; border-radius: 5px;
  font-size: 10.5pt; font-weight: 500; line-height: 1;
  background: var(--white); border: 1px solid;
}
.chip .dot { width: 7px; height: 7px; border-radius: 50%; }
.chip-critical { color: #c8102e; border-color: #f5b6b6; background: #fdecec; } .chip-critical .dot { background: #c8102e; }
.chip-high     { color: #c2410c; border-color: #fbd0a5; background: #fef5e2; } .chip-high     .dot { background: #f97316; }
.chip-medium   { color: #4b5563; border-color: #d1d5db; background: #f3f4f6; } .chip-medium   .dot { background: #6b7280; }
.chip-low      { color: #2563eb; border-color: #bfdbfe; background: #eff5ff; } .chip-low      .dot { background: #3b82f6; }

.hero {
  display: flex; align-items: flex-start; gap: 30px;
  margin: 32px 0 34px;
}
.hero-stat {
  font-size: 104pt; font-weight: 700; color: var(--blue);
  line-height: 0.9; letter-spacing: -0.055em;
  flex-shrink: 0;
}
.hero-stat.zero { color: var(--red); }
.hero-ctx  {
  font-size: 32pt; font-weight: 700; line-height: 1.08; flex: 1;
  letter-spacing: -0.028em; padding-top: 12px;
  color: var(--muted);
}
.hero-ctx .headline { color: var(--text); }

.cards { display: flex; gap: 18px; }
/* GREY-FILLED cards, larger radius, no border */
.card {
  background: var(--card);
  border-radius: 14px;
  padding: 22px 26px;
}
.card-wf { flex: 1.1; }
.card-col { flex: 1; display: flex; flex-direction: column; gap: 12px; }
.card-head { display: flex; justify-content: space-between; margin-bottom: 8px; }
.card-label {
  font-size: 11pt; font-weight: 500; color: var(--muted); letter-spacing: 0;
}
.card-body {
  font-size: 15pt; font-weight: 500; line-height: 1.4;
  color: var(--text);
}
.wf-list { list-style: none; }
.wf-list li {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0; border-top: 1px solid #e0e2e6;
}
.wf-list li:first-child { border-top: 0; padding-top: 6px; }
.wf-url {
  font-size: 12pt; color: var(--text); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; padding-right: 16px;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, monospace;
  font-weight: 400;
}
.pill {
  display: inline-block; padding: 4px 11px; border-radius: 5px;
  font-size: 10pt; font-weight: 500; white-space: nowrap;
  border: 1px solid;
}
.pill-red   { background: #fdecec; color: #c8102e; border-color: #f5b6b6; }
.pill-amber { background: #fef5e2; color: #b45309; border-color: #fbd08a; }
.pill-green { background: #eaf7ee; color: #166534; border-color: #b8dfc3; }

/* Supporting stat card — big blue number, bold dark first sentence, muted rest */
.card-sup { }
.sup-num  {
  font-size: 44pt; font-weight: 700; color: var(--blue); line-height: 1;
  letter-spacing: -0.03em; margin-bottom: 8px; display: block;
}
.sup-rest {
  font-size: 12pt; line-height: 1.4;
  color: var(--muted); font-weight: 500;
}
.sup-rest .headline { color: var(--text); font-weight: 700; }

/* Code block (robots.txt style) */
.code-block {
  background: var(--dark); color: #dfe4ee;
  border-radius: 12px; padding: 22px 26px;
  font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace;
  font-size: 12pt; line-height: 1.5;
  white-space: pre; overflow: hidden;
}
.code-below { margin-top: 12px; font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; font-size: 11pt; color: var(--text); }

/* Footer bar — hairline + centered brand */
.footer {
  position: absolute; bottom: 0.42in; left: 0.85in; right: 0.85in;
  display: grid; grid-template-columns: 1fr auto 1fr; align-items: center;
  padding-top: 14px; border-top: 1px solid var(--sep);
  font-size: 10pt; color: var(--muted); font-weight: 500;
}
.footer .brand-mark { justify-self: center; font-size: 11pt; }
.footer .brand-mark .logo { width: 18px; height: 18px; border-radius: 4px; }
.footer .page-no { text-align: right; font-weight: 500; }

/* ── Ending — DARK background, blue inline, blue button CTA ─────────── */
.page.ending {
  background: var(--dark);
  color: var(--white);
}
.page.ending .top-nav .brand-mark { color: var(--white); }
.page.ending .top-nav .domain { color: #a4adbd; }
.page.ending .top-nav .domain b { color: var(--white); }
.ending-body { margin-top: 100px; }
.ending-hero {
  font-size: 56pt; font-weight: 700; line-height: 1.04;
  letter-spacing: -0.03em; color: var(--white);
  max-width: 11in;
}
.ending-hero .blue { color: #6ea3ff; }
.ending-sub {
  margin-top: 32px;
  font-size: 15pt; color: #b9c0d0; font-weight: 500;
  max-width: 9.5in; line-height: 1.35;
}
.ending-cta {
  margin-top: 40px;
  display: inline-block; padding: 13px 24px; border-radius: 7px;
  background: var(--blue); color: var(--white);
  font-size: 13pt; font-weight: 600; letter-spacing: -0.005em;
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

    # Sheet has no data → render a friendly empty state instead of a blank page
    if not parts:
        parts.append(f"""
        <section class="page intro">
          <div class="top-nav">
            {BRAND_MARK}
            <div class="domain">Website audit · <b>{_html.escape(client_display or 'no data')}</b></div>
          </div>
          <div class="intro-body">
            <div class="intro-left">
              <div class="hero-heading">No findings yet</div>
              <div class="hero-sub">Run an audit first, then edit the sheet and rebuild the deck.</div>
            </div>
          </div>
        </section>
        """)

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
