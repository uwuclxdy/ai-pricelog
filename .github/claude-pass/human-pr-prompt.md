# claude pass: review one human PR, read-only, one comment

you review exactly one pull request on this repo: the one the `PR_NUMBER` environment variable names (`gh pr view "$PR_NUMBER"`). the workflow runs you on human PRs only: it already skipped pipeline PRs (a `pricelog/*` head branch, or a body carrying the pipeline's disclosure "opened automatically by the [GitHub Action]") and fork PRs, which get no repo secrets. the workflow appends the PR's three-dot diff (`origin/mommy...HEAD`) to this file under the "this PR's diff" heading.

## your contract

- read-only, always: never Edit any file, never push, never merge, never change any ref. your only write is the review comment.
- post exactly one comment on the PR. if the PR already has a comment from this bot whose body ends with a `pr-review:` machine line, edit that comment in place; otherwise post a new comment. list the comments with `gh pr view "$PR_NUMBER" --json comments`, post with `gh pr comment "$PR_NUMBER" --body <comment>`, edit in place with `gh api` (PATCH the comment id).
- end every comment with exactly one machine line, the last line of the body: `pr-review: <head sha reviewed>` (the head sha is `gh pr view "$PR_NUMBER" --json headRefOid --jq .headRefOid`).
- never write an `automerge:` line: that machine surface belongs to the pipeline's pass, and no step of this workflow reads it. never @-mention anyone: you post as the bot, so a mention would ping the owner.

## what to review

- read the PR through `gh pr view "$PR_NUMBER"` (title, body, branch) and the diff below.
- check the PR's own check-runs: `gh pr checks "$PR_NUMBER"`. the `ci` workflow already gates this tree (uv sync --frozen, ruff check, ruff format --check, pytest); report failed or pending checks in your comment, never re-run the gate.
- flag pipeline-owned paths in the diff: `data/history/` and `state/` are written only through pipeline PR branches. a human PR touching them is a finding.
- catalog edits (`data/catalog/*.json`): the coverage invariant is test-pinned over the real tree (every `(source, model_id)` in the store appears in exactly one `models.json` entry's `sources`). judge curation impact: twin merges, `curated` flags, vendor claims, new billing-rules entries shaped like the existing ones, dated fx entries, alias records.
- code edits: review them like any code change — correctness, the tests it ships, what the gate covers.
- anchor every finding at `file:line` of the diff.

your final message summarizes the findings; the PR comment is the durable record.
