"""
Lightweight Python site crawler — produces a DataFrame in Screaming Frog
Internal:All format so the audit can run without SF installed.

Columns produced (subset SF uses):
  Address, Content Type, Status Code, Redirect URL,
  Indexability, Indexability Status,
  Meta Robots 1, X-Robots-Tag 1,
  Title 1, Title 1 Length,
  Meta Description 1, Meta Description 1 Length,
  H1-1, H1-1 Length, H1-2,
  Canonical Link Element 1,
  Size (Bytes), Crawl Depth, Word Count
"""
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (compatible; GushworkAuditBot/1.0; "
    "+https://gushwork.ai/bot)"
)
_HEADERS = {"User-Agent": _UA}
_TIMEOUT = 15
_MAX_WORKERS = 8
_MAX_URLS = 750


def _same_origin(base_netloc, url):
    p = urlparse(url)
    return p.netloc.lstrip("www.") == base_netloc.lstrip("www.")


def _parse_page(url, resp):
    """Extract all SEO fields from a successful HTML response."""
    content_type = resp.headers.get("Content-Type", "")
    size = len(resp.content)
    x_robots = resp.headers.get("X-Robots-Tag", "")

    is_html = "text/html" in content_type
    row = {
        "Address": url,
        "Content Type": content_type.split(";")[0].strip(),
        "Status Code": resp.status_code,
        "Redirect URL": "",
        "Size (Bytes)": size,
        "X-Robots-Tag 1": x_robots,
        "Meta Robots 1": "",
        "Indexability": "Indexable",
        "Indexability Status": "",
        "Title 1": "",
        "Title 1 Length": 0,
        "Meta Description 1": "",
        "Meta Description 1 Length": 0,
        "H1-1": "",
        "H1-1 Length": 0,
        "H1-2": "",
        "Canonical Link Element 1": "",
        "Word Count": 0,
    }

    if not is_html:
        return row, []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Meta robots
    meta_robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    mr = meta_robots["content"].strip() if meta_robots and meta_robots.get("content") else ""
    row["Meta Robots 1"] = mr

    # Indexability
    noindex = (
        "noindex" in mr.lower()
        or "noindex" in x_robots.lower()
    )
    if noindex:
        row["Indexability"] = "Non-Indexable"
        row["Indexability Status"] = "noindex"

    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    row["Title 1"] = title
    row["Title 1 Length"] = len(title)

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    desc = meta_desc["content"].strip() if meta_desc and meta_desc.get("content") else ""
    row["Meta Description 1"] = desc
    row["Meta Description 1 Length"] = len(desc)

    # H1s
    h1_tags = soup.find_all("h1")
    h1 = h1_tags[0].get_text(strip=True) if h1_tags else ""
    h1b = h1_tags[1].get_text(strip=True) if len(h1_tags) > 1 else ""
    row["H1-1"] = h1
    row["H1-1 Length"] = len(h1)
    row["H1-2"] = h1b

    # Canonical
    canon_tag = soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
    canon = canon_tag["href"].strip() if canon_tag and canon_tag.get("href") else ""
    row["Canonical Link Element 1"] = canon

    # Word count (body text)
    body = soup.find("body")
    if body:
        text = body.get_text(separator=" ", strip=True)
        row["Word Count"] = len(text.split())

    # Internal links to follow
    base_netloc = urlparse(url).netloc
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        abs_href, _ = urldefrag(urljoin(url, href))
        if _same_origin(base_netloc, abs_href):
            links.append(abs_href)

    return row, links


def _fetch(session, url):
    try:
        resp = session.get(url, headers=_HEADERS, timeout=_TIMEOUT,
                           allow_redirects=False)
        return url, resp, None
    except Exception as exc:
        return url, None, exc


def crawl(start_url, max_urls=_MAX_URLS):
    """
    BFS crawl starting at `start_url`.
    Returns a list of row dicts compatible with SF's Internal:All export.
    """
    parsed = urlparse(start_url)
    base_netloc = parsed.netloc
    origin = f"{parsed.scheme}://{parsed.netloc}"

    seen = {start_url}
    queue = deque([(start_url, 0)])   # (url, depth)
    rows = []

    session = requests.Session()
    session.max_redirects = 0   # we handle redirects manually

    while queue and len(rows) < max_urls:
        batch = []
        while queue and len(batch) < _MAX_WORKERS * 2:
            batch.append(queue.popleft())

        futures = {}
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
            for url, depth in batch:
                futures[ex.submit(_fetch, session, url)] = (url, depth)

        for fut in as_completed(futures):
            url, depth = futures[fut]
            fetched_url, resp, exc = fut.result()

            if exc or resp is None:
                rows.append({
                    "Address": url, "Content Type": "", "Status Code": 0,
                    "Redirect URL": "", "Size (Bytes)": 0, "X-Robots-Tag 1": "",
                    "Meta Robots 1": "", "Indexability": "Non-Indexable",
                    "Indexability Status": "fetch error",
                    "Title 1": "", "Title 1 Length": 0,
                    "Meta Description 1": "", "Meta Description 1 Length": 0,
                    "H1-1": "", "H1-1 Length": 0, "H1-2": "",
                    "Canonical Link Element 1": "", "Word Count": 0,
                    "Crawl Depth": depth,
                })
                continue

            # Redirect
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location", "")
                abs_loc, _ = urldefrag(urljoin(url, loc))
                row = {
                    "Address": url, "Content Type": "",
                    "Status Code": resp.status_code,
                    "Redirect URL": abs_loc,
                    "Size (Bytes)": 0, "X-Robots-Tag 1": "",
                    "Meta Robots 1": "", "Indexability": "Non-Indexable",
                    "Indexability Status": f"{resp.status_code} Redirect",
                    "Title 1": "", "Title 1 Length": 0,
                    "Meta Description 1": "", "Meta Description 1 Length": 0,
                    "H1-1": "", "H1-1 Length": 0, "H1-2": "",
                    "Canonical Link Element 1": "", "Word Count": 0,
                    "Crawl Depth": depth,
                }
                rows.append(row)
                # Follow the redirect if it stays on-site
                if _same_origin(base_netloc, abs_loc) and abs_loc not in seen:
                    seen.add(abs_loc)
                    queue.append((abs_loc, depth + 1))
                continue

            row, links = _parse_page(url, resp)
            row["Crawl Depth"] = depth
            rows.append(row)

            for link in links:
                if link not in seen and len(seen) < max_urls * 2:
                    # Skip non-HTML resources
                    ext = urlparse(link).path.rsplit(".", 1)[-1].lower()
                    if ext in {"jpg", "jpeg", "png", "gif", "svg", "webp",
                               "pdf", "zip", "css", "js", "ico", "woff", "woff2"}:
                        continue
                    seen.add(link)
                    queue.append((link, depth + 1))

        time.sleep(0.05)   # gentle rate-limit between batches

    return rows
