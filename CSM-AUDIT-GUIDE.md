# Website Audit Guide for CSMs

**Use this when** you're upselling an existing feeds client to also let Gushwork take over their **full website**. The audit is a neutral, factual list of what's wrong with their *current live site*, so the client sees the gap themselves.

There are two ways to produce it:

- **Option A — Ask for the tool** (fastest, once live). See ["Using the tool"](#option-a--using-the-tool).
- **Option B — Do it yourself now** (until the tool is live). See ["Manual audit"](#option-b--manual-audit-step-by-step).

Both produce the **same output**: a Google Sheet with an **Observation** tab (the problems), evidence tabs, a **Checks Passed** tab, and an **All Pages (crawl)** tab.

---

## House rules (read first — these make every audit consistent)

1. **Pure problem list.** Neutral, factual SEO tone. No "our mockup is better", no sales language. Just "this is wrong, here's the impact."
2. **Always write "Multiple pages found with…"** even if only one URL is affected.
3. **Never comment on feeds pages.** The `/blog` and `/category` pages were built by Gushwork. Exclude them from every issue. (They still appear in the raw crawl tab, just not in observations.)
4. **Don't frame anything as an upsell.** The impact column is standard SEO impact only.
5. **No "—" (em dash).** Use a comma, colon, or full stop.
6. **Attach a real example URL** to every observation ("Eg: …") plus a Reference (an evidence tab or the list of affected URLs).

---

## Option A — Using the tool

When the tool is live, you just hand over three things and get a finished Google Sheet back:

| You provide | How to get it |
|---|---|
| **Screaming Frog `Internal > All` export (CSV)** | Crawl the live site in Screaming Frog, then `Export` the **Internal → All** tab |
| **Live site URL** | e.g. `https://www.client.com/` |
| **Mockup URL** (optional) | the Gushwork build, e.g. `https://gushwork-client.vercel.app/` (used in the background only, never shown) |

The tool then runs ~35 checks (Screaming Frog data + Google PageSpeed + live page fetches), classifies page types, checks structured data per type, reviews CRO against the mockup, and writes the Google Sheet automatically.

> Example output: [EndeavorFG audit](https://docs.google.com/spreadsheets/d/1kN6wromYMF_GHJKlXdduLpsv6nr_0ohEGPYczK44wgU/edit)

---

## Option B — Manual audit (step by step)

### Step 1 — Crawl the site (Screaming Frog)
1. Open **Screaming Frog SEO Spider** (free for up to 500 URLs).
2. Enter the live URL, click **Start**, let it finish.
3. Go to the **Internal** tab, set the filter to **HTML**, and `Export`. (Keep the full **Internal → All** export too, for the raw tab.)

### Step 2 — Set your scope
- **Drop feeds pages:** anything with `/blog` or `/category` in the URL. Don't flag these.
- **Drop non-SEO pages** from content checks: `/team-member`, `/client-login`, `/privacy`, `/terms`, etc.
- **Pick one representative page per type** for the page-level checks:
  - Homepage, Service / Product, About / Process, Contact, (Blog only to characterise the template, never to flag).

### Step 3 — Technical checks (from the Screaming Frog export)
Sort/filter the relevant column, count the affected pages, grab one example URL.

| Check | Where in Screaming Frog | Flag when | Priority |
|---|---|---|---|
| 404 / broken | `Status Code` | 4xx (ignore `/cdn-cgi/` system URLs) | High |
| Server error | `Status Code` | 5xx | High |
| Redirects | `Status Code` | 3xx | Medium |
| Noindex page | `Indexability Status` | contains "noindex" (NOT "redirected"/"canonicalised") | Medium |
| Missing title | `Title 1` | empty | High |
| Long title | `Title 1 Length` | > 80 | High |
| Short title | `Title 1 Length` | 1–29 | Low |
| Duplicate title | `Title 1` | same title on 2+ pages | Medium |
| Missing meta desc | `Meta Description 1` | empty | High |
| Long meta desc | `Meta Description 1 Length` | > 200 | High |
| Short meta desc | `Meta Description 1 Length` | 1–69 | Low |
| Duplicate meta desc | `Meta Description 1` | same on 2+ pages | Medium |
| Missing H1 | `H1-1` | empty | High |
| Multiple H1 | `H1-2` | not empty | Low |
| Long H1 | `H1-1 Length` | > 70 | Low |
| Short H1 | `H1-1 Length` | 1–19 | Low |
| Duplicate H1 | `H1-1` | same on 2+ pages | Medium |
| Thin content | `Word Count` | < 300 (SEO pages only) | High |
| Missing canonical | `Canonical Link Element 1` | empty | Medium |
| Image > 100 KB | filter `Content Type` = image, `Size (Bytes)` | > 100000 | Medium |
| Long URL | `Address` length | > 115 chars | Low |
| Deep page | `Crawl Depth` | > 4 | Low |

### Step 4 — PageSpeed (Core Web Vitals)
Run **one representative page per type** at **[pagespeed.web.dev](https://pagespeed.web.dev/)** (use the **Mobile** tab).

| Metric | Flag when | Priority |
|---|---|---|
| LCP (Largest Contentful Paint) | > 4s = High, 2.5–4s = Medium | High / Medium |
| CLS (Cumulative Layout Shift) | > 0.25 | Medium |
| Performance score | < 50 = High, 50–89 = Medium | High / Medium |

> Note the worst page + its number as the example, e.g. "Eg: homepage (LCP 8.3s)".

### Step 5 — Live checks (just open these in a browser)

| Check | How | Pass = |
|---|---|---|
| robots.txt | open `client.com/robots.txt` | loads, and is **not** `Disallow: /` for all agents |
| XML sitemap | open `client.com/sitemap.xml` | loads with `<urlset>`/`<sitemapindex>` |
| Favicon | look at the browser tab icon | icon shows |
| non-www → www | type the other variant in the address bar | it redirects to one canonical version |
| http → https | type `http://client.com` | it redirects to `https://` |
| About page exists | check the crawl | a real About / company page exists |
| Contact page exists | check the crawl | a contact / booking page exists |
| Image alt text | in Screaming Frog: `Bulk Export → Images → Missing Alt Text` (or eyeball the page source) | images have `alt=` |

### Step 6 — Structured data, per page type
For **one representative page of each type**, paste the URL into **[validator.schema.org](https://validator.schema.org/)** and check the `@type` it finds against what that type *should* have:

| Page type | Should have |
|---|---|
| Homepage | Organization and/or WebSite (LocalBusiness if local) |
| Service / Product | Service or Product |
| About / Process | Organization or AboutPage |
| Contact | LocalBusiness or ContactPoint |
| Blog / Article *(only if not a feeds page)* | Article or BlogPosting |

Flag any type whose representative page is **missing** its expected schema, e.g. "Homepage: client.com (missing Organization / WebSite schema)".

### Step 7 — CRO review (compare to the Gushwork mockup)
Open the live homepage next to the mockup. Flag anything the live site lacks:

- [ ] Clear, single, **repeated** call-to-action above the fold (e.g. "Book a Meeting")
- [ ] **Embedded lead form** on the homepage (not just a link to a contact page)
- [ ] **Trust signals**: testimonials, credentials (CFP/CFA), review badges, quantified proof (years, clients, AUM)
- [ ] **Clear value proposition** in the hero (not generic "trusted advisor")
- [ ] **Social proof / lead magnet**: client logos, "as seen in", a downloadable guide/calculator

Write each gap as a High-priority observation under the right category (Lead Capture, Call-to-Action, Trust Signals, Value Proposition, Social Proof).

---

## Step 8 — Build the Google Sheet

Create a sheet with these tabs:

**Observation** tab — columns: `Category | Observation | Priority | Impact | Reference`

- **Category** = 2–3 words (Title Length, Meta Description, Page Speed, Schema Markup, Lead Capture, etc.)
- **Observation** = "Multiple pages found with …" + a newline + "Eg: <one real URL>"
- **Priority** = Critical / High / Medium / Low
- **Impact** = one neutral SEO sentence (see crib sheet below)
- **Reference** = name of the evidence tab, or the list of affected URLs

**Evidence tabs** (only when the check fired): `Long Titles`, `Redirects`, `Thin Content`, `Images > 100 Kb`, `Duplicate Titles`, etc. — Address + the relevant column.

**Checks Passed** tab — list every parameter you tested that came back clean (shows thoroughness).

**All Pages (crawl)** tab — paste the Screaming Frog export so the client can see the full crawl.

### Impact crib sheet (copy these, keep them neutral)
- Long title: *Truncated titles in search can reduce click-through and rankings.*
- Missing meta: *Missing descriptions let search engines pick weak snippets, lowering CTR.*
- Thin content: *Thin pages struggle to rank for target keywords and convert visitors.*
- High LCP / low perf: *Poor page speed can significantly reduce rankings.*
- High CLS: *Layout shifts frustrate users and harm Core Web Vitals.*
- Duplicate title: *Duplicate titles confuse search engines about which page to rank.*
- Missing canonical: *Without canonicals, search engines may index the wrong URL.*
- No schema: *Without schema, pages miss rich-result eligibility in search.*
- Missing alt: *Missing alt text hurts accessibility and image-search visibility.*
- Redirects: *Redirect hops waste crawl budget and can leak link equity.*
- Lead capture: *May reduce lead conversions from high-intent visitors.*
- Weak CTA: *An unclear call-to-action lowers click-through and lead volume.*
- Trust signals: *Missing trust cues increase bounce and lower conversions.*

---

## What you can't check by hand (note these, don't fake them)
- **Keywords in title / meta** — needs the client's target-keyword list.
- **Full image alt-text audit** — the manual check only covers a few pages; a complete pass needs the Screaming Frog Images export.
- **CTA above the fold** — judge it visually under the CRO section.

When in doubt, leave it out and write a short "Not evaluated: <reason>" note rather than guessing.
