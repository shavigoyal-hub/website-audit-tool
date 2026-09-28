"""Ask Claude to phrase a manual finding as proper Gushwork audit copy.

The chatbot passes each line (URL + CS note) here; we fetch the page,
give Claude the HTML head/body snippet and the CS reviewer's rough note,
and get back a structured finding: label / priority / hook_stat /
hook_ctx / costs / support / category. Falls back to canonical HOOK_COPY
when ANTHROPIC_API_KEY is unset.
"""
import json
import os
import re

import requests

MODEL = os.environ.get("CHATBOT_MODEL", "claude-haiku-4-5-20251001")

_SYSTEM = """You are Gushwork's SEO audit copywriter. Turn a CS reviewer's
rough note plus a page's HTML into one finding, in this EXACT JSON shape:

{
  "label":     "2-4 word status pill (e.g. 'No top menu', 'Flat structure')",
  "priority":  "Critical | High | Medium | Low",
  "hook_stat": "'-24%', '+15%', '0%', '+3 leads/mo' — the leading number, no context",
  "hook_ctx":  "ONE short sentence, starts lowercase, ends with a period. Says what the number MEANS. Uses 'Google', 'ranking', 'leads', 'crawl', 'LLM' language.",
  "costs":     "1-2 sentences (<40 words) of business consequence. Direct, no fluff.",
  "support":   "One backing stat or citation, <20 words. Empty string if none.",
  "category":  "H1 Tags | Meta Description | Title Tags | Schema | Content | Site Architecture | LLM Citation | Page Speed | Errors | Custom",
  "verified":  true if the HTML confirms the issue, false if you couldn't verify from the HTML
}

STYLE RULES (hard):
- No em dashes anywhere.
- No markdown. No bullet points. Plain sentences.
- Speak to a business owner, not a developer.
- Prefer leads / ranking / trust framing over jargon.
- Output ONLY the JSON object, nothing before or after.
"""


def _fetch_html(url):
    if not url:
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 Gushwork-Audit"},
                         timeout=10, allow_redirects=True)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def _snippet(html, limit=6000):
    if not html:
        return ""
    # Head + a slice of body — enough to see title/meta/H1/canonical/schema
    head_m = re.search(r"<head[^>]*>(.*?)</head>", html, re.I | re.S)
    head = head_m.group(1) if head_m else html[:2000]
    body_m = re.search(r"<body[^>]*>(.*?)</body>", html, re.I | re.S)
    body = body_m.group(1)[:3000] if body_m else ""
    return (head[:3000] + "\n\n<!-- body sample -->\n" + body)[:limit]


def frame(url, hint):
    """Return dict of finding fields, or None if LLM disabled / call fails."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    html = _fetch_html(url)
    snippet = _snippet(html)
    user = (
        f"URL: {url or '(no URL)'}\n"
        f"CS reviewer note: {hint or '(no note)'}\n\n"
        f"HTML snippet (head + first 3k of body):\n{snippet}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 700,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=30,
        )
        if not r.ok:
            return None
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        return json.loads(text[start:end + 1])
    except Exception:
        return None
