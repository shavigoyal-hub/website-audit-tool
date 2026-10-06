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
    """Word-boundary matching on the pill label so 'Known schema' doesn't
    match 'no', 'Following links' doesn't match 'low', etc.
    """
    import re as _rp
    low = (label or "").lower().strip()
    if not low:
        return "pill-amber"
    tokens = set(_rp.findall(r"[a-z0-9]+", low))

    def has_token(k):
        return k in tokens

    def has_phrase(p):
        return _rp.search(r"\b" + _rp.escape(p) + r"\b", low) is not None

    # Red — hard failure signals
    if (has_token("no") or has_token("missing") or has_token("noindex")
            or has_token("404") or has_token("5xx") or has_token("error")
            or has_token("critical") or has_phrase("render error")
            or has_phrase("cls high") or has_phrase("lcp >")
            or has_phrase("perf <")):
        return "pill-red"
    # Amber — degraded / needs attention
    if (has_token("competing") or has_token("duplicate") or has_token("long")
            or has_token("truncated") or has_token("stuffed")
            or has_token("medium") or has_token("heavy") or has_token("blocking")
            or has_token("wrong") or has_token("few") or has_token("warning")
            or has_phrase("over-length") or has_phrase("js-only")):
        return "pill-amber"
    # Green — passed / healthy
    if (has_token("ok") or has_token("good") or has_token("passed")
            or has_token("single") or has_phrase("1 h1")):
        return "pill-green"
    return "pill-amber"


def _fallback_label(category, observation=""):
    """The pill for a row the sheet left unlabelled.

    "Issue" told the reader nothing — a Social / OG Tags card read
    "/ (homepage)  [Issue]". The category already says what was checked, so
    the label is that category's own status ("No OG tags", "No schema",
    "Thin"); failing that, the plainest word the observation supports.
    """
    try:
        from audit.observations import CATEGORY as _CAT
        cat = (category or "").strip().lower()
        for key, name in _CAT.items():
            if str(name).strip().lower() == cat and key in STATUS_LABEL:
                return STATUS_LABEL[key][0]
    except Exception:
        pass
    low = (observation or "").lower()
    for word, label in (("missing", "Missing"), ("duplicate", "Duplicate"), ("too long", "Too long"),
                        ("too short", "Too short"), ("thin", "Thin"), ("slow", "Slow"), ("blocked", "Blocked"),
                        ("broken", "Broken"), ("not found", "Not found")):
        if word in low:
            return label
    return "Needs fixing"


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
    # Split on ×, +, or = (with surrounding spaces). '+' must be
    # padded with spaces so we don't split a leading '+' inside a stat.
    parts = re.split(r'\s+([×+=])\s+', formula)
    terms = []
    for i, p in enumerate(parts):
        p = p.strip()
        if not p:
            continue
        if p in ('×', '+', '='):
            terms.append(('op', p))
        else:
            m = re.match(r'^([+\-]?\d+(?:\.\d+)?%?)\s+(.+)$', p)
            if m:
                terms.append(('term', m.group(1), m.group(2)))
            else:
                terms.append(('term', '', p))
    return terms


GUSHWORK_LOGO_SVG = (
    # THE REFERENCE'S OWN ARTWORK. These are the vector paths drawn in
    # ArizonaHomeGrantsWebsiteAudit.pdf (32x32 box, #0070FF tile with an 8px
    # radius, two white shapes split by a curved sweep). It had been redrawn by
    # eye twice — a parallelogram, then a document with a folded corner — and
    # neither is the Gushwork mark.
    '<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="0" y="0" width="32" height="32" rx="8" fill="#0070ff"/>'
    '<path fill="#ffffff" d="M23.3218 8.9127C23.5005 8.4721 23.1699 8 22.6945 8H9.8286'
    'C8.8187 8 8 8.8187 8 9.8286V21.3556C8 22.4036 9.0342 23.1366 9.9921 22.7114'
    'C16.1699 19.969 20.8757 14.9415 23.3218 8.9127Z"/>'
    '<path fill="#ffffff" d="M14.5032 24C14.2804 24 14.1871 23.7106 14.3652 23.5767'
    'C18.9801 20.1053 22.2868 15.1609 23.7532 9.6104C23.7881 9.4783 24 9.5032 24 9.6399'
    'V22.1714C24 23.1813 23.1813 24 22.1714 24H14.5032Z"/>'
    '</svg>'
)
BRAND_MARK = ('<span class="brand-mark">'
              f'<span class="logo">{GUSHWORK_LOGO_SVG}</span>Gushwork</span>')


def _render_intro(row, client_display):
    hook_stat = row.get("hook_stat") or "+33%"
    hook_ctx  = row.get("hook_ctx") or "Increase your leads by 33%"
    subtitle  = row.get("observation") or "Same pages. Same website."
    # Strip 'eg: <urls>' block from the intro subtitle — URLs belong on
    # per-finding slides, not the hero.
    import re as _re
    subtitle = _re.split(r"\n\s*eg\s*:", subtitle, maxsplit=1, flags=_re.I)[0]
    subtitle = subtitle.split("\n", 1)[0].strip()
    formula   = row.get("found") or ""
    # If the sheet stored a #ERROR!/#REF! (Sheets parsed a leading '+X%' as
    # a formula and blew up), or the cell is empty, fall back to a neutral
    # headline instead of inventing component terms the audit didn't find.
    # The old fallback printed '+5.8% Meta descriptions × +25% Structured
    # data = +33% More leads' REGARDLESS of what the audit actually
    # discovered — misleading when the site has neither finding.
    if formula.strip().upper().startswith("#") or formula.strip() == "":
        formula = "Same pages, same website → more leads"
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
    # Costs column preferred, then fall back to the sheet's Impact column,
    # then to the observation. That way CS-edited impact copy in the sheet
    # still surfaces on the deck.
    costs     = row.get("costs", "") or row.get("impact", "") or row.get("observation", "")
    support   = row.get("support", "")

    # Strip a duplicated leading number from hook_ctx.
    import re as _re
    hook_ctx = _re.sub(r"^\s*[+\-]?\d[\d.,\s]*%\s+", "", hook_ctx)

    # Sheets written by other tools sometimes leave hook_ctx / support
    # blank while filling only observation + impact. Fall back to the
    # first sentence of observation so the hero isn't just a naked stat.
    if not hook_ctx.strip():
        obs = (row.get("observation") or "").strip()
        # Cut at first line-break (evidence starts on next line via 'eg:')
        obs = obs.split("\n", 1)[0].strip()
        # Cut at first sentence end
        m = _re.search(r"(?<=\w{3})\.(?:\s+|$)", obs)
        if m:
            obs = obs[:m.start() + 1]
        # Hard cap so the hero doesn't wrap to 4+ lines
        if len(obs) > 70:
            cut = obs[:70].rsplit(" ", 1)[0].rstrip(",.:;")
            obs = cut + "…"
        hook_ctx = obs

    # If 'found' is empty but observation has 'eg: <urls>', harvest them
    # so 'What we found' shows real pages instead of 'Site-wide'.
    if not (row.get("found") or "").strip():
        obs_full = row.get("observation") or ""
        eg_m = _re.search(r"eg\s*:\s*(.+)$", obs_full, _re.I | _re.S)
        if eg_m:
            harvested = [u.strip() for u in eg_m.group(1).splitlines() if u.strip().startswith("http")]
            if harvested:
                row = dict(row)  # don't mutate caller's dict
                row["found"] = "\n".join(harvested)

    # URL rows with pills. Render as PATH ONLY (matches reference PDF style).
    import re as _ure
    def _to_path(u):
        m = _ure.match(r"^https?://[^/]+(/.*)?$", u.strip())
        if m:
            path = m.group(1) or ""
            return "/ (homepage)" if path in ("", "/") else path
        return u.strip()

    rows_html = []
    # Cap at 6 to fit within the page height. Deduplicate by normalized
    # display path (a trailing slash is not a different URL, and the same
    # merged category can pick up '/homepage' twice when H1_missing and
    # H1_multiple both flag it).
    seen = set()
    for entry in _split_lines(row.get("found", "")):
        if len(rows_html) >= 6:
            break
        stripped = entry.strip()
        if stripped in ("-", "") or stripped.startswith("- |") or stripped.startswith("-|"):
            continue
        if "|" in stripped:
            parts = stripped.split("|", 1)
            url   = parts[0].strip()
            label = parts[1].strip()
        else:
            url, label = stripped, ""
        if not url or url == "-":
            continue
        display_url = _to_path(url)
        # Normalize: strip trailing slash except homepage marker
        norm = display_url.rstrip("/") or "/"
        dedupe_key = (norm.lower(), (label or "").lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if not label or label.strip().lower() == "issue":
            label = _fallback_label(category, row.get("observation", ""))
        pcls = _pill_class(label)
        # Canonical / redirect findings ship as 'src → target'. Both sides
        # get rendered as paths (not full URLs) since the domain is already
        # in the deck header — the reader only cares about which path
        # points to which.
        arrow_m = _ure.match(r"^(.+?)\s*(?:→|->|=>)\s*(https?://\S+)$", url)
        if arrow_m:
            src_raw = arrow_m.group(1).strip()
            tgt_raw = arrow_m.group(2).strip()
            src_path = _to_path(src_raw)
            tgt_path = _to_path(tgt_raw)
            src_href = src_raw if src_raw.startswith("http") else url
            display_url = (f"<a href='{_html.escape(src_href)}' target='_blank' rel='noopener'>{_html.escape(src_path)}</a>"
                           f"<span class='wf-arrow'>→</span>"
                           f"<a class='wf-target' href='{_html.escape(tgt_raw)}' target='_blank' rel='noopener'>{_html.escape(tgt_path)}</a>")
            rows_html.append(
                f"<li><span class='wf-url wf-2line'>{display_url}</span>"
                f"<span class='pill {pcls}'>{_html.escape(label)}</span></li>"
            )
            continue
        # Path stays as the display text, but the anchor href is the full URL
        # so a click in the PDF / HTML opens the page directly.
        href = url if url.startswith("http") else display_url
        rows_html.append(
            f"<li><a class='wf-url' href='{_html.escape(href)}' target='_blank' rel='noopener'>{_html.escape(display_url)}</a>"
            f"<span class='pill {pcls}'>{_html.escape(label)}</span></li>"
        )

    # Pull IMG: markers out of support (attached via chatbot) — render them
    # as thumbnails in a dedicated image card. Two marker formats supported:
    #   IMG: GDRIVE_IMG:<file_id>       (new — routed through /img/<id>)
    #   IMG: https://drive.google.com/… (old — extract id, route same way)
    img_urls = []
    if support:
        import os as _os_img
        import re as _re_img
        raw = _re_img.findall(r"IMG:\s*(\S+)", support)
        if raw:
            support = _re_img.sub(r"IMG:\s*\S+\s*", "", support).strip()

        def _extract_file_id(u):
            m = _re_img.match(r"GDRIVE_IMG:([A-Za-z0-9_-]+)", u)
            if m: return m.group(1)
            m = _re_img.search(r"drive\.google\.com/(?:uc\?[^ ]*id=|thumbnail\?id=|d/)([A-Za-z0-9_-]+)", u)
            if m: return m.group(1)
            m = _re_img.search(r"lh3\.googleusercontent\.com/d/([A-Za-z0-9_-]+)", u)
            if m: return m.group(1)
            return None

        import base64 as _b64
        for u in raw:
            # Inline data URI — pass straight through.
            if u.startswith("data:"):
                img_urls.append(u)
                continue
            fid = _extract_file_id(u)
            if fid:
                # Inline as data URI — the /img proxy returned the wrong
                # content-type (application/json) and all public hotlink
                # URLs resolve to application/octet-stream which browsers
                # don't render as images. Base64 inline always works.
                try:
                    from audit.drive_upload import fetch_bytes as _fb
                    body, mime = _fb(fid)
                    if body:
                        b64 = _b64.b64encode(body).decode("ascii")
                        img_urls.append(f"data:{mime or 'image/png'};base64,{b64}")
                        continue
                except Exception as exc:
                    print(f"[deck] inline img failed {fid}: {exc}")
                # Last resort: raw URL (may still show broken; onerror hides it)
                img_urls.append(f"https://drive.google.com/uc?export=view&id={fid}")
            else:
                img_urls.append(u)

    # Supporting stat — big blue number, first sentence dark bold, rest muted.
    # HARD RULE (per CS): the Supporting Stats box is for a STAT, not a
    # narrative. Support must LEAD with a number / percentage / Nx / ratio.
    # If it starts with prose, hide the block — that narrative already lives
    # in What It Costs You above it.
    sup_html = ""
    if support:
        import re
        # Leading-stat detector: %, decimal %, Nx, N of N, or a bare number
        # followed by a unit word (seconds, sites, users, pages, etc.).
        starts_with_stat = bool(re.match(
            r"^\s*(?:[+\-]?\d+(?:[.,-]\d+)?\s*(?:%|x)|"
            r"\d+\s+of\s+\d+|only\s+\d+\s+of\s+\d+|"
            r"\d[\d,]{2,}|"                                   # 1,000+ or 100+
            r"\d+\s+(?:seconds|sec|min|hours?|days?|ms|"
            r"sites?|users?|pages?|visitors?|clicks?|leads?|percent|out\s+of))",
            support, re.I,
        ))
        if starts_with_stat:
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

    # Empty stat: if this is a Manual / Custom row, DON'T fabricate a
    # priority-based percentage — it confuses the reader ('-8% no About
    # page' is meaningless). Fall back only when the row has category
    # signal that ties to an actual finding key (H1, Title, Meta, etc.).
    def _looks_manual(cat):
        c = (cat or "").lower()
        return c.startswith("custom") or c.startswith("manual") or c == ""

    if not hook_stat:
        if _looks_manual(category):
            hook_stat = "!"
        else:
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
          <ul class="wf-list">{"".join(rows_html) or f"<li><span class='wf-url'>Homepage</span><span class='pill {_pill_class(_fallback_label(category, row.get('observation', '')))}'>{_html.escape(_fallback_label(category, row.get('observation', '')))}</span></li>"}</ul>
        </div>
        <div class="card-col">
          <div class="card card-costs">
            <div class="card-label">What it costs you</div>
            <div class="card-body">{_html.escape(costs)}</div>
          </div>
          {f"<div class='card card-sup'>{sup_html}</div>" if (sup_html and not img_urls) else ""}
          {(f"<div class='card card-img'>" + "".join(f"<img src='{u}' alt='' loading='lazy' onerror='this.parentNode&&this.parentNode.removeChild(this)' />" for u in img_urls[:3]) + "</div>") if img_urls else ""}
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
.head-line { font-size: 10pt; font-weight: 500; color: var(--muted); letter-spacing: -0.005em; }

/* ── Intro ──────────────────────────────────────────────────────────── */
.intro-body { display: flex; gap: 60px; align-items: flex-start; margin-top: 30px; }
.intro-left { flex: 1; }
.hero-heading {
  font-size: 58pt; font-weight: 700; line-height: 1.0; letter-spacing: -0.04em;
  color: var(--text);
}
.hero-heading .blue { color: var(--blue); }
.hero-sub {
  font-size: 16pt; color: var(--muted); margin-top: 18px;
  font-weight: 500; letter-spacing: -0.01em;
}

.intro-right { flex: 0 0 5.6in; min-width: 0; max-width: 5.6in; overflow: hidden; }
.intro-formula {
  display: flex; align-items: stretch; gap: 8px; flex-wrap: wrap;
  margin-bottom: 22px; max-width: 100%;
}
.formula-card {
  flex: 1 1 1.1in; min-width: 0; max-width: 100%;
  border: 1px solid var(--sep); border-radius: 12px;
  padding: 12px 14px; background: var(--white);
  display: flex; flex-direction: column; gap: 4px;
  overflow: hidden;
}
.formula-card.hi { background: var(--card-blue); border-color: #cadaff; }
.formula-num { font-size: 16pt; font-weight: 700; color: var(--blue); line-height: 1; letter-spacing: -0.02em; white-space: nowrap; }
.formula-label { font-size: 9pt; color: var(--muted); font-weight: 500; overflow-wrap: break-word; }
.formula-op { display: flex; align-items: center; padding: 0 2px; color: var(--muted); font-size: 14pt; }

.uplift-card {
  border: 1px solid var(--sep); border-radius: 14px;
  padding: 20px 24px; background: var(--white);
}
.uplift-lead { font-size: 10pt; color: var(--muted); font-weight: 500; }
.uplift-big {
  font-size: 34pt; font-weight: 700; letter-spacing: -0.03em; line-height: 1;
  margin-top: 8px;
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
.chip-small { font-size: 9pt; } /* fallback for legacy pill callers */
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 5px 12px; border-radius: 7px;
  font-size: 9.5pt; font-weight: 500; line-height: 1;
  background: var(--white); border: 1px solid;
}
.chip .dot { width: 7px; height: 7px; border-radius: 50%; }
.chip-critical { color: #c8102e; border-color: #f5b6b6; background: #fdecec; } .chip-critical .dot { background: #c8102e; }
.chip-high     { color: #c2410c; border-color: #fbd0a5; background: #fef5e2; } .chip-high     .dot { background: #f97316; }
.chip-medium   { color: #4b5563; border-color: #d1d5db; background: #f3f4f6; } .chip-medium   .dot { background: #6b7280; }
.chip-low      { color: #2563eb; border-color: #bfdbfe; background: #eff5ff; } .chip-low      .dot { background: #3b82f6; }

.hero {
  display: flex; align-items: flex-start; gap: 28px;
  margin: 28px 0 30px;
}
.hero-stat {
  font-size: 88pt; font-weight: 700; color: var(--blue);
  line-height: 0.9; letter-spacing: -0.055em;
  flex-shrink: 0;
}
.hero-stat.zero { color: var(--red); }
.hero-ctx  {
  font-size: 26pt; font-weight: 700; line-height: 1.1; flex: 1;
  letter-spacing: -0.025em; padding-top: 12px;
  color: var(--muted);
}
.hero-ctx .headline { color: var(--text); }

/* MEASURED FROM THE REFERENCE PDF (its drawing commands, 1600px canvas):
   two EQUAL columns 698px wide with a 44px gutter; each card HUGS its content
   (six rows = 384px, two rows = far shorter) — a card is never stretched to
   its neighbour's height, which is what left a one-row "What we found" card
   as a tall empty box. Fill #F8FAFC, 1px #E2E8F0 border, 12px radius, 24px
   padding. This page is 1280px wide, so lengths are those x 0.8. */
.cards {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 35px; align-items: start;
}
.card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 19px 20px 22px;
  min-width: 0;
}
.card-wf  { min-width: 0; }
.card-col { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
/* The supporting-stat card is WHITE in the reference, border only. */
.card.card-sup { background: #fff; }
.card.card-img {
  background: #fff; padding: 8px; display: flex; flex-direction: column;
  gap: 8px; align-items: center;
  /* The slide gives the right column ~3.4in total. The costs card takes
     ~1.4in, so the image card is capped hard at 2in to stay inside the
     footer. The img itself scales within that; a tall GSC screenshot
     will shrink, which is correct. */
  min-width: 0; max-width: 100%; overflow: hidden; box-sizing: border-box;
  height: 2in;
}
.card.card-img img {
  display: block;
  max-width: 100%;
  max-height: 100%;
  width: auto; height: auto;
  object-fit: contain;
  border-radius: 6px; border: 1px solid #e2e8f0;
}
.card-head { display: flex; justify-content: space-between; margin-bottom: 8px; }
.card-label {
  font-size: 9.5pt; font-weight: 500; color: var(--muted); letter-spacing: 0;
}
.card-body {
  font-size: 12.5pt; font-weight: 500; line-height: 1.4;
  color: var(--text);
}
.wf-list { list-style: none; min-width: 0; width: 100%; }
.wf-list li {
  display: flex; align-items: center; justify-content: space-between;
  gap: 14px;
  padding: 8px 0; border-top: 1px solid #e2e8f0;
  min-width: 0;
  width: 100%;
}
.wf-list li:first-child { border-top: 0; padding-top: 4px; }
.wf-2line {
  display: flex; flex-direction: column; gap: 3px; overflow: hidden;
  white-space: normal;
}
.wf-2line .wf-arrow { color: var(--muted); padding: 0 4px; }
.wf-2line .wf-target {
  color: var(--muted); font-size: 10pt;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  display: block;
}
.wf-url {
  flex: 1 1 0;
  min-width: 0;
  max-width: 100%;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10.5pt; color: var(--text);
  font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, monospace;
  font-weight: 400;
  text-decoration: none;
}
a.wf-url:hover { color: var(--blue); text-decoration: underline; }
.pill {
  flex: 0 0 auto;
  display: inline-block; padding: 2px 9px; border-radius: 6px;
  font-size: 8.5pt; font-weight: 500; white-space: nowrap;
  border: 1px solid;
}
.pill-red   { background: #fdecec; color: #c8102e; border-color: #f5b6b6; }
.pill-amber { background: #fef5e2; color: #b45309; border-color: #fbd08a; }
.pill-green { background: #eaf7ee; color: #166534; border-color: #b8dfc3; }

/* Supporting stat card — big blue number, bold dark first sentence, muted rest */
.card-sup { }
.sup-num  {
  font-size: 36pt; font-weight: 700; color: var(--blue); line-height: 1;
  letter-spacing: -0.03em; margin-bottom: 6px; display: block;
}
.sup-rest {
  font-size: 11pt; line-height: 1.4;
  color: var(--muted); font-weight: 400;
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
  font-size: 10.5pt; color: var(--muted); font-weight: 500;
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
<button id="dl-pdf" onclick="window.print()"
  style="position:fixed;top:16px;right:16px;z-index:9999;
         background:#111;color:#fff;border:0;border-radius:8px;
         padding:10px 16px;font:600 13px 'Instrument Sans',sans-serif;
         cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.15);">
  ↓ Save as PDF
</button>
<style>@media print {{ #dl-pdf {{ display: none !important; }} }}</style>
<div class="deck">
{''.join(parts)}
</div>
</body>
</html>
"""
