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
SITE_ASSETS = APP_JS.parent

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
  out.cases[name] = app.priceSession(
    spec.entry, spec.day, spec.tokens, new Date(spec.now), spec.mode ?? "");
}
out.state = app.decodeState(probe.fragment);
out.encoded = app.encodeState(out.state);
out.rate = probe.cases.peak ? app.priceAtRate(2.5, probe.cases.peak.tokens) : null;
out.rates = (probe.rates ?? []).map(v => app.formatRate(v));
out.matches = (probe.matches ?? []).map(m => app.whenMatches(m.when, m.ctx));
out.chat = (probe.chat ?? []).map(entry => app.isChatPriced(entry));
out.chart = (probe.chart ?? []).map(spec => app.chartPoints(spec.entry, spec.axis));
out.chartPeak = (probe.chartPeak ?? []).map(spec => app.chartPoints(spec.entry, spec.axis, true));
out.peakRates = (probe.peakRates ?? []).map(spec => app.peakRate(spec.entry, spec.axis));
out.peakState = {
  on: app.decodeState(probe.peakFragment ?? "").peak,
  encoded: app.encodeState({ ...app.defaultState(), model: "alpha/m1", peak: true }),
};
out.axes = app.CHART_AXES;
out.polyline = (probe.polyline ?? []).map(
  spec => app.stepPolyline(spec.run, spec.domain, spec.peak, spec.flat));
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
if (probe.modeChanges) {
  // the browser's own init run against a stub dom: the only path that fires
  // the mode select's change listener. every element is one shared shape,
  // because init only sets properties and registers listeners on them
  const element = () => ({
    textContent: "", className: "", hidden: false, value: "", type: "",
    dataset: {}, checked: false,
    append() {}, replaceChildren() {}, setAttribute() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(name, fn) { (this._listeners || (this._listeners = {}))[name] = fn; },
  });
  const wrap = element();
  wrap.dataset.uiTable = "1";
  const elements = new Map([["models", wrap], ["models-body", element()]]);
  const island = element();
  island.textContent = JSON.stringify({ entries: [] });
  elements.set("flat-data", island);
  for (const id of [
    "q", "calc-input", "calc-cached", "calc-output", "calc-day", "calc-rate",
    "calc-mode", "session-wrap", "session-body", "session-empty",
    "session-note", "rate-line", "model-count",
  ]) elements.set(id, element());
  const hashes = [];
  globalThis.document = {
    documentElement: { dataset: {} },
    getElementById: (id) => elements.get(id) ?? null,
    createElement: () => element(),
    createTextNode: () => element(),
    createDocumentFragment: () => element(),
  };
  globalThis.window = {
    location: { hash: "" },
    history: { replaceState(_state, _title, url) { hashes.push(String(url)); } },
  };
  app.init();
  const modeBox = elements.get("calc-mode");
  out.modeChanges = {};
  for (const value of probe.modeChanges) {
    modeBox.value = value;
    modeBox._listeners.change();
    // a fire that changes state pushes, so the last fragment always names the
    // post-fire state; an empty list means the state never left its default
    out.modeChanges[value] = app.decodeState(hashes[hashes.length - 1]).mode;
  }
  delete globalThis.document;
  delete globalThis.window;
}
if (probe.rows) {
  let builtRows = 0;
  const make = (tag) => {
    const el = {
      tag, children: [], className: "", textContent: "", hidden: false, value: "", type: "",
      dataset: {}, checked: false, attrs: {}, rects: [{}],
      append(...nodes) { this.children.push(...nodes); },
      replaceChildren(...nodes) {
        this.children = nodes.flatMap((node) => (node && node.isFragment ? node.children : [node]));
      },
      setAttribute(name, value) { this.attrs[name] = String(value); },
      getAttribute(name) { return this.attrs[name] ?? null; },
      getClientRects() { return this.rects; },
      getBoundingClientRect() { return { top: 0, left: 0 }; },
      scrollIntoView() {},
      style: { setProperty() {} },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener(name, fn) { (this._listeners || (this._listeners = {}))[name] = fn; },
    };
    const has = (name) => el.className.split(/\\s+/).includes(name);
    el.classList = {
      contains: has,
      add(name) {
        if (!has(name)) el.className = `${el.className} ${name}`.trim();
      },
      toggle(name, force) {
        const on = force === undefined ? !has(name) : Boolean(force);
        if (on && !has(name)) el.className = `${el.className} ${name}`.trim();
        if (!on && has(name))
          el.className = el.className.split(/\\s+/).filter((n) => n !== name).join(" ");
        return on;
      },
    };
    return el;
  };
  const wrap = make("div");
  wrap.dataset.uiTable = "1";
  const body = make("tbody");
  // the shipped controller's own sort cycle, driven through the page's own
  // buttons, so a fragment restore steps the clicks a reader would make and a
  // column the layout hides reports no client rect
  const sortState = { key: null, dir: "none" };
  const sortButtons = new Map();
  for (const key of ["name", "vendor", "input", "cache_read", "output"]) {
    const button = make("button");
    button.dataset.sort = key;
    const column = make("th");
    column.dataset.sort = key;
    if ((probe.rows.hiddenColumns ?? []).includes(key)) column.rects = [];
    button.closest = (sel) => (sel === "th" ? column : null);
    button.click = () => {
      const next = { none: "asc", asc: "desc", desc: "none" };
      sortState.dir = sortState.key === key ? next[sortState.dir] : "asc";
      sortState.key = key;
      wrap._listeners?.["table:sort"]?.({ detail: { key, dir: sortState.dir } });
    };
    sortButtons.set(key, button);
  }
  wrap.querySelector = (sel) => {
    const match = /\.th-sort\[data-sort="(.+)"\]/.exec(sel);
    return match ? sortButtons.get(match[1]) ?? null : null;
  };
  wrap.querySelectorAll = (sel) => (sel === ".th-sort" ? [...sortButtons.values()] : []);
  const elements = new Map([["models", wrap], ["models-body", body]]);
  const island = make("script");
  island.textContent = JSON.stringify(probe.rows.island);
  elements.set("flat-data", island);
  for (const id of [
    "q", "calc-input", "calc-cached", "calc-output", "calc-day", "calc-rate",
    "calc-mode", "session-wrap", "session-body", "session-empty",
    "session-note", "rate-line", "model-count", "peak-toggle",
    "model-detail", "detail-name", "detail-id", "detail-tags", "detail-empty",
    "detail-body", "detail-close", "detail-ticks-y", "detail-ticks-x", "detail-info",
  ]) elements.set(id, make("input"));
  // the detail card's chart skeleton, the shape detailNodes and drawChart read
  const chart = make("div");
  const svg = make("svg");
  const chartTitle = make("title");
  const chartDesc = make("desc");
  svg.querySelector = (sel) => (sel === "title" ? chartTitle : sel === "desc" ? chartDesc : null);
  svg.querySelectorAll = (sel) => (sel === ".chart-series" ? [series] : []);
  const chartGrid = make("g");
  const series = make("g");
  const line = make("polyline");
  series.querySelector = (sel) => (sel === ".chart-line" ? line : null);
  chart.querySelector = (sel) => ({
    ".chart-svg": svg, ".chart-grid": chartGrid, ".chart-series": series, ".chart-line": line,
  }[sel] ?? null);
  elements.set("detail-chart", chart);
  const axisButtons = ["input", "output", "cache_read"].map((axis) => {
    const button = make("button");
    button.dataset.axis = axis;
    return button;
  });
  elements.get("model-detail").querySelectorAll =
    (sel) => (sel === "[data-axis]" ? axisButtons : []);
  const hashes = [];
  const windowListeners = {};
  globalThis.document = {
    documentElement: { dataset: {} },
    getElementById: (id) => elements.get(id) ?? null,
    createElement: (tag) => {
      if (tag === "tr") builtRows += 1;
      return make(tag);
    },
    createTextNode: (text) => ({ textContent: String(text), children: [] }),
    createDocumentFragment: () => ({ ...make("fragment"), isFragment: true }),
  };
  globalThis.window = {
    location: { hash: probe.rows.hash },
    history: { replaceState(_state, _title, url) { hashes.push(String(url)); } },
    addEventListener(name, fn) { windowListeners[name] = fn; },
  };
  app.init();
  const builtOnInit = builtRows;
  const steps = [];
  for (const filter of probe.rows.filters ?? []) {
    const box = elements.get("q");
    box.value = filter;
    box._listeners?.input?.();
    steps.push({
      filter,
      built: builtRows,
      count: elements.get("model-count").textContent,
      rows: body.children.map((tr) => ({
        key: tr.children[1]?.children?.[0]?.dataset?.key ?? "",
        hidden: tr.hidden === true,
      })),
    });
  }
  if (probe.rows.hideColumnAfter) {
    sortButtons.get(probe.rows.hideColumnAfter).closest("th").rects = [];
    windowListeners.resize?.();
  }
  const cardSnapshot = () => ({
    name: elements.get("detail-name").textContent,
    info: elements.get("detail-info").children.map((tr) => tr.children.map((td) => td.textContent)),
    desc: chartDesc.textContent,
    pressed: elements.get("peak-toggle").attrs["aria-pressed"] ?? null,
    on: /(^|\\s)on(\\s|$)/.test(elements.get("peak-toggle").className),
  });
  let card = probe.rows.cardAfterInit ? cardSnapshot() : null;
  if (probe.rows.clickModel) {
    const picked = body.children.find(
      (row) => row.children[1]?.children?.[0]?.dataset?.key === probe.rows.clickModel);
    picked?.children[1]?.children?.[0]?._listeners?.click?.({});
    card = cardSnapshot();
  }
  let axisCard = null;
  if (probe.rows.chartAxis) {
    const button = axisButtons.find((b) => b.dataset.axis === probe.rows.chartAxis);
    button?._listeners?.click?.({});
    axisCard = cardSnapshot();
  }
  const toggleStates = [];
  for (let i = 0; i < (probe.rows.toggles ?? 0); i += 1) {
    elements.get("peak-toggle")._listeners?.click?.({});
    toggleStates.push({
      url: hashes[hashes.length - 1] ?? probe.rows.hash,
      rates: body.children.map((tr) => tr.children.slice(3, 6).map((td) => td.textContent)),
      tags: body.children.map((tr) =>
        tr.children[1].children
          .filter((node) => typeof node.className === "string" && node.className.startsWith("tag "))
          .map((node) => node.textContent)),
      card: cardSnapshot(),
    });
  }
  const hasBox = (node) =>
    node.type === "checkbox"
    || (Array.isArray(node.children) && node.children.some(hasBox));
  out.rows = {
    "built_on_init": builtOnInit,
    "built_after_steps": builtRows,
    // the fragment the page ends on: a rewritten one when it dropped a key,
    // else the one it loaded
    url: hashes[hashes.length - 1] ?? probe.rows.hash,
    toggle_states: toggleStates,
    card,
    axis_card: axisCard,
    session_rows: elements.get("session-body").children.length,
    steps,
    model_rows: body.children.map((tr) => {
      const name = tr.children[1];
      const spark = tr.children[6].children[0];
      const lines = spark && spark.className === "stat-spark"
        ? spark.children.flatMap((svg) => svg.children
            .filter((node) => node.tag === "polyline")
            .map((node) => node.attrs.points ?? ""))
        : null;
      return {
        hidden: tr.hidden === true,
        has_box: hasBox(tr.children[0]),
        name: name.children[0].textContent,
        rates: tr.children.slice(3, 6).map((td) => td.textContent),
        tags: name.children
          .filter((node) => typeof node.className === "string" && node.className.startsWith("tag "))
          .map((node) => node.textContent),
        vendor_class: tr.children[2].className,
        lines,
        spark_text: spark && spark.className !== "stat-spark" ? spark.textContent : "",
      };
    }),
  };
  delete globalThis.document;
  delete globalThis.window;
}
out.modes = app.MODES;
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

# a request-mode override: anthropic fast mode prices a speed:"fast" request
# at premium rates while the standard request keeps the base rates
FAST = {
    "source": "fixture",
    "model_id": "m5",
    "vendor": "fixture",
    "name": "Fixture Five",
    "observed_at": "2026-08-01",
    "rates": {"input": 5.0, "output": 25.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": None,
            "observed_at": "2026-08-01",
            "rates": {"input": 5.0, "output": 25.0},
            "overrides": [{"when": {"mode": "fast"}, "rates": {"input": 10.0, "output": 50.0}}],
        }
    ],
}

# the openai image batch override: the batch pane repeats the gpt-image ids at
# discounted rates, so a batch-mode session prices the pane's own cells
BATCH = {
    "source": "openai",
    "model_id": "gpt-image-2",
    "vendor": "openai",
    "name": "gpt-image-2",
    "observed_at": "2026-09-15",
    "rates": {"input": 5.0, "cache_read": 1.25, "output": 30.0},
    "intervals": [
        {
            "valid_from": "2026-09-15",
            "valid_to": None,
            "observed_at": "2026-09-15",
            "rates": {"input": 5.0, "cache_read": 1.25, "output": 30.0},
            "overrides": [
                {
                    "when": {"mode": "batch"},
                    "rates": {
                        "input": 2.5,
                        "cache_read": 0.625,
                        "output": 15.0,
                        "image": 4.0,
                        "image_output": 15.0,
                    },
                }
            ],
        }
    ],
}

# 2026-09-07 02:00 UTC is a monday, 120 minutes in, inside the 100..400 window
SESSION = {"input": 1000000, "cached": 200000, "output": 50000}

# a non-text row: the export labels it and the calculator never prices it as chat
MODALITY = {
    "source": "fixture",
    "model_id": "m6",
    "vendor": "fixture",
    "name": "Fixture Six",
    "observed_at": "2026-08-01",
    "modality": "image",
    "rates": {"image": 40.0, "input": 1.0, "output": 4.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": None,
            "observed_at": "2026-08-01",
            "rates": {"image": 40.0, "input": 1.0, "output": 4.0},
        }
    ],
}

# a two-interval chain for the price-history chart: input and output move on
# 2026-10-01, and cache_read is priced only in the first era, so an axis whose
# data runs out pins the line's own end
CHAIN = {
    "source": "fixture",
    "model_id": "m7",
    "vendor": "fixture",
    "name": "Fixture Seven",
    "observed_at": "2026-10-01",
    "rates": {"input": 1.0, "output": 4.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": "2026-10-01",
            "observed_at": "2026-08-01",
            "rates": {"input": 2.0, "output": 8.0, "cache_read": 0.25},
        },
        {
            "valid_from": "2026-10-01",
            "valid_to": None,
            "observed_at": "2026-10-01",
            "rates": {"input": 1.0, "output": 4.0},
        },
    ],
}

# the inverted pair the interval rule clamps to an empty span: the 08-01 row
# never applied, so only the 09-01 rate is a price the model was charged
INVERTED = {
    "source": "fixture",
    "model_id": "m8",
    "vendor": "fixture",
    "name": "Fixture Eight",
    "observed_at": "2026-09-01",
    "rates": {"input": 3.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": "2026-08-01",
            "observed_at": "2026-09-01",
            "rates": {"input": 1.5},
        },
        {
            "valid_from": "2026-09-01",
            "valid_to": None,
            "observed_at": "2026-09-01",
            "rates": {"input": 3.0},
        },
    ],
}

# an axis that stops being priced for one era and comes back: 101 stored keys
# carry this shape, so the chart must not drop either era
GAPPED = {
    "source": "fixture",
    "model_id": "m9",
    "vendor": "fixture",
    "name": "Fixture Nine",
    "observed_at": "2026-10-01",
    "rates": {"input": 1.0, "output": 4.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": "2026-09-01",
            "observed_at": "2026-08-01",
            "rates": {"input": 2.0, "output": 8.0},
        },
        {
            "valid_from": "2026-09-01",
            "valid_to": "2026-10-01",
            "observed_at": "2026-09-01",
            "rates": {"output": 9.0},
        },
        {
            "valid_from": "2026-10-01",
            "valid_to": None,
            "observed_at": "2026-10-01",
            "rates": {"input": 1.0, "output": 4.0},
        },
    ],
}

# a model removed and later revived: 38 stored keys carry this shape, and the
# entry is not removed now
REVIVED = {
    "source": "fixture",
    "model_id": "m10",
    "vendor": "fixture",
    "name": "Fixture Ten",
    "observed_at": "2026-09-10",
    "rates": {"input": 1.0},
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": "2026-08-20",
            "observed_at": "2026-08-01",
            "rates": {"input": 2.0},
        },
        {
            "valid_from": "2026-08-20",
            "valid_to": "2026-09-10",
            "observed_at": "2026-08-20",
            "removed": True,
        },
        {
            "valid_from": "2026-09-10",
            "valid_to": None,
            "observed_at": "2026-09-10",
            "rates": {"input": 1.0},
        },
    ],
}

# a provenance name a scraper could hand back: interpolated raw it would close
# the page's script island, and escaped it is just a name
NASTY = "</script><script>alert(1)</script>"

# a scheduled peak: the clock window raises all three table axes, while the
# threshold, mode and day-only overrides price no clock range and must not
# enter the peak reading; the last override carries a quota, not a rate
PEAK = {
    "source": "fixture",
    "model_id": "p1",
    "vendor": "fixture",
    "name": "Peak One",
    "observed_at": "2026-08-01",
    "rates": {"input": 0.66, "output": 1.98, "cache_read": 0.022},
    "overrides": [
        {
            "when": {
                "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                "window": [100, 400],
            },
            "rates": {"input": 1.32, "output": 3.96, "cache_read": 0.044},
        },
        {"when": {"min_tokens": 100000}, "rates": {"input": 9.0}},
        {"when": {"mode": "fast"}, "rates": {"input": 8.0}},
        {"when": {"days": ["saturday", "sunday"]}, "rates": {"input": 7.0}},
        {"when": {"window": [1600, 2400]}, "quota_multiplier": 0.4},
    ],
}

# a base above every clock window: the peak reading equals the base, so the
# row carries no tag
PEAK_BASE = {
    "source": "fixture",
    "model_id": "p2",
    "vendor": "fixture",
    "name": "Peak Base",
    "observed_at": "2026-08-01",
    "rates": {"input": 0.132, "output": 0.528, "cache_read": 0.033},
    "overrides": [
        {
            "when": {"window": [0, 1600]},
            "rates": {"input": 0.132, "output": 0.528, "cache_read": 0.033},
        },
        {
            "when": {"window": [1600, 2400]},
            "rates": {"input": 0.0825, "output": 0.33, "cache_read": 0.020625},
        },
    ],
}

PLAIN = {
    "source": "fixture",
    "model_id": "p3",
    "vendor": "fixture",
    "name": "Plain Three",
    "observed_at": "2026-08-01",
    "rates": {"input": 2.0, "output": 4.0, "cache_read": 0.5},
}

# a window that raises only two axes: the cache axis the window leaves out
# keeps its base rate in the peak reading
PEAK_PARTIAL = {
    "source": "fixture",
    "model_id": "p4",
    "vendor": "fixture",
    "name": "Peak Partial",
    "observed_at": "2026-08-01",
    "rates": {"input": 1.0, "output": 2.0, "cache_read": 0.5},
    "overrides": [{"when": {"window": [0, 600]}, "rates": {"input": 3.0}}],
}

# a model whose window raises the only axis it prices, so its peak input (3.0)
# outranks the plain entry's 2.0 while its base input (1.0) sits below it
PEAK_SORT = {
    "source": "fixture",
    "model_id": "s1",
    "vendor": "fixture",
    "name": "Sort Peak",
    "observed_at": "2026-08-01",
    "rates": {"input": 1.0, "output": 2.0},
    "overrides": [{"when": {"window": [0, 600]}, "rates": {"input": 3.0}}],
}

# an axis that exists only in the window: the card's peak reading lists it,
# while the base rates carry no such rate at all
PEAK_AXIS = {
    "source": "fixture",
    "model_id": "a1",
    "vendor": "fixture",
    "name": "Axis Only",
    "observed_at": "2026-08-01",
    "rates": {"input": 1.0},
    "overrides": [{"when": {"window": [0, 600]}, "rates": {"input": 2.0, "cache_read": 0.5}}],
}

# a detail-card model: its entry-level and per-interval schedules are raised by
# the same window, so the card's rate rows and its chart both have a peak to read
CARD = {
    "source": "fixture",
    "model_id": "c1",
    "vendor": "fixture",
    "name": "Card One",
    "observed_at": "2026-08-01",
    "rates": {"input": 1.0, "output": 2.0, "cache_read": 0.5},
    "overrides": [{"when": {"window": [0, 600]}, "rates": {"input": 2.0, "output": 4.0}}],
    "intervals": [
        {
            "valid_from": "2026-08-01",
            "valid_to": "2026-09-01",
            "observed_at": "2026-08-01",
            "rates": {"input": 1.0, "output": 2.0, "cache_read": 0.5},
            "overrides": [{"when": {"window": [0, 600]}, "rates": {"input": 2.0, "output": 4.0}}],
        },
        {
            "valid_from": "2026-09-01",
            "valid_to": None,
            "observed_at": "2026-09-01",
            "rates": {"input": 1.0, "output": 2.0, "cache_read": 0.5},
            "overrides": [{"when": {"window": [0, 600]}, "rates": {"input": 2.0, "output": 4.0}}],
        },
    ],
}


def _rows() -> list[dict[str, object]]:
    """The shared fixture rows plus one carrying markup in its name."""
    return [
        *_flat_rows(),
        MODALITY,
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
    export = json.loads((out / "flat-v3.json").read_text(encoding="utf-8"))
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


def test_a_modality_entry_is_labelled_in_the_static_table(tmp_path):
    out = _built(tmp_path)
    rows = _soup((out / "index.html").read_text(encoding="utf-8")).select("#models-static tbody tr")
    row = next(row for row in rows if row["data-key"] == "fixture/m6")
    label = row.select_one("td span.tag")
    assert label is not None
    assert label.get_text() == "image"


def test_the_calculator_neither_selects_nor_prices_a_modality_entry(tmp_path):
    out = _built(tmp_path)
    export = json.loads((out / "flat-v3.json").read_text(encoding="utf-8"))
    modality = next(entry for entry in export["entries"] if entry.get("modality") == "image")
    text = next(entry for entry in export["entries"] if "modality" not in entry)
    result = _node(
        tmp_path,
        {"cases": {}, "fragment": "", "chat": [modality, text, {"modality": ""}]},
    )
    assert result["chat"] == [False, True, True]


def test_a_modality_row_has_no_checkbox_and_never_prices_a_session(tmp_path):
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [ENTRY, MODALITY]},
                "hash": "#sel=fixture%2Fm1,fixture%2Fm6",
            },
        },
    )
    rows = result["rows"]["model_rows"]
    assert [row["name"] for row in rows] == ["Fixture One", "Fixture Six"]
    assert [row["has_box"] for row in rows] == [True, False]
    assert rows[1]["tags"] == ["image"]
    # the fragment named both keys; the modality key is dropped, so only the
    # chat entry prices a session
    assert result["rows"]["session_rows"] == 1


def test_every_row_draws_its_price_history_sparkline(tmp_path):
    """The row carries the model's own shape on the input axis, and a row with
    no priced interval draws none rather than an empty line."""
    bare = {
        "source": "fixture",
        "model_id": "m11",
        "vendor": "fixture",
        "observed_at": "2026-08-01",
        "rates": {"image": 1.0},
        "intervals": [],
    }
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {"island": {"entries": [ENTRY, MODALITY, bare]}, "hash": ""},
        },
    )
    rows = result["rows"]["model_rows"]
    assert [row["lines"] is not None for row in rows] == [True, True, False]
    assert [len(row["lines"]) for row in rows[:2]] == [1, 1]
    # the row with nothing to draw takes the table's dash: an empty cell reads
    # as a bug, and the export's own no-reading convention is the en dash
    assert [row["spark_text"] for row in rows] == ["", "", "–"]
    # the vendor column's own class is what the desktop hide rule targets, on
    # the row side; the header carries it beside this
    assert [row["vendor_class"] for row in rows] == ["col-vendor"] * 3


def test_the_row_sparkline_draws_the_input_axis(tmp_path):
    """GAPPED prices input and output differently, so the drawn coordinates say
    which axis the sparkline read: input runs 2.0 then 1.0 over a peak of 2, so
    the first era sits at the top of the box and the second at its middle. An
    output-based sparkline would draw 8.0 then 9.0 and land at neither."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {"island": {"entries": [GAPPED]}, "hash": ""},
        },
    )
    lines = result["rows"]["model_rows"][0]["lines"]
    levels = [[point.split(",")[1] for point in line.split()] for line in lines]
    assert levels == [["0", "0"], ["50", "50"]]


def _stub_entry(source: str, model_id: str, name: str, vendor: str, input_rate: float):
    return {
        "source": source,
        "model_id": model_id,
        "vendor": vendor,
        "name": name,
        "observed_at": "2026-08-01",
        "rates": {"input": input_rate, "output": input_rate * 2},
        "intervals": [
            {
                "valid_from": "2026-08-01",
                "valid_to": None,
                "observed_at": "2026-08-01",
                "rates": {"input": input_rate, "output": input_rate * 2},
            }
        ],
    }


def test_a_search_keystroke_hides_rows_instead_of_rebuilding_them(tmp_path):
    """The filter toggles the built rows rather than constructing them again.

    A rebuilt row and a toggled one look the same to every reader, so the
    construction count is the only seam that tells them apart: the pre-change
    page built three fresh rows on each of the three keystrokes.
    """
    entries = [
        _stub_entry("alpha", "m1", "Alpha One", "alpha", 1.0),
        _stub_entry("beta", "m2", "Beta Two", "beta", 2.0),
        _stub_entry("beta", "m3", "Beta Three", "beta", 3.0),
    ]
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": entries},
                "hash": "",
                "filters": ["one", "zzz", ""],
            },
        },
    )
    rows = result["rows"]
    assert rows["built_on_init"] == 3
    assert rows["built_after_steps"] == 3
    assert [step["built"] for step in rows["steps"]] == [3, 3, 3]
    assert [step["count"] for step in rows["steps"]] == [
        "1 of 3 models",
        "0 of 3 models",
        "3 of 3 models",
    ]
    assert rows["steps"][0]["rows"] == [
        {"key": "alpha/m1", "hidden": False},
        {"key": "beta/m2", "hidden": True},
        {"key": "beta/m3", "hidden": True},
    ]
    assert rows["steps"][1]["rows"] == [
        {"key": "alpha/m1", "hidden": True},
        {"key": "beta/m2", "hidden": True},
        {"key": "beta/m3", "hidden": True},
    ]
    assert rows["steps"][2]["rows"] == [
        {"key": "alpha/m1", "hidden": False},
        {"key": "beta/m2", "hidden": False},
        {"key": "beta/m3", "hidden": False},
    ]


def test_a_sort_reorders_the_built_rows_without_rebuilding_them(tmp_path):
    """A sort moves the rows it already has: the fragment restores by clicking
    the controller's own button, so the page's sort handler runs the same path
    a reader's click does."""
    entries = [
        _stub_entry("beta", "first", "Beta First", "beta", 1.0),
        _stub_entry("alpha", "second", "Alpha Second", "alpha", 2.0),
        _stub_entry("alpha", "third", "Alpha Third", "alpha", 3.0),
    ]
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": entries},
                "hash": "#sort=vendor&dir=asc",
                "filters": ["second"],
            },
        },
    )
    rows = result["rows"]
    assert rows["built_on_init"] == 3
    assert rows["built_after_steps"] == 3
    # a stable sort keeps the export's order inside the tie
    assert [row["name"] for row in rows["model_rows"]] == [
        "Alpha Second",
        "Alpha Third",
        "Beta First",
    ]
    # the filter hides its misses in that same sorted order
    assert rows["steps"][0]["rows"] == [
        {"key": "alpha/second", "hidden": False},
        {"key": "alpha/third", "hidden": True},
        {"key": "beta/first", "hidden": True},
    ]


def test_a_sort_on_a_hidden_column_is_dropped(tmp_path):
    """The vendor column leaves the table at 1100px and up, so a `sort=vendor`
    fragment would order every row by a fact no reader can see on desktop. The
    column's own visibility decides it, never a breakpoint restated in the
    script: the stub reports the header with no client rect."""
    entries = [
        _stub_entry("beta", "first", "Beta First", "beta", 1.0),
        _stub_entry("alpha", "second", "Alpha Second", "alpha", 2.0),
        _stub_entry("alpha", "third", "Alpha Third", "alpha", 3.0),
    ]
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": entries},
                "hash": "#sort=vendor&dir=asc",
                "hiddenColumns": ["vendor"],
            },
        },
    )
    rows = result["rows"]
    assert rows["url"] == "#calc=1000000|0|0"
    assert [row["name"] for row in rows["model_rows"]] == [
        "Beta First",
        "Alpha Second",
        "Alpha Third",
    ]


def test_a_visible_vendor_sort_still_applies(tmp_path):
    """The control on the same fixture with the column drawn: the drop above
    must read the column, not the key."""
    entries = [
        _stub_entry("beta", "first", "Beta First", "beta", 1.0),
        _stub_entry("alpha", "second", "Alpha Second", "alpha", 2.0),
        _stub_entry("alpha", "third", "Alpha Third", "alpha", 3.0),
    ]
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": entries},
                "hash": "#sort=vendor&dir=asc",
            },
        },
    )
    rows = result["rows"]
    assert rows["url"] == "#sort=vendor&dir=asc"
    assert [row["name"] for row in rows["model_rows"]] == [
        "Alpha Second",
        "Alpha Third",
        "Beta First",
    ]


def test_hiding_the_sorted_column_drops_the_sort_on_resize(tmp_path):
    """A mobile reader's vendor sort must not survive the width that hides the
    column: the resize handler re-reads the same visibility and drops it."""
    entries = [
        _stub_entry("beta", "first", "Beta First", "beta", 1.0),
        _stub_entry("alpha", "second", "Alpha Second", "alpha", 2.0),
        _stub_entry("alpha", "third", "Alpha Third", "alpha", 3.0),
    ]
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": entries},
                "hash": "#sort=vendor&dir=asc",
                "hideColumnAfter": "vendor",
            },
        },
    )
    rows = result["rows"]
    assert rows["url"] == "#calc=1000000|0|0"
    assert rows["built_after_steps"] == 3
    assert [row["name"] for row in rows["model_rows"]] == [
        "Beta First",
        "Alpha Second",
        "Alpha Third",
    ]


def test_every_key_of_the_real_export_renders(tmp_path):
    """The fixture cannot carry the shape of 1123 real entries; this one does."""
    rows = store.load_shards(ROOT / store.SHARD_DIR)
    out = tmp_path / "out"
    payload = publish.build_flat(rows, ROOT, out, 4)
    site.render_site(payload, out)

    export = json.loads((out / "flat-v3.json").read_text(encoding="utf-8"))
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
    file_payload = json.loads((out / "flat-v3.json").read_text(encoding="utf-8"))

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
    assert json.loads(island) == json.loads((out / "flat-v3.json").read_text(encoding="utf-8"))

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
    """Every id and class the module reaches for is on the page. The card's
    parts are found by class, so an id-only walk misses the lookup that makes
    the whole card render."""
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    script = APP_JS.read_text(encoding="utf-8")
    wanted = set(re.findall(r'getElementById\("([^"]+)"\)', script))
    assert wanted != set()
    for element_id in sorted(wanted):
        assert soup.select_one(f'[id="{element_id}"]') is not None, (
            f"the page never renders #{element_id}"
        )
    for selector in (".chart-svg", ".chart-series", ".chart-line", ".chart-grid"):
        assert selector in script, selector
        assert soup.select_one(f"#detail-chart {selector}") is not None, (
            f"the page never renders {selector}"
        )
    assert soup.select_one("[data-axis][aria-pressed]") is not None


def test_the_page_holds_a_model_detail_card(tmp_path):
    """The card is server-rendered and empty until a row is picked: `data-empty`
    is what hides it above the table on a phone, the body ships hidden, the
    empty state carries the instruction, the axis selector offers the chart's
    three axes with the first one selected, and the line ships with no points so
    nothing paints before the page fills it."""
    soup = _soup((_built(tmp_path) / "index.html").read_text(encoding="utf-8"))
    card = soup.select_one("#model-detail")
    assert card is not None
    assert card["data-empty"] == "true"
    assert "js-only" in card["class"]
    body = soup.select_one("#detail-body")
    assert body is not None and body.has_attr("hidden")
    empty = soup.select_one("#detail-empty")
    assert empty is not None
    assert empty.get_text(" ", strip=True) == (
        "select a model in the table to see its price history and rates"
    )
    axes = [
        (b.get("data-axis"), b.get_text(strip=True), b.get("aria-pressed"), " ".join(b["class"]))
        for b in card.select("[data-axis]")
    ]
    assert axes == [
        ("input", "input", "true", "btn btn-secondary"),
        ("output", "output", "false", "btn btn-secondary"),
        ("cache_read", "cache read", "false", "btn btn-secondary"),
    ]
    line = card.select_one(".chart .chart-line")
    assert line is not None and line.get("points") == ""


def test_the_shipped_asset_tree_names_no_design_system():
    """A published file must never name the internal system it was copied from.
    The sweep reads every text asset whole rather than the one header a reader
    happens to open, so a comment carried over in the next refresh fails here."""
    assert SITE_ASSETS.is_dir()
    for path in sorted(SITE_ASSETS.rglob("*")):
        if path.suffix in {".css", ".js", ".svg", ".html"}:
            text = path.read_text(encoding="utf-8").lower()
            assert "cloudy" not in text, f"{path.name} names the design system"


def test_the_toolbar_offers_a_peak_time_toggle(tmp_path):
    """The page-wide switch that prints the entry's highest scheduled rate: a
    real button in the shipped toggle costume, named by its own visible label."""
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    toggle = soup.select_one("#peak-toggle")
    assert toggle is not None
    assert toggle.name == "button"
    assert "toggle" in toggle.get("class", [])
    assert toggle.get("aria-pressed") == "false"
    assert toggle.get("aria-labelledby") == "peak-label"
    assert "toggle-wrap" in toggle.parent.get("class", [])
    label = soup.select_one("#peak-label")
    assert label is not None and label.get_text(strip=True) == "peak time"


def test_the_session_card_offers_the_request_modes(tmp_path):
    """The calculator's mode select: standard first and selected, then every
    request mode the index carries — fast (the anthropic premium) and batch
    (the openai image discount).

    The option set is pinned whole — one equality over the (value, label)
    pairs, never a substring walk that a fourth option would slip past.
    """
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    select = soup.select_one("#calc-mode")
    assert select is not None
    assert select.name == "select"
    label = soup.select_one('label[for="calc-mode"]')
    assert label is not None and label.get_text(strip=True) == "request mode"
    options = [
        (option.get("value", ""), option.get_text(strip=True), option.has_attr("selected"))
        for option in select.select("option")
    ]
    assert options == [
        ("", "standard", True),
        ("fast", "fast", False),
        ("batch", "batch", False),
    ]


def test_the_mode_gate_accepts_every_option_the_select_offers(tmp_path):
    """The change handler and the fragment restore both reset a mode the
    script's gate does not carry, so a mode dropped from `MODES` silently
    unselects it for every interactive user while every gate stays green.

    Driven over the served page's own option list through the real init run:
    each offered option fires the select's change event and must come back as
    the session's mode; the empty standard option and an unknown value must
    reset it.
    """
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    options = [option.get("value", "") for option in soup.select_one("#calc-mode").select("option")]
    result = _node(
        tmp_path,
        {"cases": {}, "fragment": "#mode=no-such-mode", "modeChanges": options + ["no-such-mode"]},
    )
    # the script's gate list and the select's options are two lists that must
    # stay one set: whole equality over the non-empty values, so a mode added
    # to or dropped from either side reds
    assert sorted(value for value in options if value) == sorted(result["modes"])
    for value in options:
        assert result["modeChanges"][value] == value, f"mode {value!r} reset by the gate"
    assert result["modeChanges"]["no-such-mode"] == ""
    # the fragment restore applies the same gate: a crafted fragment naming a
    # mode neither list carries must land on standard, not on a ghost mode
    assert result["state"]["mode"] == ""


def test_the_peak_rate_is_the_highest_priced_clock_window(tmp_path):
    """A peak reads the base and every override naming a clock window — never a
    threshold, mode, day-only or quota-only override, whose 9.0 / 8.0 / 7.0
    would otherwise outrank the window's 1.32."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "peakRates": [
                {"entry": PEAK, "axis": "input"},
                {"entry": PEAK, "axis": "output"},
                {"entry": PEAK, "axis": "cache_read"},
                {"entry": PEAK_BASE, "axis": "input"},
                {"entry": PLAIN, "axis": "input"},
                {"entry": PEAK_PARTIAL, "axis": "input"},
                {"entry": PEAK_PARTIAL, "axis": "output"},
                {"entry": PEAK_PARTIAL, "axis": "cache_read"},
            ],
        },
    )
    assert result["peakRates"] == [1.32, 3.96, 0.044, 0.132, 2.0, 3.0, 2.0, 0.5]


def test_the_peak_chart_points_read_each_interval_schedule(tmp_path):
    """Every interval's own overrides set its peak, so the history keeps its
    step shape instead of flattening to the entry's today rate."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "chartPeak": [{"entry": ENTRY, "axis": "input"}],
        },
    )
    runs = result["chartPeak"][0]["runs"]
    assert [point["value"] for run in runs for point in run["points"]] == [9.0, 1.0]


def test_the_peak_fragment_key_round_trips(tmp_path):
    result = _node(
        tmp_path,
        {"cases": {}, "fragment": "#peak=1", "peakFragment": "#peak=1"},
    )
    assert result["peakState"] == {
        "on": True,
        "encoded": "calc=1000000|0|0&model=alpha/m1&peak=1",
    }
    off = _node(
        tmp_path,
        {"cases": {}, "fragment": "#peak=0", "peakFragment": "#peak=0"},
    )
    assert off["peakState"]["on"] is False


def test_a_peak_fragment_prints_the_windowed_rates_and_tags_the_row(tmp_path):
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [PEAK, PEAK_BASE, PLAIN]},
                "hash": "#peak=1",
            },
        },
    )
    rows = result["rows"]["model_rows"]
    assert [row["rates"] for row in rows] == [
        ["1.32", "0.044", "3.96"],
        ["0.132", "0.033", "0.528"],
        ["2", "0.5", "4"],
    ]
    # the tag marks only a row whose printed rate moved off its base
    assert ["peak" in row["tags"] for row in rows] == [True, False, False]


def test_peak_off_prints_the_base_rates_with_no_tag(tmp_path):
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {"island": {"entries": [PEAK, PEAK_BASE, PLAIN]}, "hash": ""},
        },
    )
    rows = result["rows"]["model_rows"]
    assert [row["rates"] for row in rows] == [
        ["0.66", "0.022", "1.98"],
        ["0.132", "0.033", "0.528"],
        ["2", "0.5", "4"],
    ]
    assert [row["tags"] for row in rows] == [[], [], []]


def test_the_peak_toggle_reprices_the_table_and_rides_the_fragment(tmp_path):
    """One click repaints every row from the entry's own peak and writes the
    fragment; the second click puts both back."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [PEAK, PLAIN]},
                "hash": "",
                "toggles": 2,
            },
        },
    )
    on, off = result["rows"]["toggle_states"]
    assert on["url"] == "#calc=1000000|0|0&peak=1"
    assert on["rates"] == [["1.32", "0.044", "3.96"], ["2", "0.5", "4"]]
    assert ["peak" in tag for tag in on["tags"]] == [True, False]
    assert off["url"] == "#calc=1000000|0|0"
    assert off["rates"] == [["0.66", "0.022", "1.98"], ["2", "0.5", "4"]]
    assert ["peak" in tag for tag in off["tags"]] == [False, False]


def test_the_open_card_reads_peak_rates_and_follows_the_toggle(tmp_path):
    """The card's rate rows and its chart read the same peak the table does,
    and a toggle with the card open repaints both in place."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [CARD, PLAIN]},
                "hash": "#peak=1",
                "clickModel": "fixture/c1",
                "toggles": 1,
            },
        },
    )
    rows = result["rows"]
    assert rows["card"]["name"] == "Card One"
    assert rows["card"]["info"][:3] == [
        ["rate input", "2"],
        ["rate output", "4"],
        ["rate cache read", "0.5"],
    ]
    assert rows["card"]["desc"] == (
        "input price per million tokens: 2 from 2026-08-01, 2 from 2026-09-01."
    )
    assert rows["card"]["pressed"] == "true"
    assert rows["card"]["on"] is True
    after = rows["toggle_states"][0]
    assert after["card"]["info"][:3] == [
        ["rate input", "1"],
        ["rate output", "2"],
        ["rate cache read", "0.5"],
    ]
    assert after["card"]["desc"] == (
        "input price per million tokens: 1 from 2026-08-01, 1 from 2026-09-01."
    )
    assert after["card"]["pressed"] == "false"
    assert after["card"]["on"] is False


def test_a_peak_fragment_opens_the_card_at_peak(tmp_path):
    """A shared link naming both a model and peak opens the card on the peak
    reading, not on the base one its neighbour renders off."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [CARD]},
                "hash": "#model=fixture/c1&peak=1",
                "cardAfterInit": True,
            },
        },
    )
    card = result["rows"]["card"]
    assert card["name"] == "Card One"
    assert card["info"][:3] == [
        ["rate input", "2"],
        ["rate output", "4"],
        ["rate cache read", "0.5"],
    ]
    assert card["desc"] == "input price per million tokens: 2 from 2026-08-01, 2 from 2026-09-01."


def test_switching_the_card_axis_keeps_the_peak_reading(tmp_path):
    """The axis buttons redraw the chart from the interval schedule; under peak
    the redraw must stay on the peak values."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [CARD]},
                "hash": "#peak=1",
                "clickModel": "fixture/c1",
                "chartAxis": "output",
            },
        },
    )
    card = result["rows"]["axis_card"]
    assert card["desc"] == (
        "output price per million tokens: 4 from 2026-08-01, 4 from 2026-09-01."
    )


def test_a_rate_sort_orders_by_the_printed_peak(tmp_path):
    """The sort and the cells must read one value: base order is Sort Peak then
    Plain Three, and the window flips it."""
    island = {"entries": [PEAK_SORT, PLAIN]}
    on = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {"island": island, "hash": "#sort=input&dir=asc&peak=1"},
        },
    )
    off = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {"island": island, "hash": "#sort=input&dir=asc"},
        },
    )
    assert [row["name"] for row in on["rows"]["model_rows"]] == ["Plain Three", "Sort Peak"]
    assert [row["name"] for row in off["rows"]["model_rows"]] == ["Sort Peak", "Plain Three"]


def test_the_card_lists_an_axis_that_only_the_window_prices(tmp_path):
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [PEAK_AXIS]},
                "hash": "#peak=1",
                "clickModel": "fixture/a1",
            },
        },
    )
    info = result["rows"]["card"]["info"]
    assert ["rate input", "2"] in info
    assert ["rate cache read", "0.5"] in info


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
        "a_volume_threshold_exactly_met_prices_the_base_tier": {
            "entry": VOLUME,
            "day": "2026-09-07",
            # anthropic bills "over N": a prompt of exactly 500000 does not
            # reach the override, so it prices the base input rate, not 0.5
            "tokens": {"input": 500000, "cached": 0, "output": 0},
            "now": "2026-09-07T02:00:00Z",
            "expected": 0.5 * 1.0,
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
        "a_fast_mode_session_prices_the_premium_rates": {
            "entry": FAST,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T02:00:00Z",
            "mode": "fast",
            # the override replaces input and output; the fixture carries no
            # cache_read axis at all, so the cached count prices at the
            # EFFECTIVE input rate — the override's 10.0, not the base 5.0
            "expected": 1.0 * 10.0 + 0.2 * 10.0 + 0.05 * 50.0,
        },
        "a_standard_session_keeps_the_base_rates": {
            "entry": FAST,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T02:00:00Z",
            # no mode: the mode override does not match, the base prices it
            "expected": 1.0 * 5.0 + 0.2 * 5.0 + 0.05 * 25.0,
        },
        "an_openai_batch_session_prices_the_pane_cells": {
            "entry": BATCH,
            "day": "2026-09-15",
            "tokens": SESSION,
            "now": "2026-09-07T02:00:00Z",
            "mode": "batch",
            # the batch override replaces input, cache_read and output; the
            # image axes the session never uses ride the entry unpriced by
            # the walk
            "expected": 1.0 * 2.5 + 0.2 * 0.625 + 0.05 * 15.0,
        },
        "an_openai_standard_session_keeps_the_base_rates": {
            "entry": BATCH,
            "day": "2026-09-15",
            "tokens": SESSION,
            "now": "2026-09-07T02:00:00Z",
            "expected": 1.0 * 5.0 + 0.2 * 1.25 + 0.05 * 30.0,
        },
        "a_batch_selection_on_a_model_without_a_batch_override_prices_the_base": {
            "entry": FAST,
            "day": "2026-09-07",
            "tokens": SESSION,
            "now": "2026-09-07T02:00:00Z",
            "mode": "batch",
            # the model carries a fast override but no batch one: no entry
            # matches a batch session, so the base rates price it — the same
            # walk that leaves a non-anthropic model's fast selection at base
            "expected": 1.0 * 5.0 + 0.2 * 5.0 + 0.05 * 25.0,
        },
        "a_modality_entry_is_not_chat_priced": {
            "entry": MODALITY,
            "day": "2026-08-01",
            "tokens": SESSION,
            "now": "2026-08-01T02:00:00Z",
            # the row prices image output; a token session over its text
            # axes must never count, since its rates are not chat rates
            "expected": None,
        },
    }


FRAGMENT = (
    "#q=fixture%20one&sort=input&dir=desc&sel=fixture%2Fm1,fixture%2Fm2"
    "&calc=1000|200|30&day=2026-09-07&rate=0.5&mode=fast"
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
            "mode": spec.get("mode", ""),
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


# the mode key's own outcomes, each pinned against a ctx pair: a match, the
# standard session's empty string, a different mode, an empty when.mode (a
# truthiness check would let it through; the comparison must not), and a when
# with no mode key at all (which a mode-ful session still prices under)
_MATCH_CASES = [
    ({"mode": "fast"}, {"mode": "fast"}, True),
    ({"mode": "fast"}, {"mode": ""}, False),
    ({"mode": "fast"}, {"mode": "turbo"}, False),
    ({"mode": ""}, {"mode": "fast"}, False),
    ({"days": ["monday"]}, {"mode": "fast", "weekday": "monday"}, True),
    (None, {"mode": "fast"}, True),
]


def test_when_matches_on_the_mode_key(tmp_path):
    """The mode comparison as its own unit: the price walk above only reaches
    it through a whole session, so a false on the wrong pair would read as a
    rate mismatch rather than a condition mismatch."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "matches": [{"when": when, "ctx": ctx} for when, ctx, _ in _MATCH_CASES],
        },
    )
    assert result["matches"] == [expected for _, _, expected in _MATCH_CASES]


def test_the_chart_draws_one_point_per_interval(tmp_path):
    """A two-row chain is two prices, so the line steps twice: once at each
    interval's own start, at that interval's rate for the chosen axis."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "chart": [
                {"entry": CHAIN, "axis": "input"},
                {"entry": CHAIN, "axis": "output"},
            ],
        },
    )
    assert result["chart"][0] == {
        "runs": [
            {
                "points": [
                    {"date": "2026-08-01", "value": 2.0},
                    {"date": "2026-10-01", "value": 1.0},
                ],
                "end": None,
            }
        ],
        "removed": False,
    }
    assert result["chart"][1] == {
        "runs": [
            {
                "points": [
                    {"date": "2026-08-01", "value": 8.0},
                    {"date": "2026-10-01", "value": 4.0},
                ],
                "end": None,
            }
        ],
        "removed": False,
    }


def test_the_chart_collapses_an_inverted_pair_to_one_point(tmp_path):
    """The clamped interval never applied, so the pair draws one price: the one
    the model was actually charged, at the surviving interval's start."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "chart": [
                {"entry": INVERTED, "axis": "input"},
            ],
        },
    )
    assert result["chart"][0] == {
        "runs": [{"points": [{"date": "2026-09-01", "value": 3.0}], "end": None}],
        "removed": False,
    }


def test_the_chart_ends_the_line_at_a_removal(tmp_path):
    """A removed model keeps the prices it held and stops at the removal's own
    start: the removal row carries a copied rate that was never charged."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "chart": [
                {"entry": REMOVED, "axis": "input"},
            ],
        },
    )
    assert result["chart"][0] == {
        "runs": [{"points": [{"date": "2026-08-01", "value": 1.0}], "end": "2026-08-05"}],
        "removed": True,
    }


def test_the_chart_ends_an_axis_whose_data_runs_out(tmp_path):
    """cache_read is priced only in the first era. The line stops where that
    era does instead of carrying the stale rate over the row that lacks one."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "chart": [
                {"entry": CHAIN, "axis": "cache_read"},
            ],
        },
    )
    assert result["chart"][0] == {
        "runs": [{"points": [{"date": "2026-08-01", "value": 0.25}], "end": "2026-10-01"}],
        "removed": False,
    }


def test_the_chart_keeps_every_era_an_axis_is_priced_in(tmp_path):
    """The axis goes missing for one era and comes back. The chart keeps both
    eras as separate runs: 101 stored keys have such a gap, and a single
    truncated line would drop history the flat entry still carries."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "chart": [
                {"entry": GAPPED, "axis": "input"},
            ],
        },
    )
    assert result["chart"][0] == {
        "runs": [
            {"points": [{"date": "2026-08-01", "value": 2.0}], "end": "2026-09-01"},
            {"points": [{"date": "2026-10-01", "value": 1.0}], "end": None},
        ],
        "removed": False,
    }


def test_the_chart_continues_past_a_closed_removal(tmp_path):
    """A model that came back after a removal is not removed now: the chart
    draws the revival as its own run instead of stopping at the old removal."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "chart": [
                {"entry": REVIVED, "axis": "input"},
            ],
        },
    )
    assert result["chart"][0] == {
        "runs": [
            {"points": [{"date": "2026-08-01", "value": 2.0}], "end": "2026-08-20"},
            {"points": [{"date": "2026-09-10", "value": 1.0}], "end": None},
        ],
        "removed": False,
    }


def test_the_axis_selector_offers_the_chart_axes(tmp_path):
    """The selector's own segments and the module's axis list are one set: a
    segment whose axis the module rejects draws nothing, and every other check
    here would stay green."""
    soup = _soup((_built(tmp_path) / "index.html").read_text(encoding="utf-8"))
    offered = [b["data-axis"] for b in soup.select("#model-detail [data-axis]")]
    result = _node(tmp_path, {"cases": {}, "fragment": ""})
    assert result["axes"] == offered == ["input", "output", "cache_read"]


def test_a_model_fragment_key_restores_and_round_trips(tmp_path):
    """The detail card's model is url state like the rest: a shared link opens
    onto the same card, and the encoder writes the key only when it is set."""
    result = _node(tmp_path, {"cases": {}, "fragment": "#model=deepseek/deepseek-v4-pro"})
    assert result["state"]["model"] == "deepseek/deepseek-v4-pro"
    assert result["encoded"] == "calc=1000000|0|0&model=deepseek/deepseek-v4-pro"


def test_a_flat_history_draws_at_the_top_or_the_middle(tmp_path):
    """The builder's two readings of a price that never moved, which is the
    choice the two callers make: at the top of its own scale it agrees with the
    axis ticks (peak = the value, y = 0), and at the middle it reads as a shape
    the way a sparkline with no axis does. A card chart drawn at 50 reads a 1.32
    price as 0.66 beside its own ticks."""
    run = {"points": [{"date": "2026-08-01", "value": 2.0}], "end": None}
    domain = {"start": "2026-08-01", "finish": "2026-10-01"}
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "polyline": [
                {"run": run, "domain": domain, "peak": 2.0, "flat": False},
                {"run": run, "domain": domain, "peak": 2.0, "flat": True},
            ],
        },
    )
    levels = [[point.split(",")[1] for point in line.split()] for line in result["polyline"]]
    assert levels == [["0", "0"], ["50", "50"]]


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
        "mode": "fast",
        "model": "",
        "peak": False,
    }


def test_a_batch_mode_fragment_restores(tmp_path):
    """The openai batch mode is selectable state exactly like fast: the
    fragment carries it, the restore accepts it, the encoder round-trips it."""
    result = _node(tmp_path, {"cases": {}, "fragment": "#mode=batch"})
    assert result["state"]["mode"] == "batch"
    assert result["encoded"] == "calc=1000000|0|0&mode=batch"


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
        "mode": "",
        "model": "",
        "peak": False,
    }
    assert result["encoded"] == "calc=1000000|0|0"


def test_a_malformed_fragment_falls_back_rather_than_raising(tmp_path):
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": (
                "#sort=nowhere&dir=sideways&calc=1|2&day=yesterday&rate=-4&mode=turbo&sel=%zz"
            ),
        },
    )
    assert result["state"]["sort"] == ""
    assert result["state"]["dir"] == ""
    assert result["state"]["calc"] == {"input": 1000000, "cached": 0, "output": 0}
    assert result["state"]["day"] == ""
    assert result["state"]["rate"] == ""
    # an unoffered mode is malformed input: the standard request takes over
    assert result["state"]["mode"] == ""
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
