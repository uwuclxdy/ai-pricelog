# automerge: the dispositions that drive the merge of verified pipeline PRs

the claude pass judges the draft PRs and posts a merge disposition on each; it never merges. read this file before classifying anything. `.github/claude-pass/prompt.md` owns the review job; this file owns the disposition rules.

## disposition table

| verdict | action |
|---|---|
| verified | post the marker `automerge: yes` |
| flip-flop | post `automerge: yes`; the next run appends the correction |
| deprecation/retirement confirmed | write the billing rule + bump its test pin, then post `automerge: yes` |
| everything else | `needs human` comment, post `automerge: no` |

every PR comment the pass posts ends with exactly one machine line — `automerge: yes` or `automerge: no` — as the last line of the body. a PR with no comment or no marker line is never merged: the merge step's conservative default.

## what counts as verified

a row is verified when you re-read its rate on its `url` page (the api for openrouter rows) and it matches. the PR body checklist and any earlier pass comment are leads, never evidence. a removal row is verified when the model is absent from its live source. an unverifiable row (bot wall, fetch failure) never merges.

## the flip-flop disposition

openrouter reseller rates flip-flop: a row can record a transient the api reverted in a day. land a row that differs from today's api when BOTH hold:

1. today's api value equals the prior stored row for (source, model_id) (read the last row from `git show origin/mommy:data/history/<source>.ndjson`)
2. the row itself records the transient state it saw

a rate that moved again since the row leaves condition 1 unanswerable against today's api. a later run settles it: every run diffs the api against `origin/mommy`, so a newer branch carrying no row for that (source, model_id) proves the api was back at the prior stored value when it ran. that silence is the revert.

the next run appends the correction row. precedents (ruled 2026-09-02): gryphe/mythomax-l2-13b (0.35/0.6 for one day), qwen/qwen3-235b-a22b-2507 (0.09/0.55), deepseek/deepseek-v4-pro-0813 (a uniform 1.69x step), deepseek/deepseek-v4-pro (1% reseller drift), and tencent/hy3's base-rate oscillation (0.132/0.0825 across runs; its window_rates carry the schedule either way). when a flip-flop row's correction does not arrive on the next run, the class flips from transient to misread: comment needs human and point at `openrouter.py`.

## always human: comment needs-human and stop

| case | how to recognize it |
|---|---|
| seed PR | the branch is `pricelog/seed` (the first full snapshot; never automerged) |
| code PR | the branch diff changes any file outside `data/history/`, `state/announce/`, `state/absence/`, `data/catalog/models.json`, `data/catalog/billing-rules.json`, `tests/test_billing_rules.py` |
| other billing-rule classes | rate changes, tier changes, promo windows, free-tier flips: name the semantics and flag them for the human, who owns those calls |
| unverifiable rows | the source page fetch fails (bot wall, 403) |
| ambiguous announce semantics | the rubric answer is not clear-cut |

## billing rules the pass may write

a confirmed deprecation or retirement of priced models (the channel prose names the models and the change in when their rates apply):

- append ONE entry at the END of the `rules` array in `data/catalog/billing-rules.json`: `id` as `<provider>-<what>-<date>`, `provider`, `effective` (YYYY-MM-DD), `timezone`, `statement` naming the models and their migrations, `citation` = the channel url
- in the SAME commit bump the count pin: `tests/test_billing_rules.py` `test_committed_billing_rules_pass_schema` asserts `len(rules) == N`. the rules and the pin land atomically, or the next CI run reds
- edit the file on the PR branch, name the rule in your comment, then mark the PR `automerge: yes`

## the merge

after every PR is judged and every comment posted, your part is done: you never run the merge. the workflow's `merge verified PRs` step runs `ai-pricelog-merge-verified` after the pass — even a pass killed at its step timeout — which reads the run log for this run's PRs, reads each open PR's comments for the pass's marker, and hands the eligible branches to `ai-pricelog-automerge` in PR-number order, oldest PR first, newest last. the script:

- refuses a checkout that is not the default branch (or at its remote tip): every pricelog branch is a base descendant, so a merge started elsewhere would push as a fast-forward and ride that branch's own unverified commits into the default branch's history
- refuses non-`pricelog/` branches, the seed branch, and any branch touching files outside the pipeline set
- every line of the branch's copy must read as one json object per line, and each line the union appends must pass the row contract (`data/schema/row.v4.json`); a refused line stops the merge naming the branch and its line in the branch's own copy (`origin/<branch>:<path>`)
- per branch: a two-parent merge commit, exact-line history union per shard the branch touched (HEAD's lines first, the branch's new lines appended; a key-based union drops same-day update rows, so the dedupe is exact lines only), the union re-sorted on `(model_id, observed_at)`
- `state/announce/`: every branch's copy lands in merge order, so the final (newest) write is the freshest snapshot and a burst spanning runs resolves its own add/add conflicts. `state/absence/<source>.json`: each file comes from the newest branch that carries it (a burst of one run carries one shared snapshot, so single-run behavior is unchanged)
- verifies each branch head is an ancestor of the result (the auto-mark precondition), then pushes the default branch and deletes the branch refs

github auto-marks each PR merged once its head lands in the default branch. the merge writes no derived file: the publish workflow owns the `dist` branch and the README stats outright, and a `GITHUB_TOKEN` automerge push starts no workflow run, so dist catches up on the next PAT or human push.

when the script fails: the merge step reds the run, every PR stays open, and nothing is retried. the next run re-derives the rows.

## hard bans

- never push the default branch except through `ai-pricelog-automerge` or the workflow's `merge verified PRs` step
- never delete branch refs by hand
- never mark a seed PR, a code PR, or a PR with unverified rows `automerge: yes`
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
