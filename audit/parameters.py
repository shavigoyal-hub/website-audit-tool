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

from audit.sf_csv import _col, is_html, _num, is_non_seo

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
    has_about = bool(addr_l.str.contains(
        r"about|who-we-serve|our-process|meet-the-team|/team|our-story|company",
        regex=True).any())
    # Fallback: crawl might have missed the URL. Also check the homepage's
    # own anchor list and probe a wider set of paths.
    if not has_about:
        try:
            _hp = _get(f"{origin}/")
            _hp_text = (_hp.text or "").lower() if _hp and _hp.status_code == 200 else ""
            if re.search(r'href=["\'][^"\']*(?:about|our-story|our-company|who-we-are)[^"\']*["\']', _hp_text):
                has_about = True
        except Exception:
            pass
    if not has_about:
        # Probe wider set including .asp/.htm/.php that older sites use
        for _p in ["/about", "/about-us", "/about.html", "/aboutus.asp",
                   "/aboutus.php", "/aboutus.htm", "/our-story", "/our-company",
                   "/who-we-are", "/company", "/team"]:
            _r = _get(f"{origin}{_p}")
            if _r is not None and _r.status_code == 200:
                has_about = True
                break
    if has_about:
        passed.append("About / company page present")
    else:
        # Show which common About-page paths we tried and their status —
        # clearer for CS than 'homepage | No About page'.
        _about_paths = ["/about", "/about-us", "/about.html", "/aboutus.asp",
                        "/aboutus.php", "/our-company", "/who-we-are",
                        "/company", "/team", "/our-story"]
        _about_probe = []
        for _p in _about_paths:
            _r = _get(f"{origin}{_p}")
            _sc = _r.status_code if _r is not None else "no response"
            _about_probe.append(f"{origin}{_p} → {_sc}")
        issues.append(_issue(
            "about_missing", "About / Company Page", "High",
            "No About / company page — all common paths return 404 and no homepage link points to one",
            "A missing About page weakens brand trust signals.",
            reference=_about_probe))
    has_contact = bool(addr_l.str.contains(
        r"contact|book-meeting|/get-in-touch|/schedule|reach-us|get-a-quote",
        regex=True).any())
    if not has_contact:
        try:
            _hp2 = _get(f"{origin}/")
            _hp2_text = (_hp2.text or "").lower() if _hp2 and _hp2.status_code == 200 else ""
            if re.search(r'href=["\'][^"\']*(?:contact|get-in-touch|reach-us|get-a-quote)[^"\']*["\']', _hp2_text):
                has_contact = True
        except Exception:
            pass
    if not has_contact:
        for _p in ["/contact", "/contact-us", "/contact.html",
                   "/contactus.asp", "/contactus.php", "/contactus.htm",
                   "/get-in-touch", "/reach-us"]:
            _r = _get(f"{origin}{_p}")
            if _r is not None and _r.status_code == 200:
                has_contact = True
                break
    (passed if has_contact else issues).append(
        "Contact page present" if has_contact else _issue(
            "contact_missing", "Contact Page", "High",
            "No contact / booking page — neither crawled nor probed at common paths, and no homepage link points to one",
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
        body = rb.text or ""
        # 'Empty robots' (0-byte body or whitespace-only) is functionally
        # identical to 'no robots' — carries no crawl directives, no sitemap
        # reference. Roll both into one finding.
        if not body.strip():
            issues.append(_issue("robots_missing", "Robots.txt", "Low",
                                 "robots.txt returns 200 but is empty — carries no crawl directives",
                                 "A missing / empty robots.txt removes control over crawler access."))
        else:
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
                             "A missing / empty robots.txt removes control over crawler access."))

    # --- XML sitemap ---
    _sm_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                 "/sitemap.gz", "/sitemap1.xml"]
    _sm_probe = []
    _sm_found = None
    for _p in _sm_paths:
        _r = _get(f"{origin}{_p}")
        _sc = _r.status_code if _r is not None else "no response"
        _sm_probe.append(f"{origin}{_p} → {_sc}")
        if (_r is not None and _r.status_code == 200
                and ("<urlset" in (_r.text or "") or "<sitemapindex" in (_r.text or ""))):
            _sm_found = _r
            break
    if _sm_found is not None:
        passed.append("XML sitemap found and valid")
    else:
        issues.append(_issue(
            "sitemap_missing", "XML Sitemap", "Critical",
            "No XML sitemap served at any standard path",
            "Without a sitemap, Google discovers new pages up to 2x slower.",
            reference=_sm_probe))

    # --- Favicon ---
    # Detection is broad: any <link rel="...icon..."> in the homepage HTML, OR
    # a 200 on any of the common favicon paths. A blocked or unreachable
    # homepage (403/None) is treated as inconclusive rather than "missing".
    home = _get(origin + "/")
    fav_html = bool(home is not None and re.search(
        r'<link[^>]+rel=["\'][^"\']*(?:icon|shortcut icon|apple-touch-icon|mask-icon)[^"\']*["\']',
        home.text or "", re.I))
    fav_paths = [
        "/favicon.ico", "/favicon.png", "/favicon.svg",
        "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
    ]
    fav_file_ok = False
    for p in fav_paths:
        r = _get(f"{origin}{p}")
        if r is not None and r.status_code == 200 and (r.headers.get("Content-Type", "").startswith("image/") or p.endswith(".ico")):
            fav_file_ok = True
            break
    homepage_blocked = (home is None) or (home.status_code in (401, 403, 405, 429))
    if fav_html or fav_file_ok:
        passed.append("Favicon present")
    elif homepage_blocked:
        na.append("Favicon (homepage fetch blocked, not evaluated)")
    else:
        issues.append(_issue("favicon_missing", "Favicon", "Low",
                             "No favicon detected",
                             "A missing favicon weakens brand recognition in tabs and search."))

    # HTTP + www redirect checks removed per CS review — the probe kept
    # producing false positives on sites that route through CDNs / edge
    # workers with non-301 (but valid) redirect chains.

    # ── Viewport / pinch-zoom accessibility ──────────────────────────
    if home is not None and (home.text or "") and not homepage_blocked:
        vm = re.search(r'<meta[^>]+name=["\']viewport["\'][^>]+content=["\']([^"\']+)["\']',
                       home.text, re.I)
        if vm:
            vc = vm.group(1).lower()
            if "user-scalable=no" in vc or "user-scalable=0" in vc or "maximum-scale=1" in vc:
                issues.append(_issue("viewport_pinch_zoom_blocked", "Viewport", "Medium",
                                     "Viewport meta blocks pinch-to-zoom on mobile",
                                     "Blocking pinch zoom fails Google's mobile-friendly test and hurts accessibility.",
                                     reference=[f"viewport content: {vc}"]))
            else:
                passed.append("Viewport allows pinch zoom")

    # ── Dead nav links (href='#' inside site header) ─────────────────
    if home is not None and (home.text or "") and not homepage_blocked:
        nav_m = re.search(r'<(?:nav|header)[^>]*>(.*?)</(?:nav|header)>',
                          home.text, re.I | re.S)
        nav_html = nav_m.group(1) if nav_m else ""
        dead = re.findall(r'<a[^>]+href=["\'](#|javascript:void\(0\))["\']', nav_html, re.I)
        if len(dead) >= 1:
            issues.append(_issue("dead_nav_links", "Navigation", "High",
                                 f"{len(dead)} dead link(s) in the primary navigation (href='#' or javascript:void)",
                                 "Dead nav links break the money-page crawl path and hurt UX.",
                                 reference=[f"{len(dead)} dead nav anchor(s) on homepage"]))
        elif nav_html:
            passed.append("Navigation links resolve to real pages")

    # www / non-www and HTTP→HTTPS redirect checks removed per CS review.
    # SF-crawl-data variants produced too many false positives on sites
    # behind CDNs; the active-probe versions were removed above too.

    # --- Homepage-level probes: schema, CTA, conversion path ---
    og_req = _get(origin + "/")
    if og_req is not None and og_req.status_code == 200:
        home_html = og_req.text or ""
        home_html_lower = home_html.lower()

        # Structured data — sample a handful of SEO pages (not just the
        # homepage) so the finding reflects the WHOLE site, not just one URL.
        # If zero pages ship ld+json, flag it site-wide with multiple
        # example URLs so CS can see this isn't a one-page omission.
        _schema_sample = [origin + "/"]
        try:
            _addr_sample = addr[~is_non_seo(df) & is_html(df)].tolist()
            # Prefer different URL depths: 1 homepage + 3 inner pages
            seen_paths = {"/"}
            for u in _addr_sample:
                p = re.sub(r"^https?://[^/]+", "", u).split("?")[0]
                if p and p not in seen_paths:
                    _schema_sample.append(u)
                    seen_paths.add(p)
                if len(_schema_sample) >= 4:
                    break
        except Exception:
            pass
        _pages_with_schema = []
        _pages_without_schema = []
        for _u in _schema_sample:
            _r = _get(_u) if _u != origin + "/" else og_req
            if _r is None or _r.status_code != 200:
                continue
            if "application/ld+json" in (_r.text or "").lower():
                _pages_with_schema.append(_u)
            else:
                _pages_without_schema.append(_u)
        if _pages_without_schema and not _pages_with_schema:
            issues.append(_issue(
                "structured_data", "Schema", "High",
                "No page ships any ld+json schema (no Organization, Service, Product, FAQPage, or BreadcrumbList)",
                "Without any schema, Google can't render rich results and LLMs miss key business context.",
                reference=_pages_without_schema))
        # Conversion path (form / mailto / tel / clear CTA button link).
        has_form   = bool(re.search(r"<form[\s>]", home_html, re.I))
        has_mailto = "mailto:" in home_html_lower
        has_tel    = "tel:" in home_html_lower
        has_cta_link = bool(re.search(
            r'<a[^>]+href=["\'][^"\']*(?:contact|book|schedule|demo|get-started|get-in-touch|apply|request|consultation)',
            home_html, re.I))
        if not (has_form or has_mailto or has_tel or has_cta_link):
            issues.append(_issue("cta_missing", "Conversion Path", "Critical",
                                 "No form, no mailto, no tel link, and no clear CTA button on the homepage",
                                 "Visitors ready to buy have no way to make contact.",
                                 reference=origin + "/"))

    # --- Open Graph tags (fetch homepage) ---
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
