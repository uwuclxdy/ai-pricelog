<div align="center">

# autopr-genai-prices

**watch model releases, open draft PRs to a genai-prices-layout repo**

detectors scrape each provider's own docs and pricing pages daily, one draft PR per new model, a human verifies prices and marks it ready

![ci](https://shields.uwuclxdy.dev/github/actions/workflow/status/uwuclxdy/autopr-genai-prices/ci.yml?branch=mommy) ![license](https://shields.uwuclxdy.dev/github/license/uwuclxdy/autopr-genai-prices)

</div>

## What it does

a daily GitHub Actions run watches model companies for new releases and opens draft PRs adding pricing entries to a LiteLLM-layout repo's `model_prices_and_context_window.json`. nothing merges without a human reading the prices.

## How it works

| step | what happens |
|---|---|
| detect | each provider's page is parsed for its current model list (no API keys, all sources are static pages) |
| diff | new ids vs the git-backed state file's `last_seen` and `handled` |
| dedup | ids already in the target repo's file are dropped (upstream beat us), plus provider-specific key spellings |
| scrape | input/output price per token from the provider's pricing page; missing price = retry next run |
| validate | provider vocab, mode, costs and max_tokens checked against LiteLLM's live file |
| pr | branch pushed, draft PR opened, max 3 open drafts per run |
| state | PR'd ids recorded in `handled` (never re-fires), state committed and pushed |

## Watched providers

| provider | namespace | detection + pricing source |
|---|---|---|
| deepseek | `deepseek/` | api-docs.deepseek.com pricing page |
| zai | `zai/` | docs.z.ai pricing page |
| moonshot | `moonshot/` | platform.kimi.ai models + pricing pages |
| minimax | `minimax/` | platform.minimax.io models + pricing pages |
| dashscope | `dashscope/` | aliyun CN model tables + alibabacloud intl pricing |
| xai | `xai/` | docs.x.ai models blob |
| mistral | `mistral/` | docs.mistral.ai model cards + pricing |
| perplexity | `perplexity/` | docs.perplexity.ai pricing |

volcengine (doubao) ships as dormant code: static pricing exists only in CNY on the CN plaza, so the config skips it until a USD source appears. dropped at the mapping gate: baidu, tencent, 01.AI, inflection, nous (no official litellm namespace), meta_llama, nvidia_nim, amazon_nova, cohere (no static pricing), stability (images-only, per-image credits).

## Setup

```sh
uv sync --frozen
export REPO=https://github.com/<owner>/<litellm-layout-repo>
uv run autopr-genai-prices
```

`REPO` is the only required input. clone source, base branch, push target and PR target all derive from it. push permission decides the flow: the token can push to `REPO` and the PR opens in-repo, or it cannot and the run forks first. no fork detection, one code path.

in Actions the run uses the `REPO` and `GH_TOKEN` repo secrets; `GH_TOKEN` is a PAT with `repo` scope (GITHUB_TOKEN only reaches the autopr repo itself). schedule: daily 05:17 utc, or `workflow_dispatch`.

## Configuration

`providers.toml` holds one section per provider:

```toml
[settings]
cap = 3 # max open drafts per run

[deepseek]
provider = "deepseek"   # the litellm_provider value
namespace = "deepseek"  # the key prefix in the prices file
detector = "deepseek_page"
detector_url = "https://api-docs.deepseek.com/quick_start/pricing"
scraper = "deepseek_page"
scraper_url = "https://api-docs.deepseek.com/quick_start/pricing"
```

`detector`/`scraper` name modules under `autopr_genai_prices.{detectors,scrapers}`; adding a provider is a config section plus a module pair. `LITELLM_FILE_URL` overrides the live-file fetch (default: the litellm main-branch raw url).

## Development

```sh
uv run ruff check
uv run ruff format --check
uv run pytest -q
```

tests pin live-page fixtures per provider; nothing hits the network in the suite.

## License

MIT
