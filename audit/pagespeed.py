"""PageSpeed Insights API client + Core Web Vitals extraction."""
import base64
import os
import time

import requests

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def _audit_num(audits, key):
    a = audits.get(key, {})
    return a.get("numericValue")


def fetch(url, strategy="mobile", api_key=None, retries=2):
    api_key = api_key or os.environ.get("PAGESPEED_API_KEY")
    params = {"url": url, "strategy": strategy, "category": "performance"}
    if api_key:
        params["key"] = api_key
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(ENDPOINT, params=params, timeout=90)
            if r.status_code == 200:
                return _parse(url, strategy, r.json())
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    return {"url": url, "strategy": strategy, "error": last}


def _parse(url, strategy, data):
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    perf = lh.get("categories", {}).get("performance", {}).get("score")
    opps = []
    for k, a in audits.items():
        details = a.get("details", {})
        if details.get("type") == "opportunity" and (a.get("score") is not None and a["score"] < 0.9):
            saving = details.get("overallSavingsMs", 0)
            if saving and saving > 150:
                opps.append((a.get("title", k), round(saving)))

    # Extract Lighthouse final-screenshot (base64 WebP thumbnail of the page at end of load).
    # Stored in the result dict so callers can upload to Drive / Sheets.
    screenshot_b64 = None
    fs = audits.get("final-screenshot", {})
    fs_data = fs.get("details", {}).get("data", "")
    if fs_data and fs_data.startswith("data:"):
        # Strip the data-URI prefix → raw base64 bytes
        screenshot_b64 = fs_data.split(",", 1)[-1]

    return {
        "url": url,
        "strategy": strategy,
        "performance_score": round(perf * 100) if perf is not None else None,
        "lcp_s": _to_s(_audit_num(audits, "largest-contentful-paint")),
        "fcp_s": _to_s(_audit_num(audits, "first-contentful-paint")),
        "tbt_ms": _audit_num(audits, "total-blocking-time"),
        "cls": _audit_num(audits, "cumulative-layout-shift"),
        "si_s": _to_s(_audit_num(audits, "speed-index")),
        "opportunities": sorted(opps, key=lambda x: -x[1])[:6],
        "screenshot_b64": screenshot_b64,  # base64 WebP; None if not present
        "error": None,
    }


def _to_s(ms):
    return round(ms / 1000.0, 1) if ms is not None else None


def fetch_many(reps, strategy, api_key):
    """reps = {page_type: url}. Returns {page_type: result}."""
    out = {}
    for ptype, url in reps.items():
        out[ptype] = fetch(url, strategy=strategy, api_key=api_key)
        time.sleep(0.5)
    return out


def save_screenshot(result, out_path):
    """Write the Lighthouse screenshot to a PNG/WebP file. Returns path or None."""
    b64 = result.get("screenshot_b64")
    if not b64:
        return None
    img_bytes = base64.b64decode(b64)
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    return out_path
