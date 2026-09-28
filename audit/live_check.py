"""Live single-URL audit for the /append-finding chatbot.

Given a URL and a free-text hint, fetch the page and pick the best-fit
observation key from HOOK_COPY. The hint anchors the search — e.g. "flat
architecture" resolves to flat_architecture — and the fetched HTML verifies
common on-page issues (missing H1, missing title, missing meta, missing
canonical) so we can still flag something concrete when the hint is vague.
"""
import re
import requests

from audit.hook_copy import HINT_ALIASES, HOOK_COPY, STATUS_LABEL

_UA = {"User-Agent": "Mozilla/5.0 (compatible; Gushwork-Audit-Bot/1.0)"}


def _fetch(url, timeout=15):
    try:
        return requests.get(url, headers=_UA, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None


def _norm_tokens(s):
    """Lowercase words, split on non-alnum, keep 3+ char stems."""
    import re as _re
    return [w[:8] for w in _re.split(r"[^a-z0-9]+", s.lower()) if len(w) >= 3]


def _match_hint(hint):
    """Return the canonical observation key for a hint, or None.

    Matching passes, most-strict first:
      1. Exact alias substring (case-insensitive).
      2. Direct HOOK_COPY key match.
      3. Fuzzy token overlap: every alias-token appears as a prefix of some
         hint-token (so 'architure' matches 'architecture', 'archi' matches
         'architecture', 'missing h1' matches 'h1 is missing').
    """
    if not hint:
        return None
    h = hint.lower().strip()
    # Pass 1: exact substring, longest alias wins
    best = None
    best_len = 0
    for phrase, key in HINT_ALIASES.items():
        if phrase in h and len(phrase) > best_len:
            best = key
            best_len = len(phrase)
    if best:
        return best
    # Pass 2: direct HOOK_COPY key
    if h.replace(" ", "_") in HOOK_COPY:
        return h.replace(" ", "_")
    # Pass 3: fuzzy — every alias-token has a hint-token that shares a
    # long common prefix (handles typos like 'architure' vs 'architecture').
    def _shared_prefix(a, b):
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        return n

    def _fuzzy_match(pt, ht):
        # Short tokens must match exactly; longer tokens allow a shared
        # prefix of ceil(70% of the shorter length).
        if len(pt) <= 3 or len(ht) <= 3:
            return pt == ht
        need = max(4, (min(len(pt), len(ht)) * 7 + 9) // 10)
        return _shared_prefix(pt, ht) >= need

    hint_tokens = _norm_tokens(h)
    if not hint_tokens:
        return None
    best = None
    best_score = 0
    for phrase, key in HINT_ALIASES.items():
        phrase_tokens = _norm_tokens(phrase)
        if not phrase_tokens:
            continue
        score = 0
        for pt in phrase_tokens:
            if any(_fuzzy_match(pt, ht) for ht in hint_tokens):
                score += 1
        if score == len(phrase_tokens) and score > best_score:
            best = key
            best_score = score
    return best


def _analyze_html(html):
    """Extract on-page signals and return a list of detected issue keys."""
    if not html:
        return []
    lower = html.lower()
    issues = []
    # Title
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = (m.group(1).strip() if m else "")
    if not title:
        issues.append(("title_missing", "no <title> in page HTML"))
    elif len(title) > 65:
        issues.append(("title_long", f"title is {len(title)} chars"))
    elif len(title) < 30:
        issues.append(("title_short", f"title is {len(title)} chars"))
    # Meta description
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', html, re.I)
    meta_desc = (m.group(1).strip() if m else "")
    if not meta_desc:
        issues.append(("meta_missing", "no meta description"))
    # H1
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    h1s = [re.sub(r"<[^>]+>", "", h).strip() for h in h1s]
    h1s = [h for h in h1s if h]
    if not h1s:
        issues.append(("h1_missing", "no <h1> in page HTML"))
    elif len(h1s) > 1:
        issues.append(("h1_multiple", f"{len(h1s)} <h1> tags on the page"))
    # Canonical
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']*)["\']', html, re.I)
    canonical = (m.group(1).strip() if m else "")
    if not canonical:
        issues.append(("canonical_missing", "no <link rel=canonical>"))
    # Structured data
    if "application/ld+json" not in lower:
        issues.append(("structured_data", "no ld+json schema block"))
    return issues


def audit_url(url, hint=""):
    """Return a dict describing what to append for `url` + `hint`.

    {
      "key":       finding key from HOOK_COPY (or "" if fully unknown),
      "label":     short status pill label,
      "url":       normalised URL,
      "evidence":  one-line context ("H1 count = 2", "hint match: flat_architecture"),
      "detected":  list of extra issues found on the page,
    }
    """
    result = {"key": "", "label": "", "url": url,
              "evidence": "", "detected": []}
    hint_key = _match_hint(hint)
    r = _fetch(url) if url else None
    html = r.text if (r is not None and r.status_code == 200) else ""
    detected = _analyze_html(html)
    result["detected"] = [{"key": k, "evidence": ev} for k, ev in detected]

    chosen_key = None
    if hint_key and hint_key in HOOK_COPY:
        chosen_key = hint_key
        result["evidence"] = f"hint matched → {hint_key}"
    elif detected:
        chosen_key = detected[0][0]
        result["evidence"] = f"auto-detected: {detected[0][1]}"
    if chosen_key:
        result["key"] = chosen_key
        result["label"] = STATUS_LABEL.get(chosen_key, ("Issue", "medium"))[0]
    else:
        # Fall back: use hint verbatim, no canonical copy
        result["label"] = (hint or "Custom").strip()[:40] or "Custom"
        result["evidence"] = f"no rule matched; recorded as manual finding"
    if r is None:
        result["evidence"] += " (URL not fetched)"
    elif r.status_code != 200:
        result["evidence"] += f" (HTTP {r.status_code})"
    return result
