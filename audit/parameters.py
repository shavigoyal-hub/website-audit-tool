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

    # --- Open Graph tags (fetch homepage) ---
    og_req = _get(origin + "/")
    if og_req is not None and og_req.status_code == 200:
        html = og_req.text
        has_og_title = bool(re.search(r'property=["\']og:title["\']', html, re.I))
        has_og_desc  = bool(re.search(r'property=["\']og:description["\']', html, re.I))
        has_og_image = bool(re.search(r'property=["\']og:image["\']', html, re.I))
        if has_og_title and has_og_desc and has_og_image:
            passed.append("Open Graph tags present (og:title, og:description, og:image)")
        else:
            missing = [t for t, ok in [("og:title", has_og_title), ("og:description", has_og_desc), ("og:image", has_og_image)] if not ok]
            issues.append(_issue("og_missing", "Social / OG Tags", "Medium",
                                 f"Homepage is missing Open Graph tags: {', '.join(missing)}",
                                 "Missing OG tags produce blank link previews when the page is shared on LinkedIn, WhatsApp, or social media.",
                                 reference=origin + "/"))
    else:
        na.append("Open Graph tags : could not fetch homepage")

    # --- Hreflang: detect language subdirectories (e.g. /fr/, /de/, /es/) ---
    lang_dirs = addr_l.str.extract(r"/(fr|de|es|pt|it|nl|ar|zh|ja|ko|pl|ru|tr|sv|da|fi|no|cs|hu|ro|th|vi|id)(/|$)")[0].dropna().unique().tolist()
    if lang_dirs:
        # Check if any crawled page has hreflang — SF would include it as a column if present
        hreflang_col = next((c for c in df.columns if "hreflang" in c.lower()), None)
        has_hreflang = bool(hreflang_col and _col(df, hreflang_col).str.strip().ne("").any())
        if has_hreflang:
            passed.append(f"Hreflang tags present for language variants ({', '.join(lang_dirs)})")
        else:
            issues.append(_issue("hreflang_missing", "Hreflang", "High",
                                 f"Site has language subdirectories ({', '.join('/' + l + '/' for l in lang_dirs)}) but no hreflang tags detected",
                                 "Without hreflang, Google cannot serve the correct language version to users, diluting rankings across locales."))
    else:
        passed.append("No multi-language subdirectories detected (hreflang not required)")

    # --- FAQ check on service / product pages ---
    service_urls = [u for u in addr.tolist() if any(k in u.lower() for k in ("service", "product", "solutions", "capabilities"))]
    if service_urls:
        faq_page = service_urls[0]
        faq_req = _get(faq_page)
        if faq_req is not None and faq_req.status_code == 200:
            html = faq_req.text
            has_faq_schema = bool(re.search(r'"@type"\s*:\s*"FAQPage"', html))
            has_faq_section = bool(re.search(r'(?i)(?:frequently asked questions|<h[2-4][^>]*>\s*faq)', html))
            if has_faq_schema:
                passed.append(f"FAQPage schema present on service pages ({faq_page})")
            elif has_faq_section:
                issues.append(_issue("faq_missing", "FAQ / Schema", "Medium",
                                     f"FAQ section found but no FAQPage schema markup on service pages",
                                     "Adding FAQPage JSON-LD unlocks FAQ rich results in search, increasing visibility without ranking changes.",
                                     reference=faq_page))
            else:
                issues.append(_issue("faq_missing", "FAQ / Schema", "Medium",
                                     f"Service pages found with no FAQ section",
                                     "FAQ sections address buyer objections on the page and can unlock FAQ rich results in search.",
                                     reference=faq_page))
        else:
            na.append(f"FAQ check : could not fetch {faq_page}")
    else:
        na.append("FAQ check : no service/product pages found in crawl")

    # --- CTA above the fold (basic DOM check — mobile requires visual review) ---
    if og_req is not None and og_req.status_code == 200:
        html_home = og_req.text
        cta_pattern = re.compile(r'(?:get.?a?.?quote|contact|free.?quote|call.?us|get.?started|book|schedule|enquir|request)', re.I)
        top_html = html_home[:6000]
        links = re.findall(r'<a[^>]*>(.*?)</a>', top_html, re.DOTALL)
        buttons = re.findall(r'<button[^>]*>(.*?)</button>', top_html, re.DOTALL)
        cta_texts = [re.sub('<[^>]+>', '', t).strip() for t in links + buttons]
        visible_ctas = [t for t in cta_texts if cta_pattern.search(t) and len(t) < 60]
        if visible_ctas:
            passed.append(f"CTA found in early page HTML: {visible_ctas[0]}")
        else:
            na.append("CTA above the fold : no CTA button detected in homepage HTML — verify mobile hero manually (mobile viewport may hide desktop CTAs)")

    # --- Not derivable without extra inputs ---
    na.append("Keywords in Title Tags : needs a target-keyword list per page")
    na.append("Keywords in Meta Description : needs a target-keyword list per page")
    na.append("Full image alt-text audit : needs Screaming Frog 'Images' export")

    return {"issues": issues, "passed": passed, "na": na}


def _issue(key, category, priority, observation, impact, reference="-"):
    return {"key": key, "category": category, "priority": priority,
            "observation": observation, "impact": impact, "reference": reference}
