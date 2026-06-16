# Website Audit Tool — Working Doc

**Purpose:** When we upsell an existing client (where we already run their feeds) to *also* take over their full website, we generate a technical SEO + UX audit of their **live** site. The audit shows everything wrong with the current site so we can make the case to move to a Gushwork-built website.

**Owner:** Shavi Goyal · **Status:** v1 built, run on `endeavorfg`

---

## 0. Decisions (locked with user)

- [x] **Standalone project** — lives in `/Users/shavigoyal/Projects/website-audit-tool` (separate from CSM module).
- [x] **Output = Google Sheet**, auto-created in user's Google Drive via the connected Google MCP (multi-tab, mirrors existing audit format).
- [x] **Mockup comparison is backend-only.** We fetch PageSpeed for our mockup too, but the final sheet is a **pure problem list of the LIVE site** — no side-by-side, no "our mockup is better" framing.
- [x] **Screaming Frog `internal_all` CSV is always provided** and is the primary import.
- [x] **PageSpeed run on different page TYPES** (one representative per template: home / service / contact / blog-article / etc.), not most-linked.
- [x] **Tone = pure problem list** + SEO impact. Neutral, like existing audits. No upsell language in the sheet.
- [x] **Always phrase as "Multiple instances found"** even when only one URL is affected.
- [x] **Never comment on feeds pages** (the blog/category pages we built) — excluded via config `exclude_url_patterns`.

---

## 1. Inputs (per client)

A small JSON config in `clients/<name>.json`:

```json
{
  "client": "endeavorfg",
  "live_url": "https://www.endeavorfg.com/",
  "mockup_url": "https://gushwork-endeavorfg.vercel.app/",
  "sf_internal_all_csv": "inputs/endeavorfg_internal_all.csv",
  "sf_images_csv": null,
  "exclude_url_patterns": ["/blog", "/category", "?page="],
  "pagespeed_strategy": "mobile",
  "drive_folder_id": null
}
```

- [x] `live_url`, `mockup_url`, `sf_internal_all_csv` required.
- [x] `sf_images_csv` optional — only source of **alt-text** + authoritative image sizes. If null, alt-text check is skipped (internal_all has no alt data) and images>100KB is derived from internal_all instead.
- [x] `exclude_url_patterns` — paths we built (feeds) to keep out of observations.
- [x] PageSpeed API key read from env `PAGESPEED_API_KEY` (provided: `AIzaSy…Wkcdc`).

---

## 2. Architecture

```
audit.py                 # CLI entry: python audit.py clients/endeavorfg.json
audit/
  config.py              # load + validate client config
  sf_csv.py              # parse internal_all, classify page types, run CSV checks
  pagespeed.py           # PSI API calls (live + mockup), extract CWV + opportunities
  observations.py        # turn raw findings -> Observation rows (priority+impact+ref)
  report_xlsx.py         # build multi-tab .xlsx mirroring existing audit format
clients/<name>.json
inputs/<name>_internal_all.csv
output/<name>_audit.xlsx
```

Flow:
1. Load config → load CSV → drop excluded (feeds) URLs.
2. Run all **CSV checks** → raw findings (with example URLs + counts).
3. Pick representative URL per **page type** → run **PageSpeed** (live; mockup backend-only).
4. Merge into **Observations** (Observation / Priority / Impact / Reference).
5. Build **multi-tab xlsx** (Observation + supporting evidence tabs).
6. Upload to Drive as a **Google Sheet** (Claude calls `create_file` MCP with the xlsx → auto-converts to multi-tab Sheet).

---

## 3. Checks / Parameters

Union of both reference audits + additions. Each fires only if instances exist; phrasing always "Multiple … found".

### From Screaming Frog `internal_all` CSV
- [x] **Render / JS errors** — `JS Error` non-empty → Critical. *Pages may not be indexed → severe traffic/ranking loss.*
- [x] **404 / broken pages** — `Status Code` 4xx → High. Tab: `404 Pages`.
- [x] **5xx server errors** — `Status Code` 5xx → High.
- [x] **Redirects** — `Status Code` 3xx (excl. canonical) → Medium. Tab: `Redirects`.
- [x] **Non-indexable pages** — `Indexability = Non-Indexable` (excl. feeds/paginated) → Medium. Tab: `Non-Indexable`.
- [x] **Title too long** — `Title 1 Length > 60` → High. Tab: `Long Titles`.
- [x] **Title keyword-stuffed** — repeated tokens / >3 `|` separators → High.
- [x] **Missing title** — `Title 1` empty → High.
- [x] **Duplicate titles** — same `Title 1` across pages → Medium.
- [x] **Meta description too long** — `Meta Description 1 Length > 160` → High.
- [x] **Meta description missing / auto-generated** — empty or > 320 chars → High.
- [x] **Missing H1** — `H1-1` empty → High. Tab: `Missing H1`.
- [x] **Multiple H1** — `H1-2` non-empty → Low.
- [x] **Thin content** — `Word Count < 300` → High. Tab: `Thin Content`.
- [x] **Limited content depth** — low word + low `Sentence Count` (missing key sections) → High.
- [x] **Near-duplicate content** — `No. Near Duplicates > 0` → Medium. Tab: `Near Duplicates`.
- [x] **Images > 100 KB** — `Content Type` image & `Size (Bytes) > 100000` → Medium. Tab: `Images > 100 Kb`.
- [x] **Slow response time** — `Response Time > 1.0s` → Medium.
- [x] **High carbon / page weight** — `Carbon Rating` ∈ {E,F} or high `CO2 (mg)` → Low.
- [x] **Deep crawl depth** — `Crawl Depth > 4` → Low.
- [x] **Missing canonical** — `Canonical Link Element 1` empty on indexable HTML → Medium.
- [x] **Spelling / grammar errors** — `Spelling Errors`/`Grammar Errors > 0` → Low.
- [x] **Low text ratio** — `Text Ratio < 10%` → Low.
- [x] **Poor readability** — `Flesch Reading Ease < 30` → Low.
- [x] **Missing alt text** — only if `sf_images_csv` provided; else skipped with a note.
- [x] **Structured data absent** — heuristic sitewide note (internal_all can't confirm per-page) → Medium.

### From PageSpeed Insights API (per page type, live site)
- [x] **High LCP** — lab LCP > 4s → High; 2.5–4s → Medium. e.g. "homepage 7.9s".
- [x] **High CLS** — > 0.25 → Medium.
- [x] **High TBT / low performance score** — perf score < 0.5 → High.
- [x] **Render-blocking resources** — opportunity present → Medium.
- [x] **Unoptimized / next-gen images** — `uses-optimized-images` / `modern-image-formats` → Medium.
- [x] **Backend (not shown):** same page types fetched for mockup; deltas logged to console to confirm our build fixes each issue before we pitch.

### Page-type classification (for PSI representative selection)
- [x] Homepage (path `/`), Service/Product, About/Process, Contact, Article/Blog (one rep only, even though feeds excluded from observations, to characterize template), Landing. Heuristic on URL path + crawl depth; pick lowest-depth representative per bucket. Cap ~6 PSI calls/site.

---

## 4. Output sheet (mirrors existing audits)

- [x] **Tab `Observation`** — columns: `Observation | Priority | Impact | Reference`. Header row blue (matches existing). Sorted Critical→Low.
- [x] **Tab `SF Internal all`** — raw CSV (evidence).
- [x] **Evidence tabs** (only when the check fired): `404 Pages`, `Images > 100 Kb`, `Long Titles`, `Missing H1`, `Thin Content`, `Non-Indexable`, `Redirects`, `Near Duplicates`.
- [x] `Reference` column points to the evidence tab name or lists ≤8 example URLs.
- [x] **Google Sheet** created in Drive; link returned to user.

---

## 5. Build & run checklist

- [x] Scaffold project + copy endeavorfg CSV to `inputs/`.
- [x] Write `WORKING-DOC.md` (this file).
- [ ] `requirements.txt` (pandas, openpyxl, requests).
- [ ] `audit/sf_csv.py` — CSV load + page-type classify + all CSV checks.
- [ ] `audit/pagespeed.py` — PSI client + extraction.
- [ ] `audit/observations.py` — priority/impact catalog + row builder.
- [ ] `audit/report_xlsx.py` — multi-tab xlsx writer (format match).
- [ ] `audit.py` — CLI wiring.
- [ ] `clients/endeavorfg.json`.
- [ ] Run end-to-end on endeavorfg → `output/endeavorfg_audit.xlsx`.
- [ ] Verify zero errors, sanity-check observations against raw data.
- [ ] Upload to Google Drive as a Google Sheet → share link.

---

## 6. Open / future

- [ ] Auto-fetch SF "Images" export for alt-text (currently manual/optional).
- [ ] Detect structured data per-page (needs raw HTML fetch, not in internal_all).
- [ ] Optional one-click HTML report for client presentations.
- [ ] Batch mode: run all clients in `clients/` in one command.
