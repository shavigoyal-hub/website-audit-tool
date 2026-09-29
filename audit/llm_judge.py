"""LLM judgement pass over raw pipeline findings.

Turns the rule-based, templated findings from sf_csv / parameters / PSI
into Gushwork-voice copy with real judgement — same quality as when a
CS reviewer prompts Claude directly in chat.

Usage from audit.pipeline.run:
    from audit import llm_judge
    rows = llm_judge.enrich(rows, live_url)

Provider auto-detects:
    OPENAI_API_KEY set  → GPT (default: gpt-4o-mini)
    ANTHROPIC_API_KEY   → Claude (default: haiku 4.5)
    Neither             → returns rows unchanged (no-op)

Env overrides:
    JUDGE_MODEL    — override default model
    JUDGE_MAX_ROWS — cap how many rows to enrich (default 20)
"""
import json
import os
import re

import requests


_SYSTEM_PROMPT = """You are Gushwork's SEO audit copywriter. You receive one
finding at a time from a technical audit tool. Rewrite it in Gushwork's voice
using the HTML evidence provided.

Return ONLY valid JSON matching this schema, no explanation:

{
  "category":  "clean noun phrase, NO numbers/counts (bad: 'Meta Descriptions Missing on 3 Pages'; good: 'Meta Descriptions Missing'). Say it in client language, not SEO jargon.",
  "label":     "2-4 word status pill for the per-URL badge (eg 'No H1', 'Truncated title', 'Slow LCP')",
  "priority":  "Critical | High | Medium | Low — judge based on business impact for THIS site, not templated",
  "hook_stat": "specific number tied to what you found ('-32%', '+15%', '0%', '7.0s LCP'). No generic '-15%' when you can be specific.",
  "hook_ctx":  "one sentence, starts lowercase, ends with period. Says what the number means in leads/ranking/LLM terms.",
  "observation": "EXACT format: 'Multiple pages have <5-8 word issue>\\neg:\\n<url>\\n<url>'. If single page: 'The homepage has <issue>\\neg: <url>'. No paragraphs, no benchmarks, no prescriptive fixes, no mechanism explanations.",
  "costs":     "1-2 short sentences of business consequence. Direct, no em-dashes.",
  "support":   "one line: a supporting stat or citation. Empty string if none.",
  "insight":   "one extra insight you noticed while reading the HTML that the original finding missed. Empty string if none.",
  "impact":    "2-10 words, ONE consequence. Approved patterns: 'Impacts Ranking', 'Impacts leads', 'Wastes crawl budget', 'Splits ranking signals', 'May impact rich results / LLM citation', 'Hurts local pack', 'Kills brand credibility', 'Breaks SERP snippet', 'Slow LCP demotes rankings', 'Thin pages can't rank'."
}

STYLE (hard rules):
- No em dashes anywhere. Use commas.
- No markdown. No bullets.
- Speak to a business owner, not a developer.
- Prefer 'leads', 'ranking', 'LLM citation', 'trust' framing over jargon.
- Category avoids internal SEO jargon: not 'money pages', 'SERP snippet', 'orphan pages', 'index bloat' — use 'Pages', 'Google search result', 'pages not linked from anywhere', 'extra pages Google is crawling'.
- If the HTML disproves the finding, still return JSON but set priority=Low.
- Vendor product names → generic: ChatGPT/Perplexity/Claude/AI Overviews → 'LLM citation'; Local Pack/GBP → 'local pack'; GPTBot/ClaudeBot → 'LLM crawlers'.

NEVER FLAG (return category='SKIP' and priority='Low' if forced to answer):
- /llms.txt missing (not an SEO parameter)
- og:image missing (social preview, not SEO)
- LCP / thin content / meta / H1 issues on /contact, /apply, /book, /schedule, /demo pages — these are CRO, not SEO
- www vs non-www or trailing-slash duplicates when canonical is set correctly
- Flat URL structure (unless there are collisions or duplicate content at multiple paths)
- 'Rendering not verified' on WordPress/Squarespace/Wix/Shopify/Webflow/Ghost/Craft/Kirby — those are server-rendered

If the finding hits one of the NEVER FLAG rules, set category='SKIP' and the pipeline will drop it.
"""


def _client_ctx():
    """Return (mode, model, api_key) — mode in {'openai','anthropic',None}."""
    override_model = os.environ.get("JUDGE_MODEL", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if openai_key:
        return "openai", override_model or "gpt-4o-mini", openai_key
    if anthropic_key:
        return "anthropic", override_model or "claude-haiku-4-5-20251001", anthropic_key
    return None, None, None


def _fetch_snippet(url, limit=5000):
    if not url:
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 Gushwork-Audit"},
                         timeout=12, allow_redirects=True)
    except Exception:
        return ""
    if r.status_code != 200:
        return f"(HTTP {r.status_code} — bot-blocked or unavailable)"
    html = r.text
    head_m = re.search(r"<head[^>]*>(.*?)</head>", html, re.I | re.S)
    head = head_m.group(1)[:2500] if head_m else html[:2000]
    body_m = re.search(r"<body[^>]*>(.*?)</body>", html, re.I | re.S)
    body = body_m.group(1)[:2500] if body_m else ""
    return (head + "\n\n<!-- body sample -->\n" + body)[:limit]


def _first_url_from(row, live_url):
    """Pick the first http(s) URL out of the finding's reference/observation."""
    for candidate in (row.get("reference"), row.get("observation"), row.get("found")):
        if not candidate:
            continue
        m = re.search(r"https?://\S+", str(candidate))
        if m:
            return m.group(0).rstrip(".,;)|")
    return live_url


def _call_openai(prompt, model, key):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "max_tokens": 700,
        },
        timeout=30,
    )
    if not r.ok:
        return None
    text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
    return _parse_json(text)


def _call_anthropic(prompt, model, key):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": 700,
              "system": _SYSTEM_PROMPT,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    if not r.ok:
        return None
    text = "".join(b.get("text", "") for b in r.json().get("content", []))
    return _parse_json(text)


def _parse_json(text):
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _enrich_row(row, live_url, mode, model, key):
    target_url = _first_url_from(row, live_url)
    snippet = _fetch_snippet(target_url)
    prompt = (
        f"Site homepage: {live_url}\n"
        f"URL under review: {target_url}\n\n"
        f"Tool-generated finding:\n"
        f"  category:  {row.get('category', '')}\n"
        f"  observation: {row.get('observation', '')}\n"
        f"  priority (tool guess): {row.get('priority', '')}\n"
        f"  impact (tool guess): {row.get('impact', '')}\n\n"
        f"HTML evidence (head + body sample):\n{snippet}\n"
    )
    if mode == "openai":
        return _call_openai(prompt, model, key)
    return _call_anthropic(prompt, model, key)


def _apply_judgement(row, judgement):
    if not judgement:
        return row
    new = dict(row)
    for k_llm, k_row in (
        ("category", "category"),
        ("priority", "priority"),
        ("observation", "observation"),
        ("hook_stat", "hook_stat"),
        ("hook_ctx", "hook_ctx"),
        ("costs", "costs"),
        ("support", "support"),
        ("label", "_status_label"),
    ):
        v = judgement.get(k_llm)
        if isinstance(v, str):
            v = v.strip()
        if v:
            new[k_row] = v
    insight = judgement.get("insight")
    if isinstance(insight, str):
        insight = insight.strip()
    if insight and "insight" not in (new.get("observation") or "").lower():
        new["observation"] = (new.get("observation") or "").rstrip() + f"\nInsight: {insight}"
    new["_llm_enriched"] = True
    return new


def enrich(rows, live_url):
    """Return `rows` with LLM-generated fields applied. No-op if no API key.

    Runs LLM calls in parallel (default 5 workers). Cuts a 20-finding pass
    from ~40s of serial GPT calls down to ~8-12s.
    """
    mode, model, key = _client_ctx()
    if not mode:
        return rows
    cap = int(os.environ.get("JUDGE_MAX_ROWS", "20"))
    workers = int(os.environ.get("JUDGE_WORKERS", "5"))
    to_judge = list(enumerate(rows[:cap]))
    passthrough = list(enumerate(rows[cap:], start=cap))

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_to_idx = {
            ex.submit(_enrich_row, r, live_url, mode, model, key): i
            for i, r in to_judge
        }
        for fut in as_completed(fut_to_idx):
            i = fut_to_idx[fut]
            try:
                results[i] = fut.result()
            except Exception:
                results[i] = None

    out = []
    enriched = 0
    skipped = 0
    kept_map = {}  # original index -> final row
    for i, r in to_judge:
        j = results.get(i)
        if j:
            # Drop findings the LLM marked as SKIP per Direct-chat never-flag rules
            if isinstance(j.get("category"), str) and j["category"].strip().upper() == "SKIP":
                skipped += 1
                continue
            kept_map[i] = _apply_judgement(r, j)
            enriched += 1
        else:
            kept_map[i] = r
    for i, r in passthrough:
        kept_map[i] = r
    # Preserve original order
    for i in sorted(kept_map.keys()):
        out.append(kept_map[i])
    if enriched or skipped:
        print(f"[judge] enriched {enriched}, skipped {skipped}, kept {len(out)}/{len(rows)} findings via {mode}:{model}")
    return out
