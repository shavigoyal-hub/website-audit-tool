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


def _match_hint(hint):
    """Return the canonical observation key for a hint, or None."""
    if not hint:
        return None
    h = hint.lower().strip()
    # Longest alias substring wins so 'missing h1' beats 'h1'.
    best = None
    best_len = 0
    for phrase, key in HINT_ALIASES.items():
        if phrase in h and len(phrase) > best_len:
            best = key
            best_len = len(phrase)
    if best:
        return best
    # Direct HOOK_COPY key
    if h.replace(" ", "_") in HOOK_COPY:
        return h.replace(" ", "_")
    return None


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
