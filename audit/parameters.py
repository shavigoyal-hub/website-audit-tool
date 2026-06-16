"""Site-level + live parameters that the Screaming Frog CSV can't answer alone.

Returns a dict:
    {
      "issues": [ {key, category, priority, observation, impact, reference}, ... ],
      "passed": [ "label", ... ],
      "na":     [ "label — reason not evaluated", ... ],
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


def evaluate(df, reps, live_url):
    issues, passed, na = [], [], []
    origin = _origin(live_url)
    host = re.sub(r"^https?://", "", origin)
    addr = _col(df, "Address").str.lower()

    # --- Presence checks (from the crawl) ---
    has_about = bool(addr.str.contains(r"/about|who-we-serve|our-process|meet-the-team|/team").any())
    (passed if has_about else issues).append(
        "About / company page present" if has_about else _issue(
            "about_missing", "About / Company Page", "Medium",
            "No clear About / company page found in the crawl",
            "An About page builds trust and is a key relevance signal for the brand."))
    has_contact = bool(addr.str.contains(r"/contact|book-meeting|/get-in-touch|/schedule").any())
    (passed if has_contact else issues).append(
        "Contact page present" if has_contact else _issue(
            "contact_missing", "Contact Page", "High",
            "No contact / booking page found in the crawl",
            "Without a clear contact path, conversions and local-SEO signals suffer."))

    # --- Soft 404s (indexable 200 HTML that look like error pages) ---
    html_mask = is_html(df)
    status = _num(df, "Status Code").fillna(0).astype(int)
    wc = _num(df, "Word Count").fillna(0)
    title_l = _col(df, "Title 1").str.lower()
    h1_l = _col(df, "H1-1").str.lower()
    err_words = title_l.str.contains("not found|404|page not found") | h1_l.str.contains("not found|404|page not found")
    soft = html_mask & (status == 200) & (wc < 50) & err_words
    if int(soft.sum()) > 0:
        issues.append(_issue("soft_404", "Soft 404", "Medium",
                             "Multiple pages found that return 200 but look like error / empty pages (soft 404)",
                             "Soft 404s waste crawl budget and can be dropped from the index.",
                             reference="\n".join(_col(df, "Address")[soft].head(8).tolist())))
    else:
        passed.append("No soft 404s detected")

    # --- Crawl budget (share of redirects / errors / non-indexable) ---
    total_html = int(html_mask.sum()) or 1
    waste = int((status.between(300, 599) | (_col(df, "Indexability").str.lower() == "non-indexable")).sum())
    if waste / total_html > 0.10:
        issues.append(_issue("crawl_budget", "Crawl Budget", "Low",
                             f"Multiple pages found wasting crawl budget — {waste} of {total_html} crawled URLs are redirects, errors or non-indexable",
                             "Crawl budget spent on dead URLs means money pages get crawled less often."))
    else:
        passed.append(f"Crawl budget healthy ({waste}/{total_html} URLs redirect/error/non-indexable)")

    # --- robots.txt ---
    rb = _get(f"{origin}/robots.txt")
    if rb is not None and rb.status_code == 200:
        body = rb.text
        # a bare "Disallow: /" under a wildcard agent blocks the whole site
        blocked = re.search(r"(?im)^\s*user-agent:\s*\*\s*[\s\S]*?^\s*disallow:\s*/\s*$", body)
        has_sitemap_ref = bool(re.search(r"(?im)^\s*sitemap:\s*http", body))
        if blocked:
            issues.append(_issue("robots_block", "Robots.txt", "Critical",
                                 "Site appears blocked by robots.txt (Disallow: / for all agents)",
                                 "A site-wide robots block prevents Google from crawling and ranking the site."))
        else:
            passed.append("robots.txt present and not blocking the site")
        passed.append("Sitemap referenced in robots.txt" if has_sitemap_ref
                      else "robots.txt present")
    else:
        issues.append(_issue("robots_missing", "Robots.txt", "Low",
                             "No accessible robots.txt found",
                             "A missing robots.txt removes control over crawler access and sitemap discovery."))

    # --- XML sitemap ---
    sm = _get(f"{origin}/sitemap.xml")
    sm2 = sm if (sm is not None and sm.status_code == 200) else _get(f"{origin}/sitemap_index.xml")
    if sm2 is not None and sm2.status_code == 200 and ("<urlset" in sm2.text or "<sitemapindex" in sm2.text):
        passed.append("XML sitemap found and valid")
    else:
        issues.append(_issue("sitemap_missing", "XML Sitemap", "Medium",
                             "No XML sitemap found at /sitemap.xml",
                             "Without a sitemap, search engines may discover and index pages more slowly."))

    # --- Favicon ---
    home = _get(origin + "/")
    fav_html = bool(home is not None and re.search(r'rel=["\'][^"\']*icon', home.text or "", re.I))
    fav_file = _get(f"{origin}/favicon.ico")
    if fav_html or (fav_file is not None and fav_file.status_code == 200):
        passed.append("Favicon present")
    else:
        issues.append(_issue("favicon_missing", "Favicon", "Low",
                             "No favicon detected",
                             "A missing favicon weakens brand recognition in tabs, bookmarks and SERPs."))

    # --- www / non-www + http / https redirection ---
    bare = host[4:] if host.startswith("www.") else "www." + host
    alt = _get(f"https://{bare}/", allow_redirects=False)
    if alt is not None and alt.status_code in (301, 308):
        passed.append("www / non-www variants redirect to one canonical host")
    elif alt is not None and alt.status_code in (302, 307):
        issues.append(_issue("wwwredir_temp", "WWW Redirect", "Low",
                             f"www / non-www handled with a temporary redirect ({alt.status_code}) instead of 301",
                             "Temporary redirects don't consolidate link equity to the canonical host."))
    else:
        issues.append(_issue("wwwredir_missing", "WWW Redirect", "Medium",
                             "www and non-www versions do not redirect to a single canonical host",
                             "Both versions resolving splits link equity and can cause duplicate-content issues."))
    httpr = _get(f"http://{host}/", allow_redirects=False)
    if httpr is not None and httpr.status_code in (301, 308) and "https" in (httpr.headers.get("Location", "")):
        passed.append("HTTP redirects to HTTPS")
    else:
        issues.append(_issue("httpsredir_missing", "HTTPS Redirect", "High",
                             "HTTP does not 301-redirect to HTTPS",
                             "Serving HTTP without forcing HTTPS hurts security signals and can split rankings."))

    # --- Per-rep-page HTML: multiple title/meta + alt text ---
    title_counts, meta_counts, alt_rows = [], [], []
    for ptype, url in reps.items():
        r = _get(url)
        if r is None or r.status_code != 200:
            continue
        h = r.text
        title_counts.append(len(re.findall(r"<title[ >]", h, re.I)))
        meta_counts.append(len(re.findall(r'<meta\s+[^>]*name=["\']description["\']', h, re.I)))
        imgs = re.findall(r"<img\b[^>]*>", h, re.I)
        noalt = [i for i in imgs if not re.search(r'\balt\s*=', i, re.I)]
        if imgs:
            alt_rows.append((url, len(noalt), len(imgs)))

    if title_counts:
        passed.append("Single <title> tag per page") if max(title_counts) <= 1 else issues.append(
            _issue("title_multiple", "Multiple Titles", "Medium",
                   "Multiple pages found with more than one <title> tag",
                   "Multiple titles confuse search engines about the page's primary title."))
    if meta_counts:
        passed.append("Single meta description per page") if max(meta_counts) <= 1 else issues.append(
            _issue("meta_multiple", "Multiple Meta", "Low",
                   "Multiple pages found with more than one meta description tag",
                   "Duplicate meta tags send mixed signals about the page snippet."))
    if alt_rows:
        bad = [r for r in alt_rows if r[1] > 0]
        if bad:
            ex = "; ".join(f"{u} ({n}/{t} missing)" for u, n, t in bad[:5])
            issues.append(_issue("alt_missing", "Alt Tags", "Medium",
                                 f"Multiple pages found with images missing alt text\nEg: {bad[0][0]} ({bad[0][1]}/{bad[0][2]} images missing)",
                                 "Missing alt text hurts accessibility and image-search visibility.",
                                 reference=ex))
            na.append("Full image alt-text audit — evaluated on representative pages only; a complete pass needs the Screaming Frog 'Images' export")
        else:
            passed.append("Images have alt text (representative pages)")

    # --- Not derivable without extra inputs ---
    na.append("Keywords in Title Tags — needs a target-keyword list per page")
    na.append("Keywords in Meta Description — needs a target-keyword list per page")
    na.append("CTA above the fold — assessed qualitatively under the CRO findings (see Call-to-Action)")

    return {"issues": issues, "passed": passed, "na": na}


def _issue(key, category, priority, observation, impact, reference="-"):
    return {"key": key, "category": category, "priority": priority,
            "observation": observation, "impact": impact, "reference": reference}
