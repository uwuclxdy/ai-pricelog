"""The static pricing page: its coverage floor, its pricing parity and its state.

The page's own arithmetic runs twice here on purpose. Once in python, from
numbers spelled out in this file, so the expected totals never come out of the
module under test; once under `node`, over the very function the browser runs,
so a drift between the two implementations fails a gate rather than a reader.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from ai_pricelog import publish, site, store
from test_publish import _fixture_root, _flat_rows

ROOT = Path(__file__).resolve().parents[1]

APP_JS = ROOT / "src" / "ai_pricelog" / "site_assets" / "app.js"

# the page's own half of the handshake, pinned as a whole statement because the
# property alone survives a changed value. the module's half, the call included,
# is driven as behaviour under node instead
PAGE_READ = 'document.documentElement.dataset.site === "ready"'
PAGE_CALL = "reportReady(document, wrap)"

# the harness runs from a temp directory and imports a `.mjs` copy, so node
# parses the module as ESM whatever package.json sits above the repo
_NODE_HARNESS = """
import { readFileSync } from 'node:fs';
const app = await import(process.argv[2]);
const probe = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const out = { cases: {} };
for (const [name, spec] of Object.entries(probe.cases)) {
  out.cases[name] = app.priceSession(spec.entry, spec.day, spec.tokens, new Date(spec.now));
}
out.state = app.decodeState(probe.fragment);
out.encoded = app.encodeState(out.state);
out.rate = probe.cases.peak ? app.priceAtRate(2.5, probe.cases.peak.tokens) : null;
out.rates = (probe.rates ?? []).map(v => app.formatRate(v));
if (probe.reveal) {
  const run = marked => {
    const listeners = [];
    const fallback = { hidden: true };
    const stubWindow = { addEventListener: (name, fn) => listeners.push(fn) };
    const stubDocument = {
      documentElement: { dataset: marked ? { site: 'ready' } : {} },
      getElementById: () => fallback,
    };
    new Function('window', 'addEventListener', 'document', probe.reveal)(
      stubWindow, stubWindow.addEventListener, stubDocument);
    for (const fn of listeners) fn();
    return fallback.hidden;
  };
  out.reveal = { unmarked: run(false), marked: run(true) };
}
if (probe.ready) {
  const fresh = () => ({ documentElement: { dataset: {} } });
  const unmarked = fresh();
  const marked = fresh();
  const reported = [
    app.reportReady(unmarked, { dataset: {} }),
    app.reportReady(marked, { dataset: { uiTable: '1' } }),
  ];
  out.ready = {
    unmarked: unmarked.documentElement.dataset.site ?? null,
    marked: marked.documentElement.dataset.site ?? null,
    reported,
  };
}
if (probe.restoreSort) {
  const clicks = [];
  // the shipped controller's own cycle plus the page's own listener writing
  // the emitted dir back into state: the interplay a desc fragment rides
  const controller = { key: null, dir: 'none' };
  const button = {
    click() {
      clicks.push(1);
      const key = probe.restoreSort.state.sort;
      const next = { none: 'asc', asc: 'desc', desc: 'none' };
      controller.dir = controller.key === key ? next[controller.dir] : 'asc';
      controller.key = key;
      probe.restoreSort.state.dir = controller.dir;
    },
  };
  const wrap = { querySelector: () => button };
  app.restoreSort(probe.restoreSort.state, wrap);
  out.restoreSort = { clicks: clicks.length, dir: probe.restoreSort.state.dir };
}
console.log(JSON.stringify(out));
"""

# one entry, every rung of the pricing rules: a cache axis, a weekday window
# override, a later interval with no cache axis of its own, and a removal
ENTRY = {
    "source": "fixture",
    "model_id": "m1",
    "vendor": "fixture",
    "name": "Fixture One",
    "observed_at": "2026-08-01",
    "rates": {"input": 1.0, "output": 4.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": "2026-10-01",
            "observed_at": "2026-08-01",
            "rates": {"input": 2.0, "output": 8.0, "cache_read": 0.5},
            # two entries whose windows overlap on a weekday morning, so the
            # later one has to win: the reverse-first-match rule reads off this
            "overrides": [
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [100, 400],
                    },
                    "rates": {"input": 4.0, "output": 16.0},
                },
                {
                    "when": {
                        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                        "window": [100, 200],
                    },
                    "rates": {"input": 9.0, "output": 36.0},
                },
            ],
        },
        {
            "valid_from": "2026-10-01",
            "valid_to": None,
            "observed_at": "2026-10-01",
            "rates": {"input": 1.0, "output": 4.0},
        },
    ],
}

REMOVED = {
    "source": "fixture",
    "model_id": "m2",
    "vendor": "fixture",
    "name": "Fixture Two",
    "observed_at": "2026-08-05",
    "removed_at": "2026-08-05",
    "rates": {"input": 1.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": "2026-08-05",
            "observed_at": "2026-08-01",
            "rates": {"input": 1.0},
        },
        {
            "valid_from": "2026-08-05",
            "valid_to": None,
            "observed_at": "2026-08-05",
            "removed": True,
        },
    ],
}

# a volume threshold, the openrouter `min_prompt_tokens` the export maps here
VOLUME = {
    "source": "fixture",
    "model_id": "m3",
    "vendor": "fixture",
    "name": "Fixture Three",
    "observed_at": "2026-08-01",
    "rates": {"input": 1.0, "output": 2.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": None,
            "observed_at": "2026-08-01",
            "rates": {"input": 1.0, "output": 2.0},
            "overrides": [{"when": {"min_tokens": 500000}, "rates": {"input": 0.5, "output": 1.0}}],
        }
    ],
}

# a rate entry shadowed by a narrower multiplier-only entry standing LATER in
# the same list: the export carries no such pair, so this fixture is what pins
# the reading its own two rules compose to
QUOTA = {
    "source": "fixture",
    "model_id": "m4",
    "vendor": "fixture",
    "name": "Fixture Four",
    "observed_at": "2026-08-01",
    "rates": {"input": 2.0, "output": 8.0, "cache_read": 0.5},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": None,
            "observed_at": "2026-08-01",
            "rates": {"input": 2.0, "output": 8.0, "cache_read": 0.5},
            "overrides": [
                {
                    "when": {"days": ["monday"], "window": [100, 400]},
                    "rates": {"input": 9.0, "output": 36.0},
                },
                {"when": {"days": ["monday"], "window": [100, 200]}, "quota_multiplier": 0.4},
            ],
        }
    ],
}

# 2026-09-07 02:00 UTC is a monday, 120 minutes in, inside the 100..400 window
SESSION = {"input": 1000000, "cached": 200000, "output": 50000}

# a provenance name a scraper could hand back: interpolated raw it would close
# the page's script island, and escaped it is just a name
NASTY = "</script><script>alert(1)</script>"


def _rows() -> list[dict[str, object]]:
    """The shared fixture rows plus one carrying markup in its name."""
    return [
        *_flat_rows(),
        {
            "schema": 4,
            "source": "alpha",
            "model_id": "evil",
            "observed_at": "2026-08-04",
            "rates": {"input": 1.0},
            "provenance": {"name": NASTY},
        },
    ]


def _built(tmp_path: Path) -> Path:
    rows = _rows()
    root = _fixture_root(tmp_path, rows=rows)
    out = tmp_path / "out"
    publish.build_dist(rows, root, out, 4)
    return out


def _node(tmp_path: Path, probe: dict[str, object]) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        # never a skip: these legs are the only place the page's own pricing
        # rules and its fragment contract are exercised at all. a usage error
        # and not a failure, because a missing interpreter is the environment's
        # news rather than a defect here — `pytest.exit` would carry that
        # further, and it crashes xdist, which this suite runs under
        raise pytest.UsageError(
            "node is required for the page's own scripts; install node and re-run"
        )
    shutil.copyfile(APP_JS, tmp_path / "app.mjs")
    (tmp_path / "probe.json").write_text(json.dumps(probe), encoding="utf-8")
    harness = tmp_path / "harness.mjs"
    harness.write_text(_NODE_HARNESS, encoding="utf-8")
    done = subprocess.run(
        [node, str(harness), str(tmp_path / "app.mjs"), str(tmp_path / "probe.json")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _soup(html: str) -> BeautifulSoup:
    # html.parser reads the noscript subtree as markup whatever the scripting
    # flag would say, which is the surface a crawler without javascript gets
    return BeautifulSoup(html, "html.parser")


def test_the_flat_export_of_the_fixture_builds_the_expected_tree(tmp_path):
    out = _built(tmp_path)
    assert (out / "index.html").is_file()


def test_every_export_key_renders_in_the_static_table(tmp_path):
    out = _built(tmp_path)
    export = json.loads((out / "flat-v2.json").read_text(encoding="utf-8"))
    rows = _soup((out / "index.html").read_text(encoding="utf-8")).select("#models-static tbody tr")

    # equality of the whole key set, never a subset walk: a table missing one
    # entry still satisfies every entry it does carry
    assert {row["data-key"] for row in rows} == {
        f"{entry['source']}/{entry['model_id']}" for entry in export["entries"]
    }
    for row in rows:
        assert row.select_one("div.td-sub").get_text() == row["data-key"].split("/", 1)[1]


def test_a_removed_entry_is_labelled_in_the_static_table(tmp_path):
    out = _built(tmp_path)
    rows = _soup((out / "index.html").read_text(encoding="utf-8")).select("#models-static tbody tr")
    removed = [row for row in rows if "removed" in row.get_text()]
    assert removed != []
    for row in removed:
        assert row.select_one("span.tag").get_text().startswith("removed ")


def test_every_key_of_the_real_export_renders(tmp_path):
    """The fixture cannot carry the shape of 1123 real entries; this one does."""
    rows = store.load_shards(ROOT / store.SHARD_DIR)
    out = tmp_path / "out"
    payload = publish.build_flat(rows, ROOT, out, 4)
    site.render_site(payload, out)

    export = json.loads((out / "flat-v2.json").read_text(encoding="utf-8"))
    rendered = _soup((out / "index.html").read_text(encoding="utf-8")).select(
        "#models-static tbody tr"
    )
    assert len(rendered) == len(export["entries"])
    assert {row["data-key"] for row in rendered} == {
        f"{entry['source']}/{entry['model_id']}" for entry in export["entries"]
    }


def test_the_island_holds_the_export_payload_in_compact_form(tmp_path):
    out = _built(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    island = re.search(r'id="flat-data">(.*?)</script>', html, re.S).group(1)
    file_payload = json.loads((out / "flat-v2.json").read_text(encoding="utf-8"))

    # the exact shipped relation: the file's own payload, re-serialized by the
    # export's serializer with compact separators, its trailing newline
    # dropped, and `<` escaped so no name can close the script element
    assert island == json.dumps(file_payload, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    assert json.loads(island) == file_payload


def test_a_name_carrying_markup_cannot_close_the_data_island(tmp_path):
    out = _built(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    island = re.search(r'id="flat-data">(.*?)</script>', html, re.S).group(1)

    # the raw name is what the attack would put in the page, so this is the
    # clause the fixture reds; the island extractor truncates at an injected
    # `</script>`, so it cannot be the one that catches that shape
    assert NASTY not in html
    assert "<" not in island
    assert json.loads(island) == json.loads((out / "flat-v2.json").read_text(encoding="utf-8"))

    # and the escaping loses nothing: a reader still gets the export's name
    row = next(
        row
        for row in _soup(html).select("#models-static tbody tr")
        if row["data-key"] == "alpha/evil"
    )
    assert row.select_one("span.table-name").get_text() == NASTY


def test_every_reference_the_page_makes_resolves(tmp_path):
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    refs = [link["href"] for link in soup.select("link[href]")]
    refs += [script["src"] for script in soup.select("script[src]")]
    refs += [anchor["href"] for anchor in soup.select("a[href]")]
    for ref in refs:
        if ":" in ref or ref.startswith("#"):
            continue
        target = out / ref
        assert target.is_file(), f"dangling reference: {ref}"
        assert target.stat().st_size > 0, f"empty reference: {ref}"

    # and the module graph is a reference walk of its own: a script's own
    # `from './x.js'` never appears in the page's markup
    for script in sorted((out / "site").rglob("*.js")):
        for ref in re.findall(r"""from\s+['"](\.[^'"]+)['"]""", script.read_text(encoding="utf-8")):
            assert (script.parent / ref).is_file(), (
                f"dangling module import: {ref} in {script.name}"
            )

    # the fonts are the one reference a stylesheet makes, so they need their
    # own walk: a sheet that lands beside its own fonts/ is the whole contract
    for url in re.findall(r'url\("([^"]+)"\)', (out / "site" / "tokens.css").read_text("utf-8")):
        assert (out / "site" / url).is_file(), f"dangling font: {url}"


def test_every_element_the_page_script_looks_up_exists(tmp_path):
    out = _built(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    wanted = set(re.findall(r'getElementById\("([^"]+)"\)', APP_JS.read_text(encoding="utf-8")))
    assert wanted != set()
    for element_id in sorted(wanted):
        assert f'id="{element_id}"' in html, f"the page never renders #{element_id}"


def _node_cases() -> dict[str, dict[str, object]]:
    """The fixture sessions, each with the total python arithmetic gives it.

    Every total is written out here in terms of the fixture's own rates and the
    session's own three counts (a million tokens is 1.0, two hundred thousand is
    0.2, fifty thousand is 0.05), so no expectation is read back off the module
    under test.
    """
    return {
        "peak": {
            "entry": ENTRY,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T02:00:00Z",
            # 02:00 sits inside both overlapping windows, so the LATER entry
            # prices it; its absent cache axis keeps the base 0.5
            "expected": 1.0 * 9.0 + 0.2 * 0.5 + 0.05 * 36.0,
        },
        "between_the_two_windows": {
            "entry": ENTRY,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T04:00:00Z",
            # 04:00 is past the later window and inside the earlier one, so the
            # later entry does not match and the earlier one prices it
            "expected": 1.0 * 4.0 + 0.2 * 0.5 + 0.05 * 16.0,
        },
        "sunday_outside_the_day_set": {
            "entry": ENTRY,
            "day": "2026-09-06",
            "tokens": SESSION,
            "now": "2026-09-06T02:00:00Z",
            "expected": 1.0 * 2.0 + 0.2 * 0.5 + 0.05 * 8.0,
        },
        "monday_outside_the_window": {
            "entry": ENTRY,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T07:00:00Z",
            "expected": 1.0 * 2.0 + 0.2 * 0.5 + 0.05 * 8.0,
        },
        "later_interval_inherits_the_input_rate_for_cached": {
            "entry": ENTRY,
            "day": "2026-10-05",
            "tokens": SESSION,
            "now": "2026-10-05T02:00:00Z",
            "expected": 1.0 * 1.0 + 0.2 * 1.0 + 0.05 * 4.0,
        },
        "the_first_interval_ends_where_the_second_begins": {
            "entry": ENTRY,
            "day": "2026-10-01",
            "tokens": {"input": 1000000, "cached": 0, "output": 0},
            "now": "2026-10-01T02:00:00Z",
            "expected": 1.0 * 1.0,
        },
        "day_before_every_interval": {
            "entry": ENTRY,
            "day": "2026-07-31",
            "tokens": SESSION,
            "now": "2026-07-31T02:00:00Z",
            "expected": None,
        },
        "removed_span": {
            "entry": REMOVED,
            "day": "2026-08-05",
            "tokens": SESSION,
            "now": "2026-08-05T02:00:00Z",
            "expected": None,
        },
        "removed_entry_still_prices_an_earlier_day": {
            "entry": REMOVED,
            "day": "2026-08-02",
            "tokens": {"input": 1000000, "cached": 0, "output": 0},
            "now": "2026-08-02T02:00:00Z",
            "expected": 1.0 * 1.0,
        },
        "a_volume_threshold_met": {
            "entry": VOLUME,
            "day": "2026-09-07",
            "tokens": {"input": 1000000, "cached": 0, "output": 0},
            "now": "2026-09-07T02:00:00Z",
            "expected": 1.0 * 0.5,
        },
        "a_volume_threshold_unmet": {
            "entry": VOLUME,
            "day": "2026-09-07",
            "tokens": {"input": 100000, "cached": 0, "output": 0},
            "now": "2026-09-07T02:00:00Z",
            "expected": 0.1 * 1.0,
        },
        "the_volume_threshold_counts_the_whole_prompt": {
            "entry": VOLUME,
            "day": "2026-09-07",
            # 300000 + 300000 reaches the 500000 floor; the input count alone
            # does not, so a threshold read off `input` prices the base rate
            "tokens": {"input": 300000, "cached": 300000, "output": 0},
            "now": "2026-09-07T02:00:00Z",
            "expected": (0.3 + 0.3) * 0.5,
        },
        "a_multiplier_only_entry_shadows_the_rate_entry": {
            "entry": QUOTA,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T02:00:00Z",
            # 02:00 is inside both windows, so the LATER entry matches and
            # stops the search; being rate-less it leaves the base rates
            "expected": 1.0 * 2.0 + 0.2 * 0.5 + 0.05 * 8.0,
        },
        "past_the_multiplier_window_the_rate_entry_prices_it": {
            "entry": QUOTA,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T04:00:00Z",
            "expected": 1.0 * 9.0 + 0.2 * 0.5 + 0.05 * 36.0,
        },
    }


FRAGMENT = (
    "#q=fixture%20one&sort=input&dir=desc&sel=fixture%2Fm1,fixture%2Fm2"
    "&calc=1000|200|30&day=2026-09-07&rate=0.5"
)


def decode_state(fragment: str) -> dict[str, object]:
    """The sort/dir pair of a fragment, in the shape `decodeState` yields it.

    The restore reads only that pair, so the leg stays honest if the fragment
    grows more keys.
    """
    params = dict(
        part.split("=", 1) for part in fragment.removeprefix("#").split("&") if "=" in part
    )
    return {
        "sort": params.get("sort", ""),
        "dir": params.get("dir", ""),
    }


def test_the_page_pricing_function_agrees_with_the_totals_above(tmp_path):
    cases = {
        name: {
            "entry": spec["entry"],
            "day": spec["day"],
            "tokens": spec["tokens"],
            "now": spec["now"],
        }
        for name, spec in _node_cases().items()
    }
    result = _node(tmp_path, {"cases": cases, "fragment": FRAGMENT})
    for name, spec in _node_cases().items():
        expected = spec["expected"]
        got = result["cases"][name]
        if expected is None:
            assert got is None, name
        else:
            assert got == pytest.approx(expected), name
    assert result["rate"] == pytest.approx((1000000 + 200000 + 50000) / 1e6 * 2.5)


def test_a_fragment_restores_the_whole_state(tmp_path):
    result = _node(tmp_path, {"cases": {}, "fragment": FRAGMENT})
    assert result["state"] == {
        "q": "fixture one",
        "sort": "input",
        "dir": "desc",
        "sel": ["fixture/m1", "fixture/m2"],
        "calc": {"input": 1000, "cached": 200, "output": 30},
        "day": "2026-09-07",
        "rate": "0.5",
    }


def test_a_desc_fragment_restore_clicks_the_sort_button_twice(tmp_path):
    """The cycle write races the read: the controller's click handler overwrote
    `state.dir` with the cycle's next value before the second click was decided,
    so a `desc` fragment restored as `asc` (found by eye in a browser, 2026-09-11).

    The stub replays the two sides exactly: the controller's `none -> asc ->
    desc -> none` cycle, and the page's own listener writing the emitted dir
    back into the state the restore reads.
    """
    state = decode_state("#sort=input&dir=desc")
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "restoreSort": {"state": state},
        },
    )
    assert result["restoreSort"] == {"clicks": 2, "dir": "desc"}


@pytest.mark.parametrize(
    ("fragment", "clicks", "dir"),
    [
        ("#sort=input&dir=asc", 1, "asc"),
        ("#sort=input", 1, "asc"),
        ("", 0, ""),
    ],
)
def test_every_other_fragment_restores_in_one_step_or_none(tmp_path, fragment, clicks, dir):
    state = decode_state(fragment)
    result = _node(tmp_path, {"cases": {}, "fragment": "", "restoreSort": {"state": state}})
    assert result["restoreSort"] == {"clicks": clicks, "dir": dir}


def test_a_fragment_that_names_nothing_keeps_the_defaults(tmp_path):
    result = _node(tmp_path, {"cases": {}, "fragment": ""})
    assert result["state"] == {
        "q": "",
        "sort": "",
        "dir": "",
        "sel": [],
        "calc": {"input": 1000000, "cached": 0, "output": 0},
        "day": "",
        "rate": "",
    }
    assert result["encoded"] == "calc=1000000|0|0"


def test_a_malformed_fragment_falls_back_rather_than_raising(tmp_path):
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "#sort=nowhere&dir=sideways&calc=1|2&day=yesterday&rate=-4&sel=%zz",
        },
    )
    assert result["state"]["sort"] == ""
    assert result["state"]["dir"] == ""
    assert result["state"]["calc"] == {"input": 1000000, "cached": 0, "output": 0}
    assert result["state"]["day"] == ""
    assert result["state"]["rate"] == ""
    assert result["state"]["sel"] == ["%zz"]


def test_the_page_carries_the_sprite_verbatim_as_the_first_body_element(tmp_path):
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    sprite = (out / "site" / "icons.svg").read_text(encoding="utf-8")
    assert sprite.strip() in (out / "index.html").read_text(encoding="utf-8")
    first = soup.body.find(True)
    assert first.name == "svg"
    assert first["hidden"] == ""


def test_the_fallback_is_hidden_until_the_page_reports_in(tmp_path):
    """The page's failure message must never show on a page that came up.

    The interactive half is filled by the script that would also reveal this,
    so a markup that shipped it visible would show every reader an error about
    a page that is working.
    """
    out = _built(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    fallback = _soup(html).select_one("#app-fallback")
    assert fallback is not None
    assert "hidden" in fallback.attrs
    # a reader without javascript still gets the server-rendered table
    assert "js-only" in fallback["class"]

    # the page's half, and the one thing behaviour cannot reach: that a page
    # which came up hands the report to the module at all
    assert PAGE_READ in html
    assert PAGE_CALL in APP_JS.read_text(encoding="utf-8")


def test_the_page_reports_ready_only_once_its_controller_has_run(tmp_path):
    """The writer half of the handshake, exercised as behaviour.

    A pin on the statement outlives an edit that keeps the literals and defangs
    the write, so the module's own function is driven against both stubs: an
    unmarked wrap must leave the document unreported, a marked one must report.
    """
    result = _node(tmp_path, {"cases": {}, "fragment": "", "ready": True})
    assert result["ready"] == {
        "unmarked": None,
        "marked": "ready",
        "reported": [False, True],
    }


def test_the_reveal_actually_reveals_the_fallback(tmp_path):
    """The pinned literals would outlive a reveal wired to do nothing.

    So the page's own script is lifted back out of the built html and run under
    node against a stub document: with no mark it has to unhide the fallback,
    and with the mark it has to leave it alone.
    """
    out = _built(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    scripts = [
        body for body in re.findall(r"<script>(.*?)</script>", html, re.S) if PAGE_READ in body
    ]
    assert len(scripts) == 1, "the mark should have exactly one reader in the page"

    result = _node(tmp_path, {"cases": {}, "fragment": "", "reveal": scripts[0]})
    assert result["reveal"] == {"unmarked": False, "marked": True}


def test_a_rate_prints_the_same_way_in_both_tables(tmp_path):
    """The server-rendered table and the page's own renderer agree on every
    rate the export carries.

    They implement the same shortest-round-trip rule with different primitives
    (python's `repr` against javascript's number-to-string), and they part
    company outside the band a real rate sits in, so the contract is pinned
    over the rates that actually ship rather than asserted in a docstring.
    """
    payload = publish.build_flat(
        store.load_shards(ROOT / store.SHARD_DIR), ROOT, tmp_path / "out", 4
    )
    values = sorted(
        {
            value
            for entry in payload["entries"]
            for value in (entry.get("rates") or {}).values()
            if isinstance(value, (int, float))
        }
    )
    assert len(values) > 100, "the real export carries far more distinct rates than this"

    result = _node(tmp_path, {"cases": {}, "fragment": "", "rates": values})
    assert result["rates"] == [site._rate_text(value) for value in values]
