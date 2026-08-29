# claude pass: review this watchdog run

you review the draft PRs this run opened, on this repo. the run log below lists them as `opened pr for <source>: <url>`. each pr carries one source's new rows from this run, price rows and `removed: true` rows mixed in one pr. work the list top to bottom.

## your job

1. for each draft PR the run opened: diff `origin/mommy` against the PR branch.
2. check every new row in `data/history.ndjson` on the branch against its source page (the row carries `url`; a first-party row names the provider page, an openrouter row names the openrouter api). for a price row: re-read the rate on the page, then compare. for a `removed: true` row: confirm the model is absent from its source (the PR body names the source and date).
3. for the announce diff: the log lists channel changes as `announce change: <provider> <url> <old sha8> -> <new sha8>`. for each changed channel, diff `origin/mommy..<branch>` on `data/announce.json` and answer the rubric question.
4. post findings as PR comments: one comment per PR, findings plus your verdict. comment only on PRs this run opened.
5. edit the branch only for a row error you re-verified against the source page (wrong rate, wrong field, missing peak rates that the page carries). commit the fix on that PR branch. never push to mommy.

## row schema

`data/history.ndjson` is append-only, one json object per line:

```json
{"source":"deepseek","model_id":"deepseek-v4-pro","observed_at":"2026-08-26","input_mtok":0.435,"output_mtok":0.87,"cache_read_mtok":0.003625,"max_tokens_in":1048576,"max_tokens_out":393216,"peak_windows":[["01:00Z","04:00Z"],["06:00Z","10:00Z"]],"peak_input_mtok":0.87,"peak_output_mtok":1.74,"url":"https://api-docs.deepseek.com/quick_start/pricing/"}
```

- `input_mtok` / `output_mtok` derive from per-token strings x 1e6, rounded to 6 decimals.
- `max_tokens_in` is the context window and `max_tokens_out` the max output length; both are optional. pre-split rows carry a single legacy `max_tokens` key (context for every source except first-party deepseek, where it is max output); the store diff treats a legacy `max_tokens` as `max_tokens_in`.
- `currency` (default `USD`) + `unit` (default `tokens`) name the source quote; `currency_rate` + `currency_rate_date` are the conversion provenance; the mtok price fields always hold USD. all four optional; the two rate fields never join the diff.
- a change = any present comparable field differs from the last row for `(source, model_id)`. `observed_at`, `url`, `name`, `currency_rate`, and `currency_rate_date` are provenance and excluded from the diff.
- openrouter rows add `name` and keep unconsumed pricing keys verbatim under `extra`. alias entries and dated-canonical snapshots get no row. scheduled overrides land under `window_rates` (one entry per override: optional `days` = lowercase weekday names, absent = every day; optional `window` = `[start_hhmm, end_hhmm]`, absent = whole day; per-rate mtok keys present only when the override carries them, absent keys inherit the base price). volume overrides (`min_prompt_tokens`) stay verbatim in `extra`.
- a removal row carries `{"removed": true}` and no price fields; it means the source stopped listing the model. accept it as valid.
- `data/index.json` regenerates each run: latest row per `(source, model_id)` plus `first_seen`. a removed model keeps its last prices and gains `removed_at`.
- `data/billing-rules.json` is human-written billing-rule semantics per provider. a channel diff that confirms a rule change should be flagged for the human to land there; you do not write it.

## source urls

`providers.toml` carries one section per watched provider: `detector_url` / `scraper_url` (the pages), `announce_urls` (the watched channels). openrouter rows come from `https://openrouter.ai/api/v1/models`.

## domain quirks

verbatim copies of the domain-knowledge quirks sections, 2026-08-26. drift-checked locally by `tests/test_claude_pass_prompt.py`.

### provider page facts, 2026-08-24 re-probe additions

measured 2026-08-24 against the pinned pricing-page snapshots (tests/fixtures/<provider>_page/pricing.html) and live target ymls.

- together: stale HF-style ids. our page ids are lowercase-hyphen slugs from the two `Model | Input | output` tables (chat + vision, merged by slug, first table wins); the batch toggle carries no static rates. cached column -> cache_read. dedup: `llama-3.3-70b` -> `meta-llama/Llama-3.3-70B-Instruct-Turbo`, `llama-3-8b-instruct-lite` -> `meta-llama/Meta-Llama-3-8B-Instruct-Lite` (same endpoints, together's api strings). openrouter lists no `together/` prefix. the fine-tuning "Specialized pricing" table carries models absent from the per-token tables (kimi k2.7-code, grouped with kimi k2.6); absence keys on the per-token tables only. OBSERVED 2026-08-29 (PR 66 review).
- novita: stale; ids come from the page's own card hrefs resolved through the embedded next.js flight state to canonical api ids (`deepseek/deepseek-v4-pro-0813`, `zai-org/glm-5.2`). rates from span title attrs, cache-read from the `data-pricing-key="cache-read"` wrapper, context -> max_tokens_in. tiered/omnimodal cards -> None. dedup: `deepseek/deepseek-r1-0528` -> `deepseek/deepseek-r1`, `deepseek/deepseek-v3-0324` -> `deepseek/deepseek_v3` (underscore spelling). no openrouter `novita/` prefix.
- cohere: the page mixes prose rates ("Command pricing is $1.00/1M tokens for input and $2.00/1M tokens for output") with a per-instance model-vault table whose cells are not per-token (-> None). the current model cards (Command R 0.15/0.60, R7B 0.0375/0.15, Embed 4 0.12/1M with output 0) live only in the embedded `__next_f` flight payload, not the rendered html; rerank cards bill per 1K searches and stay excluded. slug rule: lowercase, `+` -> `plus`, non-alphanumeric runs collapse, dots kept (`rerank-3.5-medium`). pricing cards without dollar rates are excluded from detection. dated releases emit newest first. dedup: `command-r-03-2024` -> `command-r`, `command-r-plus-04-2024`/`-08-2024` -> `command-r-plus`. openrouter prefix `cohere/` (5 models).
- google: section-per-model h2s in the pricing docs; canonical id from the heading's em slug (h2 id only as fallback, gemma-4). standard tier only; the first dollar amount in the paid column is the base rate, which handles promo cells ("$0.75 through ..., $1.50 starting ..."), tiered cells (<=200k first), and cache cells (read rate before the storage price). per-image output cells -> None; embedding sections (no output row) price with output 0. dedup: `gemini-3.1-flash-image` -> `gemini-3.1-flash-image-preview`, `gemini-3-pro-image` -> `gemini-3-pro-image-preview`, the dated native-audio/lite preview spellings -> `gemini-live-2.5-flash` / `gemini-2.5-flash-lite`. openrouter prefix `google/` (41 models).
- avian: 4 stale HF entries, no page overlap. card grid `#avModelGrid` only; slug lowercase-hyphen, dots kept (`mimo-v2.5-small`); context K/M -> max_tokens_in (page abbreviation, human reconciles); cache per card; the Dedicated Deployments block is excluded. no openrouter `avian/` prefix.
- groq (wired 2026-08-29, todo #17): `console.groq.com/docs/models.md` serves three pipe tables with a shared header (production 6 rows, systems 2, preview 8). the price cell glues "$X input$Y output" with no separator. per-token rows: 7 (gpt-oss-120b/-20b, gpt-oss-safeguard-20b, llama-prompt-guard-2-22m/-86m, qwen/qwen3.6-27b, qwen/qwen3.8-27b); ContactSales: 3; per-hour: 2; per-char: 2; dash: 2. an Enterprise badge glues onto the api id in the md twin (all badge rows ContactSales today); parse_id strips a glued prefix by suffix-match against the /docs/model/ link tail. no cached-input column; MAX COMPLETION TOKENS -> max_tokens_out (qwen3.8 reads an odd 131,042). the detector emits per-token rows only, raises on unknown price-cell shapes, and emits zero-rate rows (scrape -> None, free). no watchable announce surface: llms.txt lists only a changelog frozen since 2025-04.

### deepseek page move

measured 2026-08-26: the slash-less pricing url serves a ~46KB JS shell, but the trailing-slash form `https://api-docs.deepseek.com/quick_start/pricing/` serves the static docusaurus html (23KB) with the full MODEL table, USD prices, and the peak footnote. the config urls carry the trailing slash; the slash-less path must not come back (the js shell carries no table markers). the footnote gained a "Monday through Friday" clause, which the scraper's non-end-anchored pattern tolerates. no `.md` twin, llms.txt, or public docs source repo exists; the zh-cn twin is CNY-only.

### deepseek peak schedule

the live pricing page (2026-08-19) carries v4 peak/off-peak subrows plus the footnote "Off-peak rates are half of the peak rates. Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC (all other hours are off-peak)". the scraper parses the split schedule into peak windows + peak rates; rows store it as flat `peak_*` fields.

billing-rule change, effective 2026-08-23 00:00 beijing time (deepseek team email to cloudy, received 2026-08-22): weekdays (monday-friday, beijing time) keep the peak/off-peak split; weekends (saturday-sunday, beijing time) bill uniformly at the off-peak rate. the stored `peak_windows` are pure clock windows in UTC and cannot express this: consumers pricing weekend deepseek calls from the `peak_*` fields overcharge.

### announce channels

billing-rule announcement surfaces per provider, watched every run via `providers.toml` `announce_urls`. OBSERVED 2026-08-26 against the live pages (full probe evidence in `docs/research/announce-channels/`).

- deepseek: `/updates/` is the live static changelog (the 2026-08-13 entry carries the "API Pricing Adjustment" peak/off-peak section). `/news` is a JS shell, individual `/news/news*` pages are static, and `sitemap.xml` lists them, so a new news page surfaces there first. no rss anywhere on api-docs.deepseek.com.
- zai: release notes (`new-released.md`) carry model launches only; billing-class changes land on the devpack plan notice pages (`usage-revision`, `transition`) and the pricing page (in-place edits). `llms.txt` enumerates the docs, so a new notice page surfaces there. the 2026-08-27 `transition.md` diff was rejected as a billing rule (subscription mechanics, cloudy 2026-08-28); future diffs of the same class get the same answer.
- moonshot: the only official changelog (`platform-changelog.md`) is stale (newest entry 2025-04-07); post-2025 announcements have no docs-side dated surface. `llms.txt` + the sitemap enumerate the whole docs tree.
- minimax: models release notes are current but carry no pricing class; launch pricing appears inside blog posts on the blog index (no rss). no surface observed announcing a rate change.
- xai: `/developers/release-notes` demonstrably carries the class (per-entry prices, a 50% agent-tool price-drop entry); `x.ai/news` is the static news index (no rss).
- mistral: `resources/changelogs` carries price-reduction and free-tier entries (keys are day+month, no year labels); `mistral.ai/news/rss` is the live blog feed.
- perplexity: docs changelog with a `.md` twin; entry labels are month-granularity only; no rss.
- together: docs changelog with a `.md` twin (pricing-update entries Apr-Jun 2026); `blog/rss.xml` is marketing and launches, a change-detection complement only.
- novita: no stable titled changelog index: `/docs/changelog` 307-redirects to the newest entry, whose sidebar links every entry.
- cohere: `docs.cohere.com/changelog` page 1 is the feed (no working rss); deprecation/retirement entries are the highest-signal class.
- google: the gemini-api changelog carries intro-price windows, deprecations, and free-tier notes; fetch with `?hl=en` pinned (a locale-less fetch returned Japanese from one vantage). the developers.googleblog feed spans all dev products (label feeds 404) and re-publishes daily with a new build date; `extract_prose` drops feed date elements, so rebuild dates no longer fake a change (fixed 2026-08-29, todo #18). OBSERVED 2026-08-29 (live tag inventory).
- avian: no watchable surface: homepage banners only, x/linkedin gated. it carries no `announce_urls`; the pricing pages stay the only diffable artifact.
- cloudflare: `workers-ai/changelog/` is the static per-product changelog (pricing-update posts land there; the site-wide changelog mixes every product). OBSERVED 2026-08-27.
- digitalocean: `docs.digitalocean.com/release-notes/` is the static release-notes index. OBSERVED 2026-08-27.
- deepinfra, watsonx, baseten, sambanova, publicai, openai, ai21: no watchable announce surface from this host (no changelog page found, docs 403 this egress, or the changelog serves a JS shell). they carry no `announce_urls`; pricing pages stay the only diffable artifact. OBSERVED 2026-08-27.

## rubric question

for each changed announce channel, answer: does this change billing semantics (rates, tiers, when-rates-apply, free-tier status)? name the semantics changed and cite the prose.

## output contract

- comment on each PR this run opened: findings plus a verdict line (`verified`, `findings`, or `needs human`).
- no PR comments when you find nothing: say so in your final message only.
- never comment on PRs the run did not open. never push to mommy. never delete branches.
- your final message summarizes findings per PR; the PR comments are the durable record.

### scaleway + databricks (added 2026-08-29, todo #17)

- scaleway: the model-as-a-service page serves the per-1M-token table statically in EUR ("€1.80 / million tokens"), no USD column. ids = Name-cell slugs stored unprefixed; the Try-link modelName query cross-checks when present (parse_id falls back to the Name cell alone when a row carries no link). "Free" output = a zero rate (the embedding convention). known unpriced: per-audio-minute rows. dedup: deepseek-v4-flash-0731 -> deepseek-v4-flash, mistral-small-3.2-24b-instruct-2506 -> mistral-small-3.2-24b-instruct. the committed fixture is a content-derived slice of the live capture (byte offsets drift with css-class hashes; the guard is a fixture-shape pin: one thead row + 15 tbody rows with the complete last-row Try link). announce: docs changelog + its rss (same content twice, harmless).
- databricks: the foundation-model-serving page serves the DBU rate table statically (DBU / M input, output, cache-read tokens per display name, "Kimi K3 42.857 / 214.286 / 4.286"). ids = an explicit display-name dict derived from the stored openrouter id set (vendor prefix stripped; "(Priority)" -> "-priority"; the U+2316 regional-uplift marker strips). a priced row with an unmapped name raises. "n/a" output = embedding rows bill input only, stored with output 0.0. dedup: deepseek-v4-pro-0813 -> deepseek-v4-pro, deepseek-v4-flash-0731 -> deepseek-v4-flash. the DBU->USD rate is 0.07 (the pricing-page AI card, client-rendered; cited via google's index + third-party consensus; DBU rates differ per cloud, the announce watches /aws/ so re-probe before trusting another cloud). announce: docs release-notes index (sub-page links client-rendered).
