"""The CI claude pass reads `.github/claude-pass/prompt.md` on a checkout with no
docs/ tree, so the prompt carries every fact the pass needs. These pin the surfaces
a rename or a schema change would otherwise break silently."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

from ai_pricelog.scrapers import dashscope_page as dashscope_scrape

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / ".github" / "claude-pass" / "prompt.md"
HUMAN_PROMPT = ROOT / ".github" / "claude-pass" / "human-pr-prompt.md"
REVIEW_WF = ROOT / ".github" / "workflows" / "review.yml"


def _section_body(text: str, title: str) -> str:
    """The lines of the `## title` section, blank edges stripped."""
    pattern = re.compile(rf"^## {re.escape(title)}\s*$", re.M)
    match = pattern.search(text)
    assert match is not None, f"section {title!r} not found"
    rest = text[match.end() :]
    next_heading = re.search(r"^#{2,3} ", rest, re.M)
    body = rest[: next_heading.start()] if next_heading else rest
    return body.strip()


def _h2_body(text: str, title: str) -> str:
    """The `## title` section whole, subsections included, to the next `## `."""
    start = re.search(rf"^## {re.escape(title)}\s*$", text, re.M)
    assert start is not None, f"section {title!r} not found"
    rest = text[start.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _h3_body(text: str, title: str) -> str:
    """The `### title` subsection, to the next heading of the same depth or up."""
    start = re.search(rf"^### {re.escape(title)}\s*$", text, re.M)
    assert start is not None, f"subsection {title!r} not found"
    rest = text[start.end() :]
    nxt = re.search(r"^#{2,3} ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def test_row_schema_carries_the_current_vocabulary() -> None:
    # the pass judges rows against this section; a schema change that leaves
    # it stale sends the next review against a dead shape
    schema = _section_body(PROMPT.read_text(), "row schema")
    for term in (
        "overrides",
        "min_tokens",
        "fx_rate",
        "quota_multiplier",
        "rates",
        "fees",
        "limits",
        "provenance",
        "modality",
        "final price snapshot",
        "zero price is a price",
    ):
        assert term in schema, f"row schema section lost {term!r}; update it"


def test_prompt_names_the_automerge_surface() -> None:
    # the merge job names the automerge script and its manual; a rename of
    # either breaks the pass cold
    text = PROMPT.read_text()
    assert "ai-pricelog-automerge" in text
    assert ".github/claude-pass/automerge.md" in text


def test_prompt_carries_the_disposition_markers() -> None:
    # the merge-verified step reads these exact machine lines off the pass's
    # PR comments; a reworded marker silently strands every verified PR, and a
    # marker without the head sha cannot bind the verdict to what was judged
    text = PROMPT.read_text()
    assert "automerge: yes <head sha>" in text
    assert "automerge: no <head sha>" in text
    assert "merge verified PRs" in text
    manual = (ROOT / ".github" / "claude-pass" / "automerge.md").read_text()
    assert "automerge: yes <head sha>" in manual
    assert "automerge: no <head sha>" in manual


def test_needs_human_comment_pings_the_owner() -> None:
    # the ping line is the notification mechanism: the pass posts as the bot,
    # so the @-mention is what reaches the owner
    ping = "@uwuclxdy need help wit this"
    assert ping in PROMPT.read_text()
    manual = (ROOT / ".github" / "claude-pass" / "automerge.md").read_text()
    assert ping in manual


def test_every_watched_provider_has_page_facts_or_an_exempt_entry() -> None:
    # the pass judges rows for every watched provider on a checkout with no
    # docs/ tree: each needs page-facts context in this prompt or a named
    # exempt entry, and a provider section that lands with neither reds here
    providers = tomllib.loads((ROOT / "providers.toml").read_text(encoding="utf-8"))
    quirks = _h2_body(PROMPT.read_text(encoding="utf-8"), "domain quirks")
    announce_at = quirks.find("### announce channels")
    assert announce_at != -1, "the announce inventory moved; repin the page-facts zone"
    page_facts = quirks[:announce_at]
    exempt = _h3_body(quirks, "no page quirk")
    for key in providers:
        covered = re.search(
            rf"^(?:#{{3,4}} .*\b{re.escape(key)}\b|- {re.escape(key)}\b)", page_facts, re.M
        )
        exempted = re.search(rf"^- {re.escape(key)}\b", exempt, re.M)
        assert covered or exempted, (
            f"provider {key!r} has neither page facts nor an exempt entry in the pass prompt"
        )


def test_human_pr_prompt_carries_the_review_contract() -> None:
    # review.yml runs this prompt on human PRs, read-only, on a checkout with
    # no docs/ tree; the one-comment contract, the read-only rule and the
    # machine marker are the row's contract, and the disclosure string is the
    # pipeline skip marker — a reword on either side breaks the skip
    text = HUMAN_PROMPT.read_text()
    assert "exactly one comment" in text
    assert "edit that comment in place" in text
    assert "never Edit" in text
    assert "pr-review:" in text
    assert "pr-review: <head sha reviewed>" in text
    assert "opened automatically by the [GitHub Action]" in text


def test_review_workflow_names_the_prompt_and_stays_read_only() -> None:
    # review.yml is the human-prompt's only consumer, and its allowedTools
    # list is the read-only contract's enforcement: an Edit that creeps in
    # turns the row's read-only review into a branch-editing one
    text = REVIEW_WF.read_text()
    assert "human-pr-prompt.md" in text
    assert "opened automatically by the [GitHub Action]" in text
    tools = re.search(r"--allowedTools(.+)", text)
    assert tools is not None, "review.yml lost its --allowedTools line"
    assert '"Edit"' not in tools.group(1)
    assert '"Read" "Bash(gh:*)" "Bash(git:*)" "WebFetch" "WebSearch"' in tools.group(1)
    # the always-run verify step is the hung-pass net: a pass killed by its
    # timeout posts no warning of its own, so the step checks the one durable
    # signal — the comment's pr-review machine line for this head — and warns
    # (never fails) when it never landed
    assert "name: verify the review comment landed" in text
    assert "if: ${{ always() && !cancelled() }}" in text
    assert "pr-review: $head" in text


def test_prompt_carries_the_openrouter_fetch_and_identity_rules():
    # the pass's false absence verdicts (2026-09-22, PRs 333/337) came from
    # WebFetch extraction over the ~750KB payload and a substring id match
    # (PR 331's kwaipilot read); these rules are the fix's prompt half
    schema = _section_body(PROMPT.read_text(), "row schema")
    assert "curl -fsSL" in schema
    assert "exact id equality" in schema
    assert "never absence evidence" in schema
    assert "never substring-match an id" in schema


def test_prompt_settles_the_absence_file_lifecycle():
    # a branch deleting state/absence/<source>.json is the documented
    # cleanup of landed removals; PR 331's pass misread it as lost delistings
    job = _section_body(PROMPT.read_text(), "your job")
    assert "documented cleanup" in job


def test_output_contract_pins_one_comment_per_pr():
    # PR 331 got a yes marker and a contradicting no as a second comment;
    # the contract is one comment, edited in place when a verdict overturns
    contract = _section_body(PROMPT.read_text(), "output contract")
    assert "EDIT that comment" in contract
    assert "one comment, one disposition marker per PR" in contract


def test_prompt_works_the_review_queue_not_the_run():
    # the workflow appends the queue under this heading; a prompt scoped to
    # "the PRs this run opened" left every PR an earlier, dead pass never
    # judged open forever (2026-09-27..10-14: 80 stranded PRs)
    text = PROMPT.read_text()
    assert "## PRs awaiting review" in text
    for scoped in ("this run opened", "the run opened", "the run did not open"):
        assert scoped not in text, f"the prompt still scopes the pass to {scoped!r}"
    automerge_rules = (ROOT / ".github" / "claude-pass" / "automerge.md").read_text()
    assert "the run did not open" not in automerge_rules


def test_prompt_spells_listed_branches_as_remote_refs_in_reads_only():
    # a PR an earlier run opened exists here only as origin/<branch>, so every
    # read names that spelling; a fix commit needs the local branch, and
    # `git switch origin/<branch>` dies "a branch is expected" (measured in a
    # fresh clone, 2026-10-14). residual: the pin forbids one phrasing, so a
    # reworded scope sentence that widens the spelling back to writes passes
    # unseen
    text = PROMPT.read_text()
    job = _section_body(text, "your job")
    assert "1. for each listed PR: diff `origin/mommy...origin/<branch>`." in job
    assert "`git show origin/<branch>:<path>`" in text
    assert "in every git command" not in text
    assert "`git switch <branch>`" in job
    assert "`git push origin <branch>`" in job


def test_prompt_flags_a_cache_read_above_input_row_as_needs_human():
    # a price row whose cache_read exceeds its input is implausible; the pass
    # must flag it needs-human — a reword dropping this clause would silently
    # auto-verify such a row again
    job = _section_body(PROMPT.read_text(), "your job")
    assert "`cache_read` exceeds its `input`" in job
    assert "never auto-verify or merge" in job


def test_automerge_lands_an_openrouter_row_that_equals_a_live_endpoint():
    # openrouter's model-level price is the price of the one endpoint it routes
    # to, so a key that hops providers seldom returns to its prior stored row
    # and condition 1 strands rows that recorded a real provider state; an
    # exact match against a live endpoint of the same id is the guard
    manual = (ROOT / ".github" / "claude-pass" / "automerge.md").read_text()
    assert "| openrouter endpoint match |" in manual
    flip_flop = _section_body(manual, "the flip-flop disposition")
    assert "comment needs human, unless the endpoint-match disposition below lands" in flip_flop
    rule = _section_body(manual, "the endpoint-match disposition")
    assert (
        "`curl -fsSL -o /tmp/endpoints.json"
        " 'https://openrouter.ai/api/v1/models/<model_id>/endpoints'`" in rule
    )
    assert "`<model_id>` the row's id verbatim" in rule
    assert "a `removed: true` row never takes this path" in rule
    assert "name the matching endpoint's `provider_name` and `tag` in the comment" in rule
    # the marker is one per PR: a PR mixing matching rows with one that
    # matches nothing must not take the yes
    assert "one unverified row makes its whole PR needs human" in rule
    assert "only when each of its own rows is verified, a flip-flop or an endpoint match" in rule
    assert "a row that meets condition 1 never takes this path" in rule
    assert "no correction row" in rule
    assert "PR 869" in rule
    summary = _section_body(PROMPT.read_text(), "merge job")
    assert "merge-eligible (verified, flip-flop, openrouter endpoint match," in summary
    job = _section_body(PROMPT.read_text(), "your job")
    assert (
        "for an openrouter price row whose condition 1 fails, through `automerge.md`'s"
        " endpoint match" in job
    )


# stored openrouter rows, verbatim from data/history/openrouter.ndjson
_WAFER_ROW = {
    "schema": 4,
    "source": "openrouter",
    "model_id": "deepseek/deepseek-v4.1-flash",
    "observed_at": "2026-11-07",
    "rates": {"input": 0.051, "output": 0.567, "cache_read": 0.018},
    "limits": {"context": 1048576},
    "provenance": {"name": "DeepSeek V4.1 Flash"},
}
_MINIMAX_ROW = {
    "schema": 4,
    "source": "openrouter",
    "model_id": "minimax/minimax-m3.1-flash",
    "observed_at": "2026-11-19",
    "rates": {"input": 0.15, "output": 0.6, "cache_read": 0.015},
    "overrides": [
        {
            "when": {"window": [1500, 2400], "timezone": "UTC"},
            "rates": {"input": 0.075, "output": 0.3, "cache_read": 0.0075},
        },
        {
            "when": {"window": [0, 100], "timezone": "UTC"},
            "rates": {"input": 0.075, "output": 0.3, "cache_read": 0.0075},
        },
        {
            "when": {"window": [100, 1500], "timezone": "UTC"},
            "rates": {"input": 0.15, "output": 0.6, "cache_read": 0.015},
        },
    ],
    "limits": {"context": 1048576},
    "provenance": {"name": "MiniMax M3.1 Flash"},
}
# endpoint entries as /models/<id>/endpoints served them (measured 2026-11-19)
_OPEN_INFERENCE = {
    "provider_name": "OpenInference",
    "tag": "open-inference/fp4",
    "pricing": {
        "prompt": "0.00000005",
        "completion": "0.0000009",
        "input_cache_read": "0.000000002",
        "discount": 0,
    },
}
_WAFER = {
    "provider_name": "Wafer",
    "tag": "wafer/us",
    "pricing": {
        "prompt": "0.000000051",
        "completion": "0.000000567",
        "input_cache_read": "0.000000018",
        "discount": 0,
    },
}
_MINIMAX = {
    "provider_name": "Minimax",
    "tag": "minimax",
    "pricing": {
        "prompt": "0.00000015",
        "completion": "0.0000006",
        "input_cache_read": "0.000000015",
        "discount": 0,
        "overrides": [
            {
                "utc_start": 1500,
                "utc_end": 100,
                "prompt": "0.000000075",
                "completion": "0.0000003",
                "input_cache_read": "0.0000000075",
            },
            {
                "utc_start": 100,
                "utc_end": 1500,
                "prompt": "0.00000015",
                "completion": "0.0000006",
                "input_cache_read": "0.000000015",
            },
        ],
    },
}


def _endpoint_match(
    tmp_path: Path,
    shard: list[dict[str, object]],
    key: tuple[str, str],
    endpoints_id: str,
    endpoints: list[dict[str, object]],
) -> subprocess.CompletedProcess[str]:
    """run automerge.md's endpoint-match command through bash, as the pass would.

    only the branch read, the interpreter, the two placeholders and the endpoints
    path are swapped, so the shell's quoting of the script body runs as written.
    """
    rule = _section_body(
        (ROOT / ".github" / "claude-pass" / "automerge.md").read_text(),
        "the endpoint-match disposition",
    )
    block = re.search(r"^```bash\n(.*?)\n```$", rule, re.M | re.S)
    assert block is not None, "the endpoint-match command moved; repin it"
    command = block.group(1)
    for placeholder, value in (
        ("git show origin/<branch>:data/history/openrouter.ndjson", "cat shard.ndjson"),
        ("uv run python", shlex.quote(sys.executable)),
        ("'<model_id>'", shlex.quote(key[0])),
        ("'<observed_at>'", shlex.quote(key[1])),
        ("/tmp/endpoints.json", "endpoints.json"),
    ):
        assert command.count(placeholder) == 1, f"the command lost {placeholder!r}; repin it"
        command = command.replace(placeholder, value)
    (tmp_path / "shard.ndjson").write_text("".join(json.dumps(row) + "\n" for row in shard))
    body = {"data": {"id": endpoints_id, "endpoints": endpoints}}
    (tmp_path / "endpoints.json").write_text(json.dumps(body))
    return subprocess.run(
        ["bash", "-c", command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


# the stored row before PR 869's, verbatim from data/history/openrouter.ndjson
_PRIOR_ROW = {
    **_WAFER_ROW,
    "observed_at": "2026-11-06",
    "rates": {"input": 0.0486, "output": 0.54, "cache_read": 0.018},
}
_WAFER_KEY = ("deepseek/deepseek-v4.1-flash", "2026-11-07")


def test_endpoint_match_script_names_every_endpoint_the_row_equals(tmp_path):
    # PR 869's row equals the Wafer endpoint and no other one; the script picks
    # it out of the shard by its observed_at
    shard = [_PRIOR_ROW, _WAFER_ROW]
    run = _endpoint_match(tmp_path, shard, _WAFER_KEY, _WAFER_KEY[0], [_OPEN_INFERENCE, _WAFER])
    assert (run.returncode, run.stdout) == (0, "Wafer wafer/us\n")
    # every equal endpoint is named, not only the first
    second = {**_WAFER, "tag": "wafer/eu"}
    endpoints = [_OPEN_INFERENCE, _WAFER, second]
    run = _endpoint_match(tmp_path, shard, _WAFER_KEY, _WAFER_KEY[0], endpoints)
    assert (run.returncode, run.stdout) == (0, "Wafer wafer/us\nWafer wafer/eu\n")
    # an endpoint the script cannot name or build matches nothing: the script
    # names it on stderr and the scan goes on to the endpoints after it
    rejected = {**_OPEN_INFERENCE, "pricing": {**_OPEN_INFERENCE["pricing"], "prompt": "n/a"}}
    unpriced = {**_OPEN_INFERENCE, "pricing": None}
    listed = {**_OPEN_INFERENCE, "pricing": []}
    huge = {**_OPEN_INFERENCE, "pricing": {**_OPEN_INFERENCE["pricing"], "prompt": 10**400}}
    no_pricing = {key: value for key, value in _OPEN_INFERENCE.items() if key != "pricing"}
    tagless = {key: value for key, value in _WAFER.items() if key != "tag"}
    nameless = {key: value for key, value in _WAFER.items() if key != "provider_name"}
    for endpoints, skipped in (
        ([rejected, _WAFER], 0),
        ([_WAFER, rejected], 1),
        ([unpriced, _WAFER], 0),
        ([listed, _WAFER], 0),
        ([huge, _WAFER], 0),
        ([no_pricing, _WAFER], 0),
        ([None, _WAFER], 0),
        (["x", _WAFER], 0),
        ([_WAFER, None], 1),
        ([tagless, _WAFER], 0),
        ([_WAFER, nameless], 1),
    ):
        run = _endpoint_match(tmp_path, shard, _WAFER_KEY, _WAFER_KEY[0], endpoints)
        assert (run.returncode, run.stdout) == (0, "Wafer wafer/us\n"), endpoints
        assert f"skipped endpoint {skipped}: " in run.stderr, endpoints
    # an endpoint whose price equals the row's but that names no nonblank
    # printable provider or tag is skipped, never named as a match
    unprintable = [
        {**_WAFER, field: f"{_WAFER[field]}{char}Injected x"}
        for field in ("provider_name", "tag")
        for char in ("\n", "\r", "\U00002028", "\x1b")
    ]
    for unnamed in (
        tagless,
        nameless,
        {**_WAFER, "tag": None},
        {**_WAFER, "tag": 7},
        {**_WAFER, "provider_name": 7},
        {**_WAFER, "tag": ""},
        {**_WAFER, "provider_name": " "},
        *unprintable,
    ):
        run = _endpoint_match(tmp_path, shard, _WAFER_KEY, _WAFER_KEY[0], [unnamed])
        assert (run.returncode, run.stdout) == (0, ""), unnamed
        assert "skipped endpoint 0: " in run.stderr, unnamed
    # a same-day update row follows the landed row of its day in the shard,
    # and the script judges that last one
    landed = {**_WAFER_ROW, "rates": {"input": 0.0511, "output": 0.567, "cache_read": 0.018}}
    run = _endpoint_match(tmp_path, [landed, _WAFER_ROW], _WAFER_KEY, _WAFER_KEY[0], [_WAFER])
    assert (run.returncode, run.stdout) == (0, "Wafer wafer/us\n")
    run = _endpoint_match(tmp_path, [_WAFER_ROW, landed], _WAFER_KEY, _WAFER_KEY[0], [_WAFER])
    assert (run.returncode, run.stdout) == (0, "")
    # a scheduled row matches only when the endpoint builds the same entries
    # (its wrap window split in two)
    minimax_key = ("minimax/minimax-m3.1-flash", "2026-11-19")
    run = _endpoint_match(tmp_path, [_MINIMAX_ROW], minimax_key, minimax_key[0], [_MINIMAX])
    assert (run.returncode, run.stdout) == (0, "Minimax minimax\n")


def test_endpoint_match_script_matches_nothing_outside_exact_equality(tmp_path):
    endpoints = [_OPEN_INFERENCE, _WAFER]
    prior_key = (_WAFER_KEY[0], "2026-11-06")
    run = _endpoint_match(tmp_path, [_PRIOR_ROW, _WAFER_ROW], prior_key, _WAFER_KEY[0], endpoints)
    assert (run.returncode, run.stdout) == (0, "")
    moved = {**_WAFER_ROW, "rates": {"input": 0.0511, "output": 0.567, "cache_read": 0.018}}
    run = _endpoint_match(tmp_path, [moved], _WAFER_KEY, _WAFER_KEY[0], endpoints)
    assert (run.returncode, run.stdout) == (0, "")
    with_fee = {**_WAFER_ROW, "fees": {"web_search": 0.01}}
    run = _endpoint_match(tmp_path, [with_fee], _WAFER_KEY, _WAFER_KEY[0], endpoints)
    assert (run.returncode, run.stdout) == (0, "")
    # a price the parser keeps under `unmapped` (a per-request fee) is an axis too
    per_request = {**_WAFER, "pricing": {**_WAFER["pricing"], "request": "0.001"}}
    for fee, stdout in (("0.002", ""), ("0.001", "Wafer wafer/us\n")):
        stored = {**_WAFER_ROW, "unmapped": {"request": fee}}
        run = _endpoint_match(tmp_path, [stored], _WAFER_KEY, _WAFER_KEY[0], [per_request])
        assert (run.returncode, run.stdout) == (0, stdout), fee
    unscheduled = {key: value for key, value in _MINIMAX_ROW.items() if key != "overrides"}
    minimax_key = ("minimax/minimax-m3.1-flash", "2026-11-19")
    run = _endpoint_match(tmp_path, [unscheduled], minimax_key, minimax_key[0], [_MINIMAX])
    assert (run.returncode, run.stdout) == (0, "")


def test_endpoint_match_script_refuses_a_missing_row_a_removal_or_a_sibling_id(tmp_path):
    missing_key = (_WAFER_KEY[0], "1999-01-01")
    run = _endpoint_match(tmp_path, [_WAFER_ROW], missing_key, _WAFER_KEY[0], [_WAFER])
    assert run.returncode != 0 and run.stdout == ""
    removal = {**_WAFER_ROW, "removed": True}
    run = _endpoint_match(tmp_path, [removal], _WAFER_KEY, _WAFER_KEY[0], [_WAFER])
    assert run.returncode != 0 and run.stdout == ""
    sibling = "deepseek/deepseek-v4.1-flash:free"
    run = _endpoint_match(tmp_path, [_WAFER_ROW], _WAFER_KEY, sibling, [_WAFER])
    assert run.returncode != 0 and run.stdout == ""


def test_prompt_carries_the_2026_11_18_page_shapes():
    # the pass re-verifies rows against these pages with no docs/ tree; each
    # fact is the shape a scraper fix of 2026-11-18 reads
    quirks = _h2_body(PROMPT.read_text(encoding="utf-8"), "domain quirks")
    for fact in (
        "`Search API` / `Fetch API`",
        "`Input unit price` / `Output unit price`",
        "0.4 x 0.8 = 0.32",
        "never its alias's promo",
        "`window` `[0, 1400]`",
        '`<template data-mint="manifest">`',
        "in its Mintlify manifest when the flight payload carries no table",
        "14 per-family tables",
        "a span labelled `List price`",
        "the row records the charged run, the rate in force",
        "are not billed, while Search and Fetch API calls made directly from the client still are",
        "split into two entries where those hours wrap UTC midnight",
    ):
        assert fact in quirks, f"domain quirks lost {fact!r}"
    assert "13 per-family tables" not in quirks
    rule_id = "deepseek-server-side-search-unbilled-2026-11-18"
    assert f"`{rule_id}`" in quirks
    rules = json.loads((ROOT / "data" / "catalog" / "billing-rules.json").read_text())["rules"]
    assert rule_id in {rule["id"] for rule in rules}


def test_prompt_dashscope_promo_spellings_price_as_the_scraper_reads_them():
    # the pass judges a discounted dashscope row against these spellings, so
    # each one the prompt says records 0.32 must be one the scraper reads
    shapes = _h3_body(PROMPT.read_text(encoding="utf-8"), "dashscope page shapes, 2026-11-18")
    for cell in (
        "Original$0.4 (20% off for a limited time)",
        "List price $0.4 Limited-time 20% off",
    ):
        assert f"`{cell}`" in shapes, f"the promo bullet lost {cell!r}"
        assert dashscope_scrape._rate_in_force(cell, "qwen-x", "https://example.com") == 0.32


def _unwatched_bullet_keys(quirks: str, providers: set[str]) -> list[str]:
    """provider keys a `- key:` or `- a, b:` bullet head names outside `providers`."""
    heads = re.finditer(r"^- ([a-z0-9]+(?:, [a-z0-9]+)*)(?: \([^)]*\))?:", quirks, re.M)
    return [key for head in heads for key in head.group(1).split(", ") if key not in providers]


def test_every_provider_bullet_in_the_quirks_names_a_watched_provider():
    # a provider that leaves the watch set takes its page facts and its
    # announce-exempt entry with it, or the pass judges rows no run produces.
    # residual: a provider named outside a `- key:` / `- a, b:` bullet head
    # (prose, a heading) is not seen
    sample = "- gone (wired 2026-01-01): x\n- kept, gone2: y\n  - gone3: z\n- the gone4 rows: w\n"
    assert _unwatched_bullet_keys(sample, {"kept"}) == ["gone", "gone2"]
    providers = set(tomllib.loads((ROOT / "providers.toml").read_text(encoding="utf-8")))
    quirks = _h2_body(PROMPT.read_text(encoding="utf-8"), "domain quirks")
    assert _unwatched_bullet_keys(quirks, providers) == []


def _gitignored_paths(text: str, ignored_dirs: list[str]) -> list[str]:
    """repo-relative paths inside an ignored directory, url path segments excluded."""
    return [
        hit
        for directory in ignored_dirs
        for hit in re.findall(rf"(?<![\w.:/-]){re.escape(directory)}[\w.<-]+", text)
    ]


def test_pass_instructions_name_no_gitignored_path():
    # the pass runs on a checkout without the gitignored trees (docs/ among
    # them), so a path inside one names a file the pass cannot read.
    # residual: a gitignored file named without its directory, and a path
    # ignored outside the repo .gitignore (a global excludes file; untracked,
    # so absent on CI), are not seen
    sample = "read `docs/a.md` and docs/b.md; no `docs/` tree; see example.com/docs/c"
    assert _gitignored_paths(sample, ["docs/"]) == ["docs/a.md", "docs/b.md"]
    ignored_dirs = [
        line.strip()
        for line in (ROOT / ".gitignore").read_text().splitlines()
        if line.strip().endswith("/") and not re.search(r"[*?\[!#]", line)
    ]
    assert "docs/" in ignored_dirs
    for path in sorted((ROOT / ".github" / "claude-pass").glob("*.md")):
        hits = _gitignored_paths(path.read_text(encoding="utf-8"), ignored_dirs)
        assert not hits, f"{path.name} names gitignored paths {hits}"
