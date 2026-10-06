# Website Audit Tool — Blueprint

End-to-end map of what the app does and where every piece of logic lives.

---

## 1. High-level flow

```
User URL → crawl (SF CLI or built-in) → CSV DataFrame
      ├─ sf_csv.run_checks         → ~30 finding keys
      ├─ sf_csv.representative_pages → 1 URL per page type
      │       └─ pagespeed.fetch_many        → mobile PSI per rep
      │       └─ html_checks.analyze         → schema + render
      ├─ parameters.evaluate       → site-level checks (robots, sitemap, hreflang, CTA, …)
      └─ observations.build_rows   → priority-sorted rows
              ├─ report_xlsx.build   → output/<client>_audit.xlsx
              └─ report_sheets.build → new Google Sheet, shared to CSM
```

---

## 2. Entry points

### `app.py` — Flask web (port 5001)
- `GET /` → `templates/index.html` form (Live URL + optional Mockup URL).
- `POST /run` → derives `client_name` from domain, loads `clients/<name>.json` if present (exclude patterns, page-type overrides, `manual_psi`), calls `_get_dataframes()`:
  - shells to Screaming Frog CLI if `/Applications/Screaming Frog SEO Spider.app/...` exists (`--headless --crawl --export-tabs Internal:All`);
  - else falls back to `audit/crawler.py`.
  Runs the pipeline → writes XLSX + Google Sheet → returns `{xlsx, sheet_url, message}`.
- `GET /download/<filepath>` → serves the XLSX.

### `audit.py` — CLI
`python audit.py clients/foo.json [--no-psi] [--api-key ...]`. Requires a pre-generated SF CSV. Same pipeline as web, plus a backend-only mockup-vs-live PSI comparison (`_log_backend_compare`) and a `<client>_audit.json` sidecar for Drive upload.

### `upload_to_drive.py` — CLI
OAuth desktop flow (`credentials.json` → `token.json`). Uploads a pre-built XLSX as a Google-Sheet-converted file; optionally into `--folder-id`.

### `api/`
Empty directory. `vercel.json` may reference it but nothing runs here yet.

---

## 3. Crawler — `audit/crawler.py`

Purpose: replace Screaming Frog when SF is unavailable (Vercel, etc.) and produce a DataFrame in SF `internal_all.csv` shape.

- `_MAX_WORKERS = 8`, `_MAX_URLS = 750`, `_TIMEOUT = 15s`, UA `GushworkAuditBot/1.0`.
- BFS with a deque of `(url, depth)`; concurrent batches of `_MAX_WORKERS * 2`; 0.05s sleep between batches; `allow_redirects=False` so 3xx rows are captured and same-origin destinations are re-queued.
- Skips asset extensions during link discovery (jpg / png / pdf / css / js / woff / …).
- `_parse_page` extracts: Title + length, Meta Description + length, up to 2 H1s, Canonical, Meta Robots, X-Robots-Tag, Indexability (`noindex` → `Non-Indexable`), Word Count.

Downstream code is source-agnostic — anything that reads SF CSVs also reads crawler output.

---

## 4. Screaming Frog CSV — `audit/sf_csv.py`

### Loading
- `load(csv_path, exclude_patterns)` / `load_from_df(df, exclude_patterns)` — drops URLs matching client `exclude_url_patterns` + hardcoded `SYSTEM_EXCLUDE = ["/cdn-cgi/"]`.
- `NON_SEO_PATTERNS` — bios, `/login`, `/cart`, `/privacy`, `/terms`, `/contact` etc. Used to exclude utility pages from content checks and PSI reps.

### Classification
- `classify_page_type(url, custom_patterns)` — client `page_type_patterns` first (highest precedence), then hardcoded `PAGE_TYPE_RULES` (Homepage / About / Contact / Service / Article / Other).
- `representative_pages(df_scoped, custom_patterns)` — one URL per type, chosen by lowest Crawl Depth; non-SEO pages excluded.

### Checks — `run_checks(df, df_full, has_images_csv)`
Each check returns `{key, count, examples[≤5], evidence:(tab,headers,rows)|None, suppress?}`.

| key | trigger |
|---|---|
| `render_error` | `JS Error > 0` on HTML |
| `error_404` | status 400–499 (asset extensions excluded) |
| `error_5xx` | status 500–599 |
| `redirects` | status 300–399 (evidence-only, `suppress=True`) |
| `non_indexable` | HTML with `noindex` in Meta Robots / Indexability Status / X-Robots-Tag |
| `title_long` / `title_short` / `title_missing` | Title Length > 80 / 0 < len < 30 / empty |
| `title_stuffed` | ≥3 pipes or a 4+ char token repeated ≥3× |
| `title_duplicate` | shared titles across non-paginated pages |
| `title_multiple_tags` | Title 2 non-empty |
| `pagination_no_rel` | paginated URL missing both rel prev/next (`/page/1/` excluded) |
| `meta_long` / `meta_short` / `meta_missing` / `meta_duplicate` / `meta_multiple_tags` | > 200 / 0 < len < 70 / empty / duplicated / Meta Description 2 non-empty |
| `h1_missing` / `h1_multiple` / `h1_long` / `h1_short` / `h1_duplicate` | empty / H1-2 present / >70 / 0<len<20 / duplicated |
| `url_long` | URL length > 115 |
| `thin_content` | Word Count < 300 on SEO pages |
| `near_duplicate` | `No. Near Duplicates > 0` |
| `image_large` | image Size > 100 KB |
| `high_carbon` | Carbon Rating ∈ {E, F} |
| `canonical_missing` / `canonical_not_self` | empty / doesn't match URL (query variants excluded) |
| `spelling_grammar` | Spelling Errors > 0 or Grammar Errors > 0 |
| `render_js_dependent` | Word Count < 100 but Rendered Word Count > 200 (SF JS mode only) |
| `low_inlinks` | SEO pages with Inlinks ∈ {0, 1} |

`CSV_CHECK_LABELS` maps each key to a friendly label for the "Checks Passed" tab.

---

## 5. HTML checks — `audit/html_checks.py`

Render-time checks that CSV can't answer.

- `_schema_types(html)` — regex over JSON-LD `"@type":"…"` and microdata `itemtype=…schema.org/…`.
- `analyze(reps, df=None)` — per `{page_type: url}`:
  - **schema**: page passes if it carries any of `EXPECTED_SCHEMA[page_type]["types"]` (Homepage → Organization/WebSite/LocalBusiness; Service/Product → Service/Product/Offer; Article/Blog → Article/BlogPosting/NewsArticle; …).
  - **render**: SF JS mode present → uses `raw_wc * 6 ≈ text chars`; else counts chars from no-JS fetch. `RENDER_MIN_CHARS = 500` triggers `render_blocked`.
- Returns `{pages, schema_gaps, structured_data_absent, render_blocked, render_ok, sf_render_mode}`.

---

## 6. PageSpeed — `audit/pagespeed.py`

- `https://www.googleapis.com/pagespeedonline/v5/runPagespeed`, `category=performance`, mobile default, 90s timeout, up to 2 retries with exponential backoff, `key` from arg or `PAGESPEED_API_KEY`.
- `_parse` extracts: performance_score (×100), LCP, FCP, TBT, CLS, SI, top 6 opportunities by savings (score < 0.9, savings > 150 ms), and a base64 `final-screenshot` (WebP).
- `fetch_many(reps, strategy, api_key)` iterates page types with 0.5s sleep. `save_screenshot(result, out_path)` decodes to disk.

### Thresholds (`observations.psi_status`)
- LCP ≥ 2.5s → fail
- CLS > 0.25 → fail
- performance score < 90 → fail
- opportunity title contains "render-block" → fail
- opportunity title contains "image" → fail

`psi_to_observations` groups failures by bucket, cites the worst URL, splits `lcp_high` (≥4s) vs `lcp_medium`, `perf_low` (<50) vs `perf_moderate`.

---

## 7. Site-level checks — `audit/parameters.py`

`evaluate(df, live_url)` — hits the live domain and inspects the crawl aggregate. Returns `{issues, passed, na}`.

- **About page** (`/about|who-we-serve|our-process|meet-the-team|/team`) — Medium if missing.
- **Contact page** (`/contact|book-meeting|/get-in-touch|/schedule`) — High if missing.
- **Crawl budget** — >10% of HTML being 3xx/4xx/5xx/non-indexable → Low.
- **robots.txt** — fetches `/robots.txt`, detects `Disallow: /` for `User-agent: *` → Critical `robots_block`; missing → Low.
- **Sitemap** — tries `/sitemap.xml` then `/sitemap_index.xml`, checks for `<urlset` / `<sitemapindex`. Missing → Medium.
- **Favicon** — `<link rel="icon">` or `/favicon.ico`. Missing → Low.
- **www / non-www redirect** — alt-host URLs from crawl must be all 301/308; else Low. Not in crawl → `na`.
- **HTTP → HTTPS** — same pattern; not all 301/308 → High.
- **Open Graph** — homepage HTML must contain `og:title`, `og:description`, `og:image`. Any missing → Medium `og_missing`.
- **Hreflang** — language subdirectories present (`/fr/`, `/de/`, …) but no `hreflang` in crawl → High `hreflang_missing`.
- **FAQ** — first service/product URL must have `FAQPage` schema or a "frequently asked questions" heading. Missing → Medium `faq_missing`.
- **CTA above the fold** — first 6000 chars of homepage; regex over anchor/button text (`get.?a?.?quote|contact|call.?us|book|schedule|enquir|request`). No match → `na`.
- Always appended as `na`: keyword-in-title, keyword-in-meta, full alt-text audit.

---

## 8. Observations — `audit/observations.py`

- `CATEGORY` — finding key → short header ("Title Length", "Page Speed", …).
- `CATALOG` — finding key → `(priority, observation_template, impact_text)`. Priorities: Critical / High / Medium / Low.
- `build_rows(findings, psi_rows, extra_rows)` — skips `suppress=True`, appends `Eg: <first example>`, prefers the evidence tab name for the Reference column, sorts by `PRIORITY_ORDER`.
- `render_rows(html_result)` — schema gaps become one row with `validator.schema.org` link; `render_blocked` becomes Critical.
- `cro_rows(cro_items)` — pass-through of client-supplied CRO observations (always High).
- `build_passed_tab(fired_csv_keys, psi_passed, render_passed)` — every check that didn't fire becomes a "passed" row.

No dedupe across findings; grouping is by key. Sort is priority ascending.

---

## 9. Config — `audit/config.py`, `configs/`

- `load_config(path)` requires `client`, `live_url`, `sf_internal_all_csv`; merges with `DEFAULTS` (`mockup_url=None`, `sf_images_csv=None`, `exclude_url_patterns=[]`, `pagespeed_strategy="mobile"`, `drive_folder_id=None`). Resolves paths relative to project root.
- `configs/js-rendering.seospiderconfig` — Screaming Frog preset for JS rendering mode.

---

## 10. Reporting

### `audit/report_xlsx.py`
`build(path, client, rows, notes, df_raw, evidence_tabs, total_pages, total_images)` — openpyxl. Tabs:
- **Observation** — Category | Observation | Priority | Impact | Reference | "Count ⚠ DELETE BEFORE SHARING" (red header). Rows tinted by `PRIORITY_FILL`. Count formatted `N / M pages` (or `images` for `image_large`).
- One tab per evidence entry (name capped to 31 chars).
- **SF Internal all** — raw crawl DataFrame dump.
- Bold blue header, wrap text, freeze row 1, column autosize.

### `audit/report_sheets.py`
`build(spreadsheet_title, obs_rows, evidence_tabs, page_type_rows=None, …)` — Google Sheets API via `GOOGLE_SERVICE_ACCOUNT_JSON` env (scopes: spreadsheets + drive.file). Returns `None` gracefully if missing so caller falls back to XLSX.
- Title: `"<Client> SEO Audit — YYYY-MM-DD"`.
- **Observations** written first: dark header, Proxima Nova, wrap, frozen row 1, priority-colored rows, red count header.
- One sheet per evidence tab (first column widened to 460 px).
- Optional Page Type tab.
- Shares to `AUDIT_SHARE_EMAIL` (default `shavi.goyal@gushwork.ai`) as writer with `sendNotificationEmail=False`. Returns sheet URL.

### `upload_to_drive.py`
Separate flow; OAuth desktop credentials. Uploads a pre-built XLSX as Google-Sheet-converted; writes `drive_sheet_id` back to the client JSON.

---

## 11. Client configs — `clients/*.json`

Per-client fields:
- `client`, `live_url`, `mockup_url` (optional)
- `sf_internal_all_csv`, `sf_images_csv` (nullable)
- `exclude_url_patterns` — URL substrings dropped before every check
- `page_type_patterns` — `{type_name: [url_substrings]}` — highest precedence over slug rules for PSI reps
- `pagespeed_strategy` (default `"mobile"`)
- `drive_folder_id`
- `manual_psi` — injected PSI results per page type (`{"Homepage": {performance_score, lcp_s, cls, tbt_ms, url, opportunities:[[title, ms], …]}}`) when API quota is exhausted
- `cro_observations` — list of `{category, observation, impact, reference?}` appended as High-priority rows

---

## 12. Templates — `templates/`

Only `index.html`: one form (Live URL + optional Mockup URL). Submits to `POST /run` via fetch, shows a spinner, renders the JSON response (observation count, XLSX download, Google Sheet URL). Neutral system fonts, indigo accent.

---

## 13. Env vars

| var | purpose |
|---|---|
| `PAGESPEED_API_KEY` | PSI v5 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Sheets + Drive for `report_sheets` |
| `AUDIT_SHARE_EMAIL` | recipient for auto-share (defaults to `shavi.goyal@gushwork.ai`) |
