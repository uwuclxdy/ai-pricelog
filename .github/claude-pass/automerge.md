# automerge: the pass-side merge of verified pipeline PRs

the claude pass merges the draft PRs it verified itself. read this file before classifying anything. `.github/claude-pass/prompt.md` owns the review job; this file owns the merge job.

## disposition table

| verdict | action |
|---|---|
| verified | union-merge via `ai-pricelog-automerge` |
| flip-flop | land (merge); the next run appends the correction |
| deprecation/retirement confirmed | write the billing rule + bump its test pin, then merge |
| everything else | `needs human` comment, no merge |

## what counts as verified

a row is verified when you re-read its rate on its `url` page (the api for openrouter rows) and it matches. the PR body checklist and any earlier pass comment are leads, never evidence. a removal row is verified when the model is absent from its live source. an unverifiable row (bot wall, fetch failure) never merges.

## the flip-flop disposition

openrouter reseller rates flip-flop: a row can record a transient the api reverted in a day. land a row that differs from today's api when BOTH hold:

1. today's api value equals the prior stored row for (source, model_id) (read the last row from `git show origin/mommy:data/history.ndjson`)
2. the row itself records the transient state it saw

the next run appends the correction row. precedents (ruled 2026-09-02): gryphe/mythomax-l2-13b (0.35/0.6 for one day), qwen/qwen3-235b-a22b-2507 (0.09/0.55), deepseek/deepseek-v4-pro-0813 (a uniform 1.69x step), deepseek/deepseek-v4-pro (1% reseller drift), and tencent/hy3's base-rate oscillation (0.132/0.0825 across runs; its window_rates carry the schedule either way). when a flip-flop row's correction does not arrive on the next run, the class flips from transient to misread: comment needs human and point at `openrouter.py`.

## always human: comment needs-human and stop

| case | how to recognize it |
|---|---|
| seed PR | the branch is `pricelog/seed` (the first full snapshot; never automerged) |
| code PR | the branch diff changes any file outside `data/history.ndjson`, `data/index.json`, `README.md`, `data/announce.json`, `data/absence.json`, `data/billing-rules.json`, `tests/test_billing_rules.py` |
| other billing-rule classes | rate changes, tier changes, promo windows, free-tier flips: name the semantics and flag them for the human, who owns those calls |
| unverifiable rows | the source page fetch fails (bot wall, 403) |
| ambiguous announce semantics | the rubric answer is not clear-cut |

## billing rules the pass may write

a confirmed deprecation or retirement of priced models (the channel prose names the models and the change in when their rates apply):

- append ONE entry at the END of the `rules` array in `data/billing-rules.json`: `id` as `<provider>-<what>-<date>`, `provider`, `effective` (YYYY-MM-DD), `timezone`, `statement` naming the models and their migrations, `citation` = the channel url
- in the SAME commit bump the count pin: `tests/test_billing_rules.py` `test_committed_billing_rules_pass_schema` asserts `len(rules) == N`. the rules and the pin land atomically, or the next CI run reds
- edit the file on the PR branch, name the rule in your comment, then merge the branch

## the merge

after every PR is judged: comment on the needs-human PRs, then run

```
uv run ai-pricelog-automerge <branch>...
```

with the merge-eligible branches in order, oldest PR first, newest last. the script:

- refuses non-`pricelog/` branches, the seed branch, and any branch touching files outside the pipeline set
- per branch: a two-parent merge commit, exact-line history union (HEAD's lines first, the branch's new lines appended; a key-based union drops same-day update rows, so the dedupe is exact lines only), `index.json` and the README stats regenerated via the pipeline's own codepath
- `announce.json` + `absence.json`: HEAD's copies during intermediate merges; the last (newest) branch's copies with the final merge (every branch of one run carries the same fresh snapshots)
- verifies each branch head is an ancestor of the result (the auto-mark precondition), then pushes the default branch and deletes the branch refs

github auto-marks each PR merged once its head lands in the default branch. the push uses the checkout's persisted token, so no workflow re-runs fire; the script regenerates everything itself.

when the script fails: do not retry it. report the error in your final message, leave every PR open, delete nothing. the next run re-derives the rows.

## hard bans

- never push the default branch except through `ai-pricelog-automerge`
- never delete branch refs except through the script
- never merge a seed PR, a code PR, or a PR with unverified rows
- never comment on PRs the run did not open
- never edit rows on a branch except a row error you re-verified against the page (prompt.md step 5)

## quirks that change a judgment

- removal checks on js-heavy pages (fireworks serves a shell): run the repo's own detector against the live page instead of substring-matching rendered text; the ids live in the embedded payload
- groq verifies only from the runner's egress (this host 403s the page); the pass runs there, so the re-check works where the pipeline ran
- openrouter overrides live under `pricing.overrides` as a list, never a top-level `overrides` key; wrap windows split into two entries at build

## needs-human comment shape

every needs-human PR gets a comment opening with the ping line, posted as cloudybot (the pass runs with the bot's PAT in `GH_TOKEN`):

```markdown
@uwuclxdy need help wit this

<one line: what could not be settled>

<what you checked and what blocked it>

<what to decide>
```

the mention is what reaches the human; the rest is for the thread. end on the last substantive line. no sign-off.
