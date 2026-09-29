"""Chat-style deep audit: fetches the homepage + a few key pages and
looks at what actually renders. Complements the SF crawl (which only
gives crawl-column data) and parameters.evaluate (which does site-level
probes).

Called from pipeline.run BEFORE the sheet is built. Returns a list of
finding dicts in the same shape parameters._issue() produces.
"""
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"}


def _get(url, timeout=15):
    try:
        return requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None


def _origin(url):
    m = re.match(r"(https?://[^/]+)", url.strip())
    return m.group(1) if m else url.rstrip("/")


def _issue(key, category, priority, observation, impact, reference="-"):
    return {"key": key, "category": category, "priority": priority,
            "observation": observation, "impact": impact,
            "reference": reference}


# ── Homepage-level checks ────────────────────────────────────────────
def _check_title_quality(html, origin, findings):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = (m.group(1).strip() if m else "")
    if not title:
        return  # sf_csv will emit title_missing
    # 1. Homepage title is 'Home - Brand' / 'Home' pattern
    if re.match(r"^\s*Home\s*[-|·]?\s*", title, re.I) and len(title) < 40:
        findings.append(_issue(
            "homepage_title_weak", "Title Tags", "Critical",
            f"Homepage title reads '{title}' — no keyword, category or value prop",
            "Google has no on-page ranking signal for the site's most-linked page.",
            reference=f"{origin}/ → <title>{title}</title>"))
        return
    # 2. Title is ALL CAPS
    letters = re.findall(r"[A-Za-z]", title)
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.8:
        findings.append(_issue(
            "title_all_caps", "Title Tags", "High",
            f"Homepage title is in SHOUTING CAPS: '{title[:80]}'",
            "All-caps titles read as spammy and reduce SERP CTR.",
            reference=f"{origin}/"))


def _check_h1_quality(html, origin, findings):
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    h1s = [re.sub(r"<[^>]+>", "", h) for h in h1s]
    # Detect long whitespace runs mid-H1 (broken layout)
    for h in h1s:
        if re.search(r"\s{4,}", h):
            findings.append(_issue(
                "homepage_h1_whitespace", "H1 Tags", "High",
                "Homepage H1 has large whitespace gaps mid-sentence",
                "Broken H1 layout reads as unprofessional and can miscount as multiple H1s.",
                reference=f"{origin}/ → H1: {h.strip()[:100]}"))
            return


def _check_schema_types(html, origin, findings):
    """Look for the specific schema TYPES chat expects on the homepage."""
    ld_blocks = re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        html, re.I | re.S)
    types_found = set()
    for b in ld_blocks:
        for t in re.findall(r'"@type"\s*:\s*"([^"]+)"', b):
            types_found.add(t)
    if not ld_blocks:
        return  # parameters.evaluate already emits structured_data
    expected_home = {"Organization", "LocalBusiness", "WebSite", "Corporation"}
    if not expected_home & types_found:
        found_str = ", ".join(sorted(types_found)) or "(none)"
        findings.append(_issue(
            "schema_organization_missing", "Schema Markup", "High",
            f"Homepage ships ld+json but has no Organization / LocalBusiness / WebSite schema (found: {found_str})",
            "Missing entity schema stops Google and LLMs from linking the site to a real business.",
            reference=f"{origin}/"))


def _check_default_favicon(html, origin, findings):
    """Detect platform-default favicons — 'unbranded' signal."""
    m = re.search(
        r'<link[^>]+rel=["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]+href=["\']([^"\']+)["\']',
        html, re.I)
    if not m:
        return
    href = m.group(1)
    href_lower = href.lower()
    default_hosts = ("gohighlevel", "highlevel", "wixstatic", "wix.com",
                      "shopify.com/s/", "squarespace-cdn", "webflow",
                      "wp-content/plugins", "wp-content/themes/twenty")
    if any(h in href_lower for h in default_hosts):
        findings.append(_issue(
            "favicon_default", "Favicon", "Medium",
            f"Favicon points at platform default ({href[:80]})",
            "A platform-default favicon signals an unbranded, generic site.",
            reference=f"{origin}/ → favicon: {href}"))


def _check_broken_homepage_images(html, origin, findings):
    """Sample first 6 <img src=> and flag ones that 404."""
    srcs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)[:6]
    from urllib.parse import urljoin
    broken = []
    for s in srcs:
        if s.startswith("data:"):
            continue
        url = urljoin(origin + "/", s)
        try:
            h = requests.head(url, headers=UA, timeout=5, allow_redirects=True)
        except Exception:
            continue
        if h.status_code in (404, 410) or (h.status_code >= 500):
            broken.append(url)
    if broken:
        findings.append(_issue(
            "homepage_images_broken", "Homepage", "High",
            f"{len(broken)} of the first 6 homepage images return 404 / server error",
            "Broken homepage images kill first-impression trust.",
            reference="\n".join(broken[:5])))


def _check_fragment_only_nav(html, origin, findings):
    """Detect single-page-app nav where every top nav link is a #fragment.

    Extract the FIRST <nav>...</nav> block; if it has ≥3 anchors and ≥60% of
    them are fragment-only (href starts with '#' or href starts with '/' and
    contains '#' with no path), the site has no distinct pages for its top
    sections to rank.
    """
    nav_m = re.search(r"<nav\b[^>]*>(.*?)</nav>", html, re.I | re.S)
    if not nav_m:
        return
    nav_html = nav_m.group(1)
    anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', nav_html, re.I)
    # Filter out mailto: / tel: / javascript: / empty
    anchors = [a for a in anchors if a and not a.lower().startswith(
        ("mailto:", "tel:", "javascript:"))]
    if len(anchors) < 3:
        return
    frag_only = []
    for a in anchors:
        a_stripped = a.strip()
        if a_stripped.startswith("#"):
            frag_only.append(a_stripped)
            continue
        # /#product or https://site/#product
        if "#" in a_stripped:
            # split path from fragment
            path_part = a_stripped.split("#", 1)[0].rstrip("/")
            if path_part in ("", origin, origin.rstrip("/")):
                frag_only.append(a_stripped)
    if len(frag_only) / len(anchors) >= 0.6:
        sample = ", ".join(f"{origin}{f}" if f.startswith("#") else f
                           for f in frag_only[:4])
        findings.append(_issue(
            "fragment_only_nav", "Site Architecture", "High",
            f"Nav has {len(frag_only)}/{len(anchors)} fragment-only links — "
            f"there is no distinct page for these sections to rank",
            "Fragment nav gives Google one page instead of many; each section "
            "loses its own SERP.",
            reference=f"{origin}/ → {sample}"))


def _check_duplicate_homepage(origin, home_html, findings):
    """Compare / and /home body sizes — if same, they're duplicate."""
    for path in ("/home", "/home/"):
        r = _get(origin + path)
        if not r or r.status_code != 200:
            continue
        # Simple heuristic: if content-length within 5% and both have same H1
        root_size = len(home_html or "")
        alt_size = len(r.text or "")
        if root_size == 0 or alt_size == 0:
            continue
        ratio = abs(root_size - alt_size) / max(root_size, alt_size)
        if ratio < 0.05:
            findings.append(_issue(
                "duplicate_homepage", "Homepage", "High",
                f"{origin}{path} serves near-identical content to {origin}/",
                "Duplicate homepage variants split link equity and confuse canonicalisation.",
                reference=f"{origin}/ vs {origin}{path}"))
            return


# ── Public entry ─────────────────────────────────────────────────────
def evaluate(live_url):
    """Return chat-style findings for `live_url`. Never raises."""
    findings = []
    try:
        origin = _origin(live_url)
        home = _get(origin + "/")
        if home is None or home.status_code != 200:
            return findings
        html = home.text or ""

        _check_title_quality(html, origin, findings)
        _check_h1_quality(html, origin, findings)
        _check_schema_types(html, origin, findings)
        _check_default_favicon(html, origin, findings)
        _check_broken_homepage_images(html, origin, findings)
        _check_fragment_only_nav(html, origin, findings)
        _check_duplicate_homepage(origin, html, findings)
    except Exception as exc:
        print(f"[deep] evaluate failed: {exc}")
    return findings
