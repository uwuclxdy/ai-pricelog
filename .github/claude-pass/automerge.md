# automerge: the dispositions that drive the merge of verified pipeline PRs

the claude pass judges the draft PRs and posts a merge disposition on each; it never merges. read this file before classifying anything. `.github/claude-pass/prompt.md` owns the review job; this file owns the disposition rules.

## disposition table

| verdict | action |
|---|---|
| verified | post the marker `automerge: yes <head sha>` |
| flip-flop | post `automerge: yes <head sha>`; the next run appends the correction |
| deprecation/retirement confirmed | write the billing rule + bump its test pin, then post `automerge: yes <head sha>` |
| everything else | `needs human` comment, post `automerge: no <head sha>` |

every PR comment the pass posts ends with exactly one machine line — `automerge: yes <head sha>` or `automerge: no <head sha>`, `<head sha>` = the PR's head oid read at review time (`gh pr view "$PR_NUMBER" --json headRefOid --jq .headRefOid`) — as the last line of the body. the verdict names the head it judged, nothing else: a disposition without the head sha is not merge-eligible, the merge step compares the stamp to the PR's current head oid and merges only a branch whose head still equals the head the stamp names, and a moved head re-queues the PR for review. a PR with no comment or no marker line is never merged: the merge step's conservative default.

## what counts as verified

a row is verified when you re-read its rate on its `url` page (the api for openrouter rows) and it matches. the PR body checklist and any earlier pass comment are leads, never evidence. a removal row is verified when the model is absent from its live source. an unverifiable row (bot wall, fetch failure) never merges.

## the flip-flop disposition

a row that matches today's api is the verified class whatever the prior stored row says — the flip-flop rule below binds only rows that differ from today's api (a PR 296 misroute, 2026-09-21).

openrouter reseller rates flip-flop: a row can record a transient the api reverted in a day. land a row that differs from today's api when BOTH hold:

1. today's api value equals the prior stored row for (source, model_id) (read the last row from `git show origin/mommy:data/history/<source>.ndjson`)
2. the row itself records the transient state it saw

a rate that moved again since the row (today's api matches neither the row nor the prior stored row) leaves condition 1 unanswerable: comment needs human. a newer branch's silence settles nothing: the pipeline diffs the api against the landed rows plus every open PR's rows and holds every (source, model_id) an open PR's branch would append a row for over the landed shard (the landed rows every branch carries hold nothing, and the PR's title and body play no part), so no later run can record a NEW row for this (source, model_id) while this PR stays open.

the next run appends the correction row. precedents (ruled 2026-09-02): gryphe/mythomax-l2-13b (0.35/0.6 for one day), qwen/qwen3-235b-a22b-2507 (0.09/0.55), deepseek/deepseek-v4-pro-0813 (a uniform 1.69x step), deepseek/deepseek-v4-pro (1% reseller drift), and tencent/hy3's base-rate oscillation (0.132/0.0825 across runs; its window_rates carry the schedule either way). when a flip-flop row's correction does not arrive on the next run, the class flips from transient to misread: comment needs human and point at `openrouter.py`.

## always human: comment needs-human and stop

| case | how to recognize it |
|---|---|
| seed PR | the branch is `pricelog/seed` (the first full snapshot; never automerged) |
| code PR | the branch diff changes any file outside `data/history/`, `state/announce/`, `state/absence/`, `data/catalog/models.json`, `data/catalog/billing-rules.json`, `tests/test_billing_rules.py` |
| other billing-rule classes | rate changes, tier changes, promo windows, free-tier flips: name the semantics and flag them for the human, who owns those calls |
| unverifiable rows | the source page fetch fails (bot wall, 403) |
| ambiguous announce semantics | the rubric answer is not clear-cut |
| an older run's PR whose own rows already landed | every own row of the PR already sits in `git show origin/mommy:data/history/<source>.ndjson` through a newer sibling that copied them: the PR lands nothing of its own, so the needs-human comment names that sibling and the human closes it |

## billing rules the pass may write

a confirmed deprecation or retirement of priced models (the channel prose names the models and the change in when their rates apply):

- append ONE entry at the END of the `rules` array in `data/catalog/billing-rules.json`: `id` as `<provider>-<what>-<date>`, `provider`, `effective` (YYYY-MM-DD), `timezone`, `statement` naming the models and their migrations, `citation` = the channel url
- read every statement off the channel's snapshot on the newest branch that carries it (`git show origin/<branch>:state/announce/<source>/<slug>.md`) before writing it, never off an older PR's copy
- in the SAME commit bump the count pin: `tests/test_billing_rules.py` `test_committed_billing_rules_pass_schema` asserts `len(rules) == N`. the rules and the pin land atomically, or the next CI run reds
- edit the file on the PR branch, name the rule in your comment, then mark the PR `automerge: yes <head sha>`

## the merge

after every PR is judged and every comment posted, your part is done: you never run the merge. the workflow's `merge verified PRs` step runs `ai-pricelog-merge-verified` after the pass — even a pass killed at its step timeout — which reads every open `pricelog/` PR's comments for the pass's marker and hands the eligible branches to `ai-pricelog-automerge` in PR-number order, oldest PR first, newest last; the step resets its checkout to the base branch first (the pass may leave it on a review branch); a yes-marked PR a failed merge step stranded stays eligible and merges on the next run's merge step (the step runs every run). the script:

- fetches the base and the burst refs before any check reads them: the CI checkout's origin/* refs are minutes old and a branch a sibling run or a human pushed since the job's fetch is invisible to them (the 2026-09-22 `unknown revision` red)
- refuses a checkout that is not the default branch at or ahead of its remote tip: every pricelog branch is a base descendant, so a merge started elsewhere would push as a fast-forward and ride that branch's own unverified commits into the default branch's history, and a checkout BEHIND the tip (a local `--no-push` run advances past it, never lags it) would merge over rows that already landed upstream — refused by name instead of by a push rejection
- refuses non-`pricelog/` branches, the seed branch, and any branch touching files outside the pipeline set
- pre-gates every branch against explicit churn bounds (50 models created, 50 removed, 500 rows appended per branch, counted against the burst base): a branch beyond any bound returns an `unsafe` refusal naming the three counts, the merge step reds and every PR stays open. `--human` (never passed by CI) waives the bounds and logs the waived counts for the record
- refuses any appended price row whose `(source, model_id)` no catalog claims: neither HEAD's models.json nor any branch of the burst carries the claim (the pipeline seeds each new key on the branch that carries its row, so a missing claim means a carried row whose seed rides a sibling outside the burst, or no branch at all once that sibling closed). the refusal names the branch and the row. a removal row is exempt: its claim landed with its first price row
- every line of the branch's copy must read as one json object per line, and each line the union appends must pass the row contract (`data/schema/row.v4.json`); a refused line stops the merge naming the branch and its line in the branch's own copy (`origin/<branch>:<path>`)
- per branch: a two-parent merge commit, exact-line history union per shard the branch touched (HEAD's lines first, the branch's new lines appended; a key-based union drops same-day update rows, so the dedupe is exact lines only), the union re-sorted on `(model_id, observed_at)`
- `data/catalog/models.json`: a branch entry whose `(source, model_id)` HEAD already claims is skipped, so a human's twin merge is never resurrected; every other branch entry lands
- `state/announce/`: each channel lands from the burst entry with the newest `fetched` instant (an identical-instant tie goes to the newest branch, the base wins every tie; a legacy date-only entry sorts before every same-day timestamp), so a stale copy — a failed fetch keeping the base sha, or a branch cut before a later landed refresh — never wins; a channel the newest branch's index no longer lists is dropped
- `state/absence/<source>.json`: on every merge, inside a burst or across bursts, the merge compares runs: each side's copy is stamped with the author date of the commit that wrote it (its run's commit), and a branch's change to the file, a new copy or a deletion, lands unless HEAD's copy or deletion comes from a newer run, printing `kept HEAD's <path> over <branch>: HEAD's copy is from a newer run (<head> > <branch>)`, so a held older-run PR merges later without reverting newer counters
- verifies each branch head is an ancestor of the result (the auto-mark precondition), then pushes the default branch and deletes the branch refs

github auto-marks each PR merged once its head lands in the default branch. the merge amends the refreshed README stats into its final merge commit, so the pushed head always satisfies the stats recompute test; the publish workflow owns the `dist` branch outright. a `GITHUB_TOKEN` push starts no workflow run, so after a push lands the merge step dispatches the publish workflow itself; a failed dispatch warns in the run, and the next pushing merge dispatches again.

when the script fails: the merge step reds the run, every PR stays open, and the merge itself is never retried within the run — a yes-marked PR stays eligible, and the next run's merge step picks it up. the next run re-derives the rows.

## hard bans

- never push the default branch except through `ai-pricelog-automerge` or the workflow's `merge verified PRs` step
- never delete a branch ref by hand while its PR is open; a ref whose PR is closed may be deleted
- never mark a seed PR, a code PR, or a PR with unverified rows `automerge: yes <head sha>`
- never comment on a PR outside the `## PRs awaiting review` list
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

the mention is what reaches the human; the rest is for the thread. end on the disposition line `automerge: no <head sha>` (the merge step reads it); no sign-off.
