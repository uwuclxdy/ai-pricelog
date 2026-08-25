<div align="center">

# ai-pricelog

**watch model releases and price changes, open draft PRs to `pydantic/genai-prices`**

detectors scrape each provider's own docs and pricing pages daily, one draft PR per new model or drifted price, a human verifies prices and marks it ready

![ci](https://shields.uwuclxdy.dev/github/actions/workflow/status/uwuclxdy/ai-pricelog/ci.yml?branch=mommy) ![license](https://shields.uwuclxdy.dev/github/license/uwuclxdy/ai-pricelog)

</div>

## What it does

a daily GitHub Actions run watches model companies for new releases and price changes and opens draft PRs against the target repo's `prices/providers/*.yml` and `openrouter.yml`. new models get added entries; a tracked model whose live page drifts from the yml gets an update PR (a dated conditional entry for flat rate changes per the target's never-overwrite rule, a list-form conversion when the page turns split-priced, and a named deviation for list-form drift the schema cannot express). a follow-up pass fills deferred openrouter entries once the openrouter API lists them. each PR runs the target's own `make build`, `make test` and pre-commit in a clone before opening, and pins a generated `calc_price` test with the real computed values. nothing merges without a human reading the prices.

## How it works

| step | what happens |
|---|---|
| detect | each provider's page is parsed for its current model list (no API keys, all sources are static pages) |
| diff | new ids vs the git-backed state file's `last_seen` and `handled` |
| pending | ids named in an open PR on the real `pydantic/genai-prices` are skipped for this run (no state change) |
| dedup | ids already matched by the provider yml's match clauses are settled, plus provider-specific spelling hooks (mistral's compacted dates, xai's dated snapshots) |
| scrape | input/output price per token from the provider's pricing page (deepseek's peak/off-peak schedule included); missing price = retry next run |
| refresh | tracked models re-scrape each run; drift vs the yml opens an update PR (dated append, split conversion, or a replaced block with the deviation named), openrouter.yml mirrored when its API already lists the new rates |
| follow-up | handled ids whose vendor entry landed but whose openrouter entry deferred get an openrouter-only PR once the API lists them |
| build | vendor + openrouter entries inserted in a fresh clone, `make build`, a generated + self-verified `calc_price` test, `make test`, pre-commit, then commit |
| pr | branch pushed (fork when the token cannot push), draft PR opened, max 3 open drafts per run |
| state | PR'd ids recorded in `handled` (never re-fires), state committed and pushed; updates and follow-ups write no state |

## Watched providers

| provider | yml | openrouter prefix | detection + pricing source |
|---|---|---|---|
| deepseek | `deepseek.yml` | `deepseek/` | api-docs.deepseek.com pricing page |
| zai | `zai.yml` | `z-ai/` | docs.z.ai pricing page |
| moonshot | `moonshotai.yml` | `moonshotai/` | platform.kimi.ai models + pricing pages |
| minimax | `minimax.yml` | `minimax/` | platform.minimax.io models + pricing pages |
| xai | `x_ai.yml` | `x-ai/` | docs.x.ai models blob |
| mistral | `mistral.yml` | `mistralai/` | docs.mistral.ai model cards + pricing |
| perplexity | `perplexity.yml` | `perplexity/` | docs.perplexity.ai pricing |

dormant, commented out in `providers.toml`: dashscope (the target tracks no first-party qwen yml), volcengine (doubao pricing is CNY-only on the CN plaza). dropped at the mapping gate: baidu, tencent, 01.AI, inflection, nous, meta_llama, nvidia_nim, amazon_nova, cohere, stability.

## Setup

```sh
uv sync --frozen
export REPO=https://github.com/pydantic/genai-prices
uv run ai-pricelog
```

`REPO` is the only required input. clone source, base branch, push target and PR target all derive from it. push permission decides the flow: the token can push to `REPO` and the PR opens in-repo, or it cannot and the run forks first. no fork detection, one code path. one exception: the pending-PR check always scans the real `pydantic/genai-prices`, never `REPO`.

in Actions the run uses the `REPO` and `GH_TOKEN` repo secrets; `GH_TOKEN` is a PAT with `repo` scope (GITHUB_TOKEN only reaches the autopr repo itself). schedule: daily 05:17 utc, or `workflow_dispatch`.

## Configuration

`providers.toml` holds one section per provider:

```toml
[settings]
cap = 3 # max open drafts per run

[deepseek]
yml = "deepseek.yml"     # the target's prices/providers/<yml>
or_prefix = "deepseek"   # the openrouter slug prefix
detector = "deepseek_page"
detector_url = "https://api-docs.deepseek.com/quick_start/pricing"
scraper = "deepseek_page"
scraper_url = "https://api-docs.deepseek.com/quick_start/pricing"
```

`detector`/`scraper` name modules under `ai_pricelog.{detectors,scrapers}`; adding a provider is a config section plus a module pair.

## Development

```sh
uv run ruff check
uv run ruff format --check
uv run pytest -q
```

tests pin live-page fixtures per provider; nothing hits the network in the suite.

## License

MIT
