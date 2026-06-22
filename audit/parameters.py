"""Site-level checks derived from the Screaming Frog CSV + a small set of
single-URL live checks (robots.txt, sitemap.xml, favicon.ico, redirect probes).

Returns a dict:
    {
      "issues": [ {key, category, priority, observation, impact, reference}, ... ],
      "passed": [ "label", ... ],
      "na":     [ "label : reason not evaluated", ... ],
    }

`issues` flow into the Observation tab; `passed` into the "Checks Passed" tab;
`na` are listed as honest "not evaluated" notes (e.g. keyword-targeting checks
need a target-keyword list we don't have).
"""
import re

import requests

from audit.sf_csv import _col, is_html, _num

UA = {"User-Agent": "Mozilla/5.0 (compatible; GushworkAuditBot/1.0; +https://gushwork.ai)"}


def _get(url, allow_redirects=True, timeout=25):
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=allow_redirects)
        return r
    except requests.RequestException:
        return None


def _origin(live_url):
    m = re.match(r"(https?://[^/]+)", live_url.strip())
    return m.group(1) if m else live_url.rstrip("/")


def evaluate(df, live_url):
    issues, passed, na = [], [], []
    origin = _origin(live_url)
    host = re.sub(r"^https?://", "", origin)
    addr = _col(df, "Address")
    addr_l = addr.str.lower()

    # --- Presence checks (from the crawl) ---
    has_about = bool(addr_l.str.contains(r"/about|who-we-serve|our-process|meet-the-team|/team").any())
    (passed if has_about else issues).append(
        "About / company page present" if has_about else _issue(
            "about_missing", "About / Company Page", "Medium",
            "No clear About / company page found in the crawl",
            "A missing About page weakens brand trust signals."))
    has_contact = bool(addr_l.str.contains(r"/contact|book-meeting|/get-in-touch|/schedule").any())
    (passed if has_contact else issues).append(
        "Contact page present" if has_contact else _issue(
            "contact_missing", "Contact Page", "High",
            "No contact / booking page found in the crawl",
            "A missing contact path reduces conversions and local SEO."))

    # --- Crawl budget (share of redirects / errors / non-indexable) ---
    html_mask = is_html(df)
    status = _num(df, "Status Code").fillna(0).astype(int)
    total_html = int(html_mask.sum()) or 1
    waste = int((status.between(300, 599) | (_col(df, "Indexability").str.lower() == "non-indexable")).sum())
    if waste / total_html > 0.10:
        issues.append(_issue("crawl_budget", "Crawl Budget", "Low",
                             f"Multiple pages found wasting crawl budget : {waste} of {total_html} crawled URLs are redirects, errors or non-indexable",
                             "Crawl budget spent on dead URLs starves real money pages."))
    else:
        passed.append(f"Crawl budget healthy ({waste}/{total_html} URLs redirect/error/non-indexable)")

    # --- robots.txt ---
    rb = _get(f"{origin}/robots.txt")
    if rb is not None and rb.status_code == 200:
        body = rb.text
        blocked = re.search(r"(?im)^\s*user-agent:\s*\*\s*[\s\S]*?^\s*disallow:\s*/\s*$", body)
        has_sitemap_ref = bool(re.search(r"(?im)^\s*sitemap:\s*http", body))
        if blocked:
            issues.append(_issue("robots_block", "Robots.txt", "Critical",
                                 "Site appears blocked by robots.txt (Disallow: / for all agents)",
                                 "A site-wide robots block prevents crawling and ranking."))
        else:
            passed.append("robots.txt present and not blocking the site")
        passed.append("Sitemap referenced in robots.txt" if has_sitemap_ref else "robots.txt present")
    else:
        issues.append(_issue("robots_missing", "Robots.txt", "Low",
                             "No accessible robots.txt found",
                             "A missing robots.txt removes control over crawler access."))

    # --- XML sitemap ---
    sm = _get(f"{origin}/sitemap.xml")
    sm2 = sm if (sm is not None and sm.status_code == 200) else _get(f"{origin}/sitemap_index.xml")
    if sm2 is not None and sm2.status_code == 200 and ("<urlset" in sm2.text or "<sitemapindex" in sm2.text):
        passed.append("XML sitemap found and valid")
    else:
        issues.append(_issue("sitemap_missing", "XML Sitemap", "Medium",
                             "No XML sitemap found at /sitemap.xml",
                             "Without a sitemap, pages are discovered and indexed slower."))

    # --- Favicon ---
    home = _get(origin + "/")
    fav_html = bool(home is not None and re.search(r'rel=["\'][^"\']*icon', home.text or "", re.I))
    fav_file = _get(f"{origin}/favicon.ico")
    if fav_html or (fav_file is not None and fav_file.status_code == 200):
        passed.append("Favicon present")
    else:
        issues.append(_issue("favicon_missing", "Favicon", "Low",
                             "No favicon detected",
                             "A missing favicon weakens brand recognition in tabs and search."))

    # --- www / non-www redirect (from SF crawl data) ---
    # SF will include www. or non-www variants in the crawl if it encountered them.
    canonical_has_www = host.startswith("www.")
    alt_prefix = f"http{'s' if origin.startswith('https') else ''}://" + (
        host[4:] if canonical_has_www else "www." + host)
    alt_in_crawl = df[addr.str.startswith(alt_prefix)]
    if not alt_in_crawl.empty:
        alt_status = _num(alt_in_crawl, "Status Code").fillna(0).astype(int)
        if alt_status.isin([301, 308]).all():
            passed.append("www / non-www variants redirect to canonical host (301/308)")
        elif alt_status.isin([302, 307]).any():
            issues.append(_issue("wwwredir_temp", "WWW Redirect", "Low",
                                 f"www / non-www handled with a temporary redirect instead of 301",
                                 "Temporary redirects do not consolidate link equity.",
                                 reference=alt_in_crawl["Address"].head(3).tolist()))
        else:
            issues.append(_issue("wwwredir_missing", "WWW Redirect", "Medium",
                                 "www and non-www versions do not redirect to a single canonical host",
                                 "Both www and non-www resolving splits ranking signals."))
    else:
        na.append("www / non-www redirect : alt variant not in SF crawl — verify manually: curl -sI " + alt_prefix + "/")

    # --- HTTP → HTTPS redirect (from SF crawl data) ---
    http_prefix = "http://" + re.sub(r"^www\.", "", host)
    http_in_crawl = df[addr.str.startswith(http_prefix) & ~addr.str.startswith("https://")]
    if not http_in_crawl.empty:
        http_status = _num(http_in_crawl, "Status Code").fillna(0).astype(int)
        if http_status.isin([301, 308]).all():
            passed.append("HTTP redirects to HTTPS (301/308)")
        else:
            bad_http = http_in_crawl.loc[~http_status.isin([301, 308]), "Address"].head(3).tolist()
            issues.append(_issue("httpsredir_missing", "HTTPS Redirect", "High",
                                 "HTTP does not 301-redirect to HTTPS",
                                 "Serving HTTP without HTTPS hurts trust and rankings.",
                                 reference="\n".join(bad_http)))
    else:
        na.append("HTTP→HTTPS redirect : http:// URLs not in SF crawl scope — verify manually: curl -sI http://" + host + "/")

    # --- Not derivable without extra inputs ---
    na.append("Keywords in Title Tags : needs a target-keyword list per page")
    na.append("Keywords in Meta Description : needs a target-keyword list per page")
    na.append("Full image alt-text audit : needs Screaming Frog 'Images' export")
    na.append("CTA above the fold : assessed qualitatively under the CRO findings (see Call-to-Action)")

    return {"issues": issues, "passed": passed, "na": na}


def _issue(key, category, priority, observation, impact, reference="-"):
    return {"key": key, "category": category, "priority": priority,
            "observation": observation, "impact": impact, "reference": reference}
