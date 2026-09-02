<div align="center">

# ai-pricelog

**the biggest auto-updated genai pricing index: complete dated price history per model, peak/off-peak rates**

detectors scrape provider pricing pages and the openrouter api daily. every observed change lands as a dated row, reviewed by a human before it merges

![ci](https://shields.uwuclxdy.dev/github/actions/workflow/status/uwuclxdy/ai-pricelog/ci.yml?branch=mommy) ![license](https://shields.uwuclxdy.dev/github/license/uwuclxdy/ai-pricelog)

</div>

<!-- stats:start -->
| metric | value |
|---|---|
| models tracked | **1,097** |
| sources | 29 |
| dated rows | 2,035 |
| canonical models | 191 |
| history | since 2023-03-01 (1,282 days) |
<!-- stats:end -->

## What it is

one repo holds two files:

| file | contents |
|---|---|
| `data/history.ndjson` | one dated row per observed price change, plus a removal row per delisted model, appended forever |
| `data/index.json` | the current price of every watched model, generated from the history |

a row:

```json
{"source":"deepseek","model_id":"deepseek-v4-pro","observed_at":"2026-08-30","input_mtok":0.435,"output_mtok":0.87,"cache_read_mtok":0.0036,"max_tokens_in":1048576,"max_tokens_out":393216,"window_rates":[{"days":["monday","tuesday","wednesday","thursday","friday"],"window":[100,400],"input_mtok":0.87,"output_mtok":1.74},{"days":["monday","tuesday","wednesday","thursday","friday"],"window":[600,1000],"input_mtok":0.87,"output_mtok":1.74}],"effective_at":"2026-08-23","url":"https://api-docs.deepseek.com/quick_start/pricing"}
```

a removal row (one per source/model ever; the index stamps the entry `removed_at` until the model reappears):

```json
{"source":"deepseek","model_id":"deepseek-legacy","observed_at":"2026-08-26","removed":true}
```

git history is the changelog. every price a model ever had stays in the history file.

## How it works

| step | what happens |
|---|---|
| detect | each provider's page is parsed for its current model list (no api keys, all sources are static pages) |
| diff | new ids vs the store + open PRs |
| scrape | input/output + cache-tier prices per token from the provider's pricing page (deepseek's peak/off-peak schedule included); missing price = retry next run |
| store | a row appends only when the price differs from the last stored row for that model |
| delist | a stored model absent from its source twice, both observations merged, gets a removal row and a `Mark ... delisted` draft PR |
| pr | one draft PR per source per run, removal and price rows mixed, no cap; nothing merges without a human reading the prices |

the openrouter source stores the full keyless model list the same way. the first run with an empty store opens one seed PR with the full snapshot.

## Sources

| provider | detection + pricing source |
|---|---|
| deepseek | api-docs.deepseek.com pricing page |
| zai | docs.z.ai pricing page |
| moonshot | platform.kimi.ai models + pricing pages |
| minimax | platform.minimax.io models + pricing pages |
| xai | docs.x.ai models blob |
| mistral | docs.mistral.ai model cards + pricing |
| perplexity | docs.perplexity.ai pricing |
| together | together.ai pricing |
| novita | novita.ai pricing |
| cohere | cohere.com pricing |
| google | ai.google.dev gemini pricing docs |
| avian | avian.io pricing |
| fireworks | docs.fireworks.ai serverless pricing |
| deepinfra | deepinfra.com pricing |
| cloudflare | developers.cloudflare.com workers-ai pricing |
| watsonx | ibm.com watsonx.ai pricing |
| baseten | baseten.co pricing |
| digitalocean | docs.digitalocean.com inference pricing |
| sambanova | cloud.sambanova.ai pricing |
| publicai | platform.publicai.co models |
| ai21 | ai21.com pricing |
| openai | platform.openai.com docs pricing |
| anthropic | platform.claude.com docs pricing markdown twin |
| cerebras | api.cerebras.ai public models api |
| dashscope | alibabacloud model-studio intl pricing + CN model list |
| groq | console.groq.com models markdown twin |
| scaleway | scaleway.com model-as-a-service pricing (EUR via fx) |
| databricks | databricks.com foundation model serving pricing (DBU) |
| openrouter | openrouter.ai public models api (all models) |

dormant, commented out in `providers.toml`: volcengine (CNY-only).

## Setup

```sh
uv sync --frozen
uv run ai-pricelog
```

`GH_TOKEN` (a PAT with repo scope) is what opens the draft PRs. the scheduled GitHub Actions run carries it as a secret. schedule: every 2h (plus a weekly moonshot smoke), or `workflow_dispatch`.

## Configuration

`providers.toml` holds one section per provider:

```toml
[deepseek]
detector = "deepseek_page"
detector_url = "https://api-docs.deepseek.com/quick_start/pricing"
scraper = "deepseek_page"
scraper_url = "https://api-docs.deepseek.com/quick_start/pricing"
```

`detector`/`scraper` name modules under `ai_pricelog.{detectors,scrapers}`; adding a provider is a config section plus a module pair.

## FAQ

**where do i find the current price of a model?**

`data/index.json` under `sources`, keyed by provider and model id.

**how do i see every price a model ever had?**

```sh
rg 'deepseek-v4-pro' data/history.ndjson
```

each matching row is one observed change.

**what does a peak/off-peak model look like?**

deepseek rows carry `window_rates`: the plain `input_mtok`/`output_mtok` are the off-peak default, and one entry per peak window overrides them with the peak rates on its `days` (weekdays, matching the beijing-time weekend rule; `effective_at` stamps the rule's date).

## Comparison

| | ai-pricelog | pydantic/genai-prices |
|---|---|---|
| what | dated price history repo | generated pricing dataset for python/js packages |
| updates | automation + human review per change | human PRs into provider ymls |
| history | every observed change since the first sighting | dated conditional entries where contributors add them |
<!-- stats-row:start -->| models | **1,097** tracked across 29 sources, history back to 2023-03-01 | ~1.5k models, 36 providers in the generated dataset (measured 2026-08-26) |<!-- stats-row:end -->

## Development

```sh
uv run ruff check
uv run ruff format --check
uv run pytest -q
```

tests pin live-page fixtures per provider; nothing hits the network in the suite.

## License

MIT
