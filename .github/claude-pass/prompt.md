# claude pass: review and merge this watchdog run's draft PRs

you review the draft PRs this run opened, on this repo, then merge the ones you verified. the run log below lists them as `opened pr for <source>: <url>`. each pr carries one source's new rows from this run, price rows and `removed: true` rows mixed in one pr. work the list top to bottom.

## your job

1. for each draft PR the run opened: diff `origin/mommy` against the PR branch.
2. check every new row in `data/history/<source>.ndjson` on the branch against its source page (the row carries `provenance.url`; a first-party row names the provider page, an openrouter row names the openrouter api). for a price row: re-read the rate on the page, then compare. for a `removed: true` row: confirm the model is absent from its source (the PR body names the source and date).

a branch carries its source's shard: the landed rows for that source, rows from still-open PR branches, and its own. only the rows the PR body's table names are this PR's own new rows. judge those against their source pages, and never treat carried rows or the state files (`data/absence.json`, `data/announce.json`) as scope noise: `data/announce.json` settles the run's channel changes. a branch carries no `data/index.json`; the merge regenerates it.
3. for the announce diff: the log lists channel changes as `announce change: <provider> <url> <old sha8> -> <new sha8>`. for each changed channel, diff `origin/mommy..<branch>` on `data/announce.json` and answer the rubric question.
4. post findings as PR comments: one comment per PR, findings plus your verdict. comment only on PRs this run opened.
5. edit the branch only for a row error you re-verified against the source page (wrong rate, wrong field, missing peak rates that the page carries). commit the fix on that PR branch. pushes happen only through the merge job below.

## merge job

after every PR the run opened is judged, read `.github/claude-pass/automerge.md` and follow it. it owns the disposition table, the flip-flop rule, the always-human list, the billing-rule write shape, and the merge mechanics. the summary:

- classify each PR: merge-eligible (verified, flip-flop, confirmed deprecation/retirement) or needs human (seed PRs, code PRs, promo/tier/free-tier rule changes, bot-blocked pages, anything unverified)
- post the `needs human` comment on every excluded PR
- a confirmed deprecation/retirement: write the `data/billing-rules.json` entry on that PR branch, bump the `len(rules) == N` pin in `tests/test_billing_rules.py` in the same commit, then treat the PR as merge-eligible
- merge the eligible set with `uv run ai-pricelog-automerge <branch>...`, oldest PR first, newest last. the script refuses the seed branch, code PRs, and anything outside the pipeline file set, so pass it only what you judged
- if the script fails: do not retry it; report the error in your final message, leave every PR open, delete nothing

## row schema

each source's rows live in `data/history/<source>.ndjson`, one json object per line:

```json
{"schema":4,"source":"deepseek","model_id":"deepseek-v4-pro","observed_at":"2026-08-30","effective_at":"2026-08-23","currency":"EUR","rates":{"input":0.66,"output":1.98,"cache_read":0.022},"overrides":[{"when":{"days":["monday"],"window":[100,400],"timezone":"Asia/Shanghai"},"rates":{"input":1.32}},{"when":{"min_tokens":128000},"rates":{"input":0.5}},{"quota_multiplier":0.4}],"fees":{"web_search":0.005},"limits":{"context":1048576,"output":393216},"unmapped":{"someNewSourceKey":1},"provenance":{"url":"https://api-docs.deepseek.com/quick_start/pricing/","name":"DeepSeek V4 Pro","fx_rate":1.1643,"fx_rate_date":"2026-08-28"}}
```

- `rates` holds every per-token price, USD per 1M tokens, keyed by axis (`input`, `output`, `cache_read`, `cache_write`, `cache_write_1h`, plus the modality axes `image`, `audio`, `input_audio_cache`, `internal_reasoning`, `image_output`, `audio_output`). each rate derives from a per-token string x 1e6, rounded to 6 decimals. a new axis is a new key inside `rates`, never a top-level key.
- `limits` holds token counts, never currency-converted: `context` is the context window and `output` the max output length; both optional.
- `currency` (default `USD`) names the source quote; `provenance.fx_rate` + `provenance.fx_rate_date` are the conversion provenance and never join the diff; the rate fields always hold USD. `provenance` carries `url`, `name`, and the fx pair. `effective_at` (optional) is the date the rate or schedule becomes effective; absent = valid at observation.
- a change = any present comparable field differs from the last row for `(source, model_id)`. `observed_at` and `provenance` are excluded from the diff.
- `overrides` is the one list for every conditional price. an entry carries `rates` and/or `quota_multiplier` (a consumption weight; consumers never price from a multiplier) plus a `when`: optional `days` (lowercase weekday names, absent = every day), optional `window` (`[start_hhmm, end_hhmm]`, absent = whole day), optional `min_tokens` (a volume threshold), optional `timezone`. an absent rate axis inherits the base `rates` value; later entries override earlier matching ones. `timezone` rides inside the override's `when`, never the row. deepseek peak rows map onto override entries: the base `rates` are the off-peak rates, one entry per peak window carries the peak rates plus the weekday day-set.
- openrouter rows add `provenance.name` and keep only unmapped pricing keys verbatim under `unmapped`. alias entries and dated-canonical snapshots get no row. `web_search` is a per-request USD fee under `fees`, never per-token.
- a removal row carries `{"removed": true}`; the final price snapshot (the last priced row's comparable fields) is optional and a bare row is valid. it means the source stopped listing the model. accept it as valid.
- a zero price is a price: `0.0` rate fields are real rows, negative amounts read as unpriced.
- `data/index.json` is derived, never carried on a branch: the merge regenerates it from the shards, latest row per `(source, model_id)` plus `first_seen`. a removed model keeps its last prices and gains `removed_at`. the top-level `version` mirrors the row schema version.
- `data/schema/row.v4.json` is the row-format contract; a new or renamed top-level row key bumps the version together with the validation key set.
- `data/billing-rules.json` is human-written billing-rule semantics per provider. a channel diff confirming a deprecation or retirement of priced models changes when their rates apply: write the entry into `data/billing-rules.json` on the PR branch yourself (one entry per change, fields like the existing entries: `id` as `<provider>-<what>-<date>`, `provider`, `effective`, `timezone`, `statement` naming the models and their migrations, `citation` = the channel url) and name it in your comment. other rule classes (rate and tier changes, promo windows, free-tier flips) stay flagged for the human, who owns those calls.

## source urls

`providers.toml` carries one section per watched provider: `detector_url` / `scraper_url` (the pages), `announce_urls` (the watched channels). openrouter rows come from `https://openrouter.ai/api/v1/models`.

## domain quirks

per-source page and channel facts the pass judges rows against. this file holds them: the pass runs on a checkout with no `docs/` tree, so nothing else can.

### provider page facts, 2026-08-24 re-probe additions

measured 2026-08-24 against the pinned pricing-page snapshots (tests/fixtures/<provider>_page/pricing.html) and live target ymls.

- together: stale HF-style ids. our page ids are lowercase-hyphen slugs from the two `Model | Input | output` tables (chat + vision, merged by slug, first table wins); the batch toggle carries no static rates. cached column -> cache_read. dedup: `llama-3.3-70b` -> `meta-llama/Llama-3.3-70B-Instruct-Turbo`, `llama-3-8b-instruct-lite` -> `meta-llama/Meta-Llama-3-8B-Instruct-Lite` (same endpoints, together's api strings). openrouter lists no `together/` prefix. the fine-tuning "Specialized pricing" table carries models absent from the per-token tables (kimi k2.7-code, grouped with kimi k2.6); absence keys on the per-token tables only. OBSERVED 2026-08-29 (PR 66 review).
- novita: stale; ids come from the page's own card hrefs resolved through the embedded next.js flight state to canonical api ids (`deepseek/deepseek-v4-pro-0813`, `zai-org/glm-5.2`). rates from span title attrs, cache-read from the `data-pricing-key="cache-read"` wrapper, context -> max_tokens_in. promo cards render four titled spans in the input cell (promo input, promo cache, list input, list cache); input/output take the first span and cache-read the second (the rate in force). OBSERVED 2026-08-30 (live glm-5.3-flash card). tiered/omnimodal cards -> None. dedup: `deepseek/deepseek-r1-0528` -> `deepseek/deepseek-r1`, `deepseek/deepseek-v3-0324` -> `deepseek/deepseek_v3` (underscore spelling). no openrouter `novita/` prefix.
- cohere: the page mixes prose rates ("Command pricing is $1.00/1M tokens for input and $2.00/1M tokens for output") with a per-instance model-vault table whose cells are not per-token (-> None). the current model cards (Command R 0.15/0.60, R7B 0.0375/0.15, Embed 4 0.12/1M with output 0) live only in the embedded `__next_f` flight payload, not the rendered html; rerank cards bill per 1K searches and stay excluded. slug rule: lowercase, `+` -> `plus`, non-alphanumeric runs collapse, dots kept (`rerank-3.5-medium`). pricing cards without dollar rates are excluded from detection. the dated faq ids are the stored ids themselves (re-keyed 2026-08-30), so no dedup and no newest-first ordering; the R+ dated pair stays present via the faq prose even with no model card (re-probed 2026-08-31), so absence counters never start for them. openrouter prefix `cohere/` (5 models).
- google: section-per-model h2s in the pricing docs; canonical id from the heading's em slug (h2 id only as fallback, gemma-4). standard tier only; the first dollar amount in the paid column is the base rate, which handles promo cells ("$0.75 through ..., $1.50 starting ..."), tiered cells (<=200k first), and cache cells (read rate before the storage price). per-image output cells -> None; embedding sections (no output row) price with output 0. dedup: `gemini-3.1-flash-image` -> `gemini-3.1-flash-image-preview`, `gemini-3-pro-image` -> `gemini-3-pro-image-preview`, the dated native-audio/lite preview spellings -> `gemini-live-2.5-flash` / `gemini-2.5-flash-lite`. openrouter prefix `google/` (41 models).
- avian: 4 stale HF entries, no page overlap. card grid `#avModelGrid` only; slug lowercase-hyphen, dots kept (`mimo-v2.5-small`); context K/M -> max_tokens_in (page abbreviation, human reconciles); cache per card; the Dedicated Deployments block is excluded. no openrouter `avian/` prefix.
- groq (wired 2026-08-29, todo #17): `console.groq.com/docs/models.md` serves three pipe tables with a shared header (production 6 rows, systems 2, preview 8). the price cell glues "$X input$Y output" with no separator. per-token rows: 7 (gpt-oss-120b/-20b, gpt-oss-safeguard-20b, llama-prompt-guard-2-22m/-86m, qwen/qwen3.6-27b, qwen/qwen3.8-27b); ContactSales: 3; per-hour: 2; per-char: 2; dash: 2. an Enterprise badge glues onto the api id in the md twin (all badge rows ContactSales today); parse_id strips a glued prefix by suffix-match against the /docs/model/ link tail. no cached-input column; MAX COMPLETION TOKENS -> max_tokens_out (qwen3.8 reads an odd 131,042). the detector emits per-token rows only; rows outside the known shapes (odd cell counts, unknown price-cell text, missing model links) skip with a warning (plan #22), the header pin folds case/whitespace/&/and, a missing table or empty result still raises, and zero-rate rows stay emitted (scrape -> 0.0, free is a price). no watchable announce surface: llms.txt lists only a changelog frozen since 2025-04. this host's egress 403s the page since 2026-08-30 (browser UA too); the actions egress still fetches it, so live re-verification runs on the runner only. OBSERVED 2026-08-30.

### deepseek page move

measured 2026-08-26: the slash-less pricing url serves a ~46KB JS shell, but the trailing-slash form `https://api-docs.deepseek.com/quick_start/pricing/` serves the static docusaurus html (23KB) with the full MODEL table, USD prices, and the peak footnote. the config urls carry the trailing slash; the slash-less path must not come back (the js shell carries no table markers). the footnote gained a "Monday through Friday" clause, which the scraper parses into window_rates day-sets since 2026-08-30. no `.md` twin, llms.txt, or public docs source repo exists; the zh-cn twin is CNY-only.

### deepseek peak schedule

the live pricing page carries v4 peak/off-peak subrows plus the footnote "Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC, Monday through Friday (all other hours are off-peak)". the scraper stores the split schedule as `window_rates` entries (landed 2026-08-30, todo 20): the base mtok fields hold the off-peak rates, one entry per peak window carries the peak rates, `days` = the weekday names, `window` = the [start, end] HHMM UTC pair. rows stored before the move keep flat `peak_*` fields (no history rewrite); the migration fires one refresh row per priced model.

billing rule effective 2026-08-23 00:00 beijing time (billing-rules.json `deepseek-weekend-off-peak`; team email received 2026-08-22): weekdays (monday-friday, beijing time) keep the peak/off-peak split; weekends (saturday-sunday, beijing time) bill uniformly at the off-peak rate. the weekday day-set expresses the rule because every window ends before 16:00 UTC (beijing midnight), so each window's UTC weekday equals its beijing weekday. with the weekday clause present, the scraper raises when a window ends after 16:00 UTC, so a window move past the boundary fails loudly instead of mis-scheduling; without the clause the windows stay expressible (every-day schedules need no weekday equivalence). rows carrying the weekday schedule stamp `effective_at` = the rule date, so consumers clamp sessions from 2026-08-23 on.

### scaleway + databricks (added 2026-08-29, todo #17)

- scaleway: the model-as-a-service page serves the per-1M-token table statically in EUR ("€1.80 / million tokens"), no USD column. ids = Name-cell slugs stored unprefixed; the Try-link modelName query cross-checks when present (parse_id falls back to the Name cell alone when a row carries no link). "Free" output = a zero rate (the embedding convention). known unpriced: per-audio-minute rows. dedup: deepseek-v4-flash-0731 -> deepseek-v4-flash, mistral-small-3.2-24b-instruct-2506 -> mistral-small-3.2-24b-instruct. the committed fixture is a content-derived slice of the live capture (byte offsets drift with css-class hashes; the guard is a fixture-shape pin: one thead row + 15 tbody rows with the complete last-row Try link). announce: docs changelog + its rss (same content twice, harmless).
- databricks: the foundation-model-serving page serves the DBU rate table statically (DBU / M input, output, cache-read tokens per display name, "Kimi K3 42.857 / 214.286 / 4.286"). ids = an explicit display-name dict derived from the stored openrouter id set (vendor prefix stripped; "(Priority)" -> "-priority"; the U+2316 regional-uplift marker strips). a priced row with an unmapped name skips with a warning (plan #22), so one new model can no longer blind the provider; the GLM-5.3 and GLM-5.3 Flash rows mapped 2026-09-02 (the 2026-08-29 dict had neither). the matched row's cells stay strict (an unknown rate-cell shape raises), rows the scan passes over are tolerated. "n/a" output = embedding rows bill input only, stored with output 0.0. dedup: deepseek-v4-pro-0813 -> deepseek-v4-pro, deepseek-v4-flash-0731 -> deepseek-v4-flash. the DBU->USD rate is 0.07 (the pricing-page AI card, client-rendered; cited via google's index + third-party consensus; DBU rates differ per cloud, the announce watches /aws/ so re-probe before trusting another cloud). announce: docs release-notes index (sub-page links client-rendered).

### dashscope omni split (added 2026-08-30)

- the omni pricing tables split the input span into text/audio/image sub-columns and the output span into three modes (text-only, multimodal, text+audio); the header carries the colspans and a sub-header row names the sub-columns. the base rates are the first sub-columns: text input and text-only output (qwen2.5-omni-7b 0.10/0.40, qwen-omni-turbo 0.07/0.27, per 1M). a table whose output span splits with an unsplit input (the Non-Thinking/Thinking tables) reads the same first-output position either way. OBSERVED 2026-08-30 (live model-pricing page).

### announce channels

billing-rule announcement surfaces per provider, watched every run via `providers.toml` `announce_urls`. OBSERVED 2026-08-26 against the live pages.

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

- comment on each PR this run opened: findings plus a verdict line (`verified`, `findings`, or `needs human`). a merged PR's comment states the merge; a `needs human` comment follows the shape in `automerge.md` and opens with the ping line `@uwuclxdy need help wit this`.
- no PR comments when you find nothing: say so in your final message only.
- never comment on PRs the run did not open. the only pushes to the default branch and the only branch-ref deletions are the ones `ai-pricelog-automerge` performs; never do either by hand.
- your final message summarizes per PR: findings, the verdict, and what the merge did (merged / needs human / failed with the script's error); the PR comments are the durable record.
