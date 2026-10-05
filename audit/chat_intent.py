"""LLM-based intent router for the audit chatbot.

Given a free-form message, decide what the user is asking for and return
a structured action the /chat endpoint can execute:

  {"action": "add_finding",
   "findings": [{"url": "...", "hint": "..."}]}

  {"action": "edit_parameter",
   "edits": [{"key": "title_duplicate", "field": "primary_signal",
              "value": "Lead"}]}

  {"action": "unknown", "reason": "..."}

Never raises. Returns {"action": "unknown", ...} on any failure so the
caller can fall back to the legacy line-based parser.
"""
import json
import os
import re

import requests

from audit.hook_copy import HOOK_COPY, STATUS_LABEL

_PARAM_FIELDS = {"label", "priority", "primary_signal", "hook_stat",
                 "hook_ctx", "costs", "support", "in_lead_sum"}


def _keys_summary():
    """One-line hint per HOOK_COPY key for the LLM's grounding."""
    lines = []
    for k in sorted(HOOK_COPY.keys()):
        lbl = (STATUS_LABEL.get(k) or (k, ""))[0]
        lines.append(f"  {k}: {lbl}")
    return "\n".join(lines)


_SYSTEM = """You are the router for an SEO-audit chatbot. The user types a
message; classify it and return STRICT JSON with ONE of these shapes:

1. Adding findings to the current audit sheet:
   {"action": "add_finding",
    "findings": [{"url": "<or empty>", "hint": "<short description>"}]}

   - The user may paste ONE or MULTIPLE findings in one message. Return
     one findings[] entry per DISTINCT finding.
   - Multiple lines describing ONE finding = ONE entry. Multiple lines
     describing DIFFERENT findings = multiple entries. Judge by content.
   - "url description" or "description" alone is fine. Preserve the URL
     verbatim (no rewriting).

2. Editing a parameter in the master catalog:
   {"action": "edit_parameter",
    "edits": [{"key": "<snake_case_key>", "field": "<field>",
               "value": "<new value>"}]}

   Valid fields: label, priority (Critical/High/Medium/Low), primary_signal
   (Lead/CTR/Rank), hook_stat, hook_ctx, costs, support, in_lead_sum
   (YES/blank).

3. Attaching an uploaded screenshot/image to an EXISTING finding row:
   {"action": "attach_to_row",
    "target": "<category phrase OR row number>"}

   Trigger: user attached one or more images AND the message says
   something like 'attach to <category>', 'add screenshot to
   <finding name>', 'attach ss to Content Visibility', 'add image to
   row 5'. The target is matched case-insensitive against the category
   column — longest prefix match wins. A pure number means the row index.

4. Ambiguous / unrelated:
   {"action": "unknown", "reason": "<short reason>"}

RULES:
  - Return ONLY the JSON object, no prose.
  - Never invent keys not in the catalog.
  - For add_finding, do not summarise / rephrase — pass the hint through
    close to verbatim, the downstream framer will polish it.
  - For attach_to_row, the target must be the user's phrasing — don't
    rename it. The downstream matcher will fuzzy-match it against the
    actual row categories.
"""


def classify(prompt):
    """Return the routed action dict. Never raises."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or not prompt.strip():
        return _fallback(prompt)
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": _SYSTEM
                     + "\n\nCatalog keys (key: label):\n" + _keys_summary()},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "max_tokens": 800,
            },
            timeout=25,
        )
    except Exception as exc:
        print(f"[chat_intent] openai failed: {exc}")
        return _fallback(prompt)
    if not r.ok:
        print(f"[chat_intent] openai {r.status_code}: {(r.text or '')[:200]}")
        return _fallback(prompt)
    try:
        text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        data = json.loads(text)
    except Exception as exc:
        print(f"[chat_intent] parse failed: {exc}")
        return _fallback(prompt)

    return _sanitise(data, prompt)


def _sanitise(data, prompt):
    """Validate the LLM's JSON, dropping bogus edits. Never raises — any
    bad shape (None, list, string instead of dict) falls back to the
    regex-only parser.
    """
    if not isinstance(data, dict):
        return _fallback(prompt)
    action = str(data.get("action", "")).strip().lower()
    if action == "add_finding":
        findings = []
        for f in (data.get("findings") or []):
            # LLM has returned non-dict entries (plain strings, nulls) —
            # treat those as a hint-only fallback entry.
            if not isinstance(f, dict):
                hint = str(f or "").strip()
                if hint:
                    findings.append({"url": "", "hint": hint})
                continue
            url = str(f.get("url", "")).strip()
            hint = str(f.get("hint", "")).strip()
            if url and not url.startswith(("http://", "https://")):
                url = ""  # bad URL, treat as hint-only
            if not url and not hint:
                continue
            findings.append({"url": url, "hint": hint})
        if not findings:
            return _fallback(prompt)
        return {"action": "add_finding", "findings": findings}

    if action == "attach_to_row":
        target = str(data.get("target", "")).strip()
        if not target:
            return _fallback(prompt)
        return {"action": "attach_to_row", "target": target}

    if action == "edit_parameter":
        edits = []
        for e in (data.get("edits") or []):
            if not isinstance(e, dict):
                continue
            key = str(e.get("key", "")).strip().lower()
            field = str(e.get("field", "")).strip().lower()
            value = str(e.get("value", "")).strip()
            if key not in HOOK_COPY:
                continue
            if field not in _PARAM_FIELDS:
                continue
            if field == "priority":
                value = value.title()
                if value not in ("Critical", "High", "Medium", "Low"):
                    continue
            if field == "primary_signal":
                value = value.title()
                if value not in ("Lead", "Ctr", "Rank", "—"):
                    continue
                if value == "Ctr":
                    value = "CTR"
            if field == "in_lead_sum":
                value = "YES" if value.upper() in {"YES", "TRUE", "1"} else ""
            edits.append({"key": key, "field": field, "value": value})
        if not edits:
            return {"action": "unknown",
                    "reason": "couldn't map any edit to a real parameter key"}
        return {"action": "edit_parameter", "edits": edits}

    return {"action": "unknown",
            "reason": str(data.get("reason") or "LLM couldn't classify")}


def _fallback(prompt):
    """Regex-only fallback for when OPENAI_API_KEY is missing / offline.

    Splits on newlines and treats each as a finding — the legacy behaviour.
    """
    lines = [l.strip() for l in (prompt or "").splitlines() if l.strip()]
    findings = []
    for line in lines:
        m = re.match(r"(https?://\S+)(?:\s+(.+))?$", line)
        if m:
            findings.append({"url": m.group(1).rstrip(".,;"),
                             "hint": (m.group(2) or "").strip()})
        else:
            findings.append({"url": "", "hint": line})
    return {"action": "add_finding", "findings": findings or [
        {"url": "", "hint": prompt.strip()}
    ]}
