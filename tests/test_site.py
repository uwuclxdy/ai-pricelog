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
from datetime import date, timedelta
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
out.grid = (probe.grid ?? []).map(([year, month]) => app.monthGrid(year, month));
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
    // the shipped select's own change event: its value surface is the root's
    // dataset, written before the event fires
    modeBox.dataset.value = value;
    modeBox._listeners.change({ detail: { value } });
    // a fire that changes state pushes, so the last fragment always names the
    // post-fire state; an empty list means the state never left its default
    out.modeChanges[value] = app.decodeState(hashes[hashes.length - 1]).mode;
  }
  delete globalThis.document;
  delete globalThis.window;
}
if (probe.rows) {
  let builtRows = 0;
  /* the stub's own selector machinery: the page's row-click capture listener
     and the day picker walk classes, tags and one attribute through
     closest/querySelector/matches, so the stub answers the single-token forms
     (a class, a tag, an `[attr="value"]`, a comma list of those) the page's
     handlers use */
  const matches = (node, selector) =>
    selector.split(",").some((token) => {
      const part = token.trim();
      const attr = /^\\[([\\w-]+)="([^"]*)"\\]$/.exec(part);
      if (attr) {
        const value = attr[1] === "tabindex" ? node.tabIndex : node.attrs?.[attr[1]];
        return value !== undefined && String(value) === attr[2];
      }
      if (part.startsWith(".")) {
        return (
          typeof node.className === "string" &&
          node.className.split(/\\s+/).includes(part.slice(1))
        );
      }
      return node.tag === part;
    });
  const climb = (node, selector) => {
    for (let at = node; at; at = at.parent) {
      if (matches(at, selector)) return at;
    }
    return null;
  };
  const deepFirst = (node, selector) => {
    for (const child of node.children ?? []) {
      if (matches(child, selector)) return child;
      const hit = deepFirst(child, selector);
      if (hit) return hit;
    }
    return null;
  };
  const make = (tag) => {
    const el = {
      tag, children: [], className: "", textContent: "", hidden: false, value: "", type: "",
      dataset: {}, checked: false, attrs: {}, rects: [{}],
      append(...nodes) {
        for (const node of nodes) {
          if (node && typeof node === "object") node.parent = this;
        }
        this.children.push(...nodes);
      },
      replaceChildren(...nodes) {
        const flat = nodes.flatMap((node) => (node && node.isFragment ? node.children : [node]));
        for (const node of flat) {
          if (node && typeof node === "object") node.parent = this;
        }
        this.children = flat;
      },
      setAttribute(name, value) { this.attrs[name] = String(value); },
      getAttribute(name) { return this.attrs[name] ?? null; },
      getClientRects() { return this.rects; },
      getBoundingClientRect() { return { top: 0, left: 0 }; },
      scrollIntoView() {},
      style: { setProperty() {} },
      closest(selector) { return climb(this, selector); },
      matches(selector) { return matches(this, selector); },
      contains(node) {
        for (let at = node; at; at = at.parent) {
          if (at === this) return true;
        }
        return false;
      },
      focus() { globalThis.document.activeElement = this; },
      querySelector(selector) { return deepFirst(this, selector); },
      querySelectorAll() { return []; },
      addEventListener(name, fn, options) {
        (this._listeners || (this._listeners = {}))[name] = fn;
        if (options === true || (options && options.capture === true)) {
          (this._captures || (this._captures = {}))[name] = true;
        }
      },
    };
    const has = (name) => el.className.split(/\\s+/).includes(name);
    el.classList = {
      contains: has,
      add(...names) {
        for (const name of names) {
          if (!has(name)) el.className = `${el.className} ${name}`.trim();
        }
      },
      remove(...names) {
        el.className = el.className.split(/\\s+/).filter((n) => n && !names.includes(n)).join(" ");
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
    const match = /\\.th-sort\\[data-sort="(.+)"\\]/.exec(sel);
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
    "calc-day-value", "model-detail", "detail-name", "detail-id", "detail-tags", "detail-empty",
    "detail-body", "detail-close", "detail-ticks-y", "detail-ticks-x", "detail-info",
  ]) elements.set(id, make("input"));
  /* the day picker's skeleton, built only when a probe drives it: the range
     wraps the trigger and the panel, so contains() answers the page's
     focusout and pointerdown reads off the same tree the grid hangs from */
  let picker = null;
  if (probe.rows.picker) {
    const range = make("div");
    const panel = make("div");
    const prev = make("button");
    const next = make("button");
    const month = make("span");
    const grid = make("tbody");
    const today = make("button");
    panel.append(prev, next, month, grid, today);
    panel.hidden = true;
    panel.querySelector = (sel) => ({
      "#calc-day-grid": grid, "#calc-day-month": month, "#calc-day-today": today,
    }[sel] ?? null);
    panel.querySelectorAll = (sel) => (sel === ".daterange-head .btn" ? [prev, next] : []);
    const trigger = elements.get("calc-day");
    range.append(trigger, panel);
    // the open-time flips are arithmetic on these numbers against the
    // window's 1280x800, so a probe places the trigger where it wants a flip
    const rect = probe.rows.triggerRect ?? { top: 100, bottom: 132, left: 100, right: 300 };
    trigger.getBoundingClientRect = () => rect;
    panel.offsetHeight = 320;
    panel.offsetWidth = 300;
    elements.set("calc-day-range", range);
    elements.set("calc-day-panel", panel);
    picker = { range, panel, prev, next, month, grid, today };
  }
  /* the picker reads the wall clock for today and schedules its exit on a
     timer: a pinned instant makes today a fixture value, and a held timer
     queue lets a probe read the panel between the close and the hide */
  const RealDate = Date;
  const realTimers = { set: globalThis.setTimeout, clear: globalThis.clearTimeout };
  const timers = new Map();
  if (probe.rows.now) {
    const pinned = RealDate.parse(probe.rows.now);
    globalThis.Date = class extends RealDate {
      constructor(...args) { super(...(args.length > 0 ? args : [pinned])); }
      static now() { return pinned; }
    };
  }
  if (picker) {
    let timerId = 0;
    globalThis.setTimeout = (fn, ms) => {
      timerId += 1;
      timers.set(timerId, { fn, ms });
      return timerId;
    };
    globalThis.clearTimeout = (id) => { timers.delete(id); };
    // only the panel wears the exit costume, so a hide timed off any other
    // element reads the 0s every unanimated element computes
    globalThis.getComputedStyle = (element) => ({
      animationDuration: element === picker.panel ? probe.rows.exitDuration : "0s",
    });
  }
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
  const documentListeners = {};
  globalThis.document = {
    documentElement: { dataset: {} },
    activeElement: null,
    getElementById: (id) => elements.get(id) ?? null,
    createElement: (tag) => {
      if (tag === "tr") builtRows += 1;
      return make(tag);
    },
    createTextNode: (text) => ({ textContent: String(text), children: [] }),
    createDocumentFragment: () => ({ ...make("fragment"), isFragment: true }),
    addEventListener(name, fn) { documentListeners[name] = fn; },
  };
  globalThis.window = {
    location: { hash: probe.rows.hash },
    history: { replaceState(_state, _title, url) { hashes.push(String(url)); } },
    addEventListener(name, fn) { windowListeners[name] = fn; },
    innerWidth: 1280,
    innerHeight: 800,
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
  const rowClicks = [];
  if (probe.rows.rowClicks) {
    for (const spec of probe.rows.rowClicks) {
      const row = body.children.find(
        (tr) => tr.children[1]?.children?.[0]?.dataset?.key === spec.key,
      );
      if (!row) throw new Error(`rowClicks names no built row: ${spec.key}`);
      let cell;
      if (spec.cell === "button") cell = row.children[1]?.children?.[0];
      else if (spec.cell === "select") cell = row.children[0];
      else if (spec.cell === "rate") {
        cell = row.children.find((c) => c.classList?.contains("num-col"));
      } else throw new Error(`rowClicks names no cell: ${spec.cell}`);
      const stopped = [];
      if (cell && wrap._listeners?.click) {
        wrap._listeners.click({ target: cell, stopPropagation: () => stopped.push(1) });
      }
      rowClicks.push({
        stopped: stopped.length,
        url: hashes[hashes.length - 1] ?? probe.rows.hash,
        card: cardSnapshot(),
      });
    }
  }
  /* the picker's own state machine, one action at a time, each answered by a
     snapshot of what a reader and a screen reader see: `trigger`, `prev`,
     `next`, `today` and `flush` (fire the held exit timers) take no argument;
     `key:<key>` presses a key on the focused element, `focus:<prev|next|today>`
     moves focus onto that panel button, `day:<date>` clicks that grid cell,
     `gridgap` clicks the grid off any cell, `pointerdown:<place>` presses the
     pointer and `focusout:<place>` moves focus, where a place is `inside` (the
     prev button), `outside` (a focusable input), `page` (an unfocusable block),
     for pointerdown only `still` (the page block, pressed without moving
     focus) and for focusout only `nowhere` (focus leaving the document). a
     press runs in Chromium's order: pointerdown, then focus moves to the
     pressed element when it is focusable and to the body when it is not, and a
     move off a focused element inside the picker fires the picker's focusout
     with the new focus as related target. a key step records whether the
     handler prevented the browser default; the stub performs no default.
     residuals the stub cannot see: native button activation (Enter or Space on
     a nav button clicking it), a default action itself (page scroll), and a
     focusout an engine may fire when a redraw removes the focused cell */
  const pickerSteps = [];
  if (picker) {
    const trigger = elements.get("calc-day");
    const outsider = elements.get("q");
    const dayButtons = () =>
      picker.grid.children.flatMap((tr) => tr.children.map((td) => td.children[0]));
    const daysWhere = (test) => dayButtons().filter(test).map((b) => b.dataset.day);
    const named = new Map([
      [trigger, "trigger"], [outsider, "outside"],
      [picker.prev, "prev"], [picker.next, "next"], [picker.today, "today"],
    ]);
    const snapshot = (action, prevented) => {
      const active = globalThis.document.activeElement;
      return {
        prevented,
        session_note: elements.get("session-note").textContent,
        up: picker.range.classList.contains("daterange-up"),
        end: picker.range.classList.contains("daterange-end"),
        action,
        open: picker.range.classList.contains("open"),
        closing: picker.range.classList.contains("closing"),
        hidden: picker.panel.hidden === true,
        expanded: trigger.attrs["aria-expanded"] ?? null,
        month: picker.month.textContent,
        days: daysWhere(() => true),
        outside: daysWhere((b) => b.classList.contains("is-outside")),
        current: daysWhere((b) => b.attrs["aria-current"] === "date"),
        picked: daysWhere(
          (b) => b.classList.contains("is-start") && b.classList.contains("is-end")),
        tabbable: daysWhere((b) => b.tabIndex === 0),
        focus: named.get(active) ?? active?.dataset?.day ?? null,
        timers: [...timers.values()].map((timer) => timer.ms),
        url: hashes[hashes.length - 1] ?? probe.rows.hash,
        day_value: elements.get("calc-day-value").textContent,
        day_empty: elements.get("calc-day-value").classList.contains("is-empty"),
      };
    };
    const page = elements.get("session-wrap");
    const relative = (where) => {
      if (where === "inside") return picker.prev;
      if (where === "outside") return outsider;
      if (where === "page" || where === "still") return page;
      throw new Error(`picker names no place: ${where}`);
    };
    const focusable = (element) => element === picker.prev || element === outsider;
    const focusOn = (element) => { globalThis.document.activeElement = element; };
    const panelButton = (name) => {
      const button = { prev: picker.prev, next: picker.next, today: picker.today }[name];
      if (!button) throw new Error(`picker names no panel button: ${name}`);
      return button;
    };
    for (const action of probe.rows.picker) {
      const [verb, arg] = action.split(/:(.*)/s);
      let prevented = null;
      if (verb === "trigger") {
        focusOn(trigger);
        trigger._listeners.click({});
      } else if (verb === "prev" || verb === "next" || verb === "today") {
        panelButton(verb)._listeners.click({});
      } else if (verb === "flush") {
        const due = [...timers.values()];
        timers.clear();
        for (const timer of due) timer.fn();
      } else if (verb === "focus") {
        focusOn(panelButton(arg));
      } else if (verb === "key") {
        // a key lands on the focused element and bubbles; the panel hears it
        // only while focus sits inside it
        const active = globalThis.document.activeElement;
        prevented = false;
        if (picker.panel.contains(active)) {
          picker.panel._listeners.keydown({
            key: arg, target: active, preventDefault() { prevented = true; },
          });
        }
      } else if (verb === "day") {
        const button = dayButtons().find((b) => b.dataset.day === arg);
        if (!button) throw new Error(`picker grid draws no ${arg}`);
        picker.grid._listeners.click({ target: button });
      } else if (verb === "gridgap") {
        picker.grid._listeners.click({ target: picker.grid.children[0] });
      } else if (verb === "pointerdown") {
        const target = relative(arg);
        const left = globalThis.document.activeElement;
        documentListeners.pointerdown({ target });
        // `still` is a press that moves no focus at all (WebKit's clicked
        // button), which leaves the pointerdown listener as the only close path
        const landed = arg === "still" ? left : focusable(target) ? target : null;
        if (landed !== left) {
          focusOn(landed);
          if (picker.range.contains(left)) {
            picker.range._listeners.focusout({ relatedTarget: landed });
          }
        }
      } else if (verb === "focusout") {
        const target = arg === "nowhere" ? null : relative(arg);
        focusOn(target);
        picker.range._listeners.focusout({ relatedTarget: target });
      } else throw new Error(`picker names no action: ${action}`);
      pickerSteps.push(snapshot(action, prevented));
    }
  }
  globalThis.Date = RealDate;
  globalThis.setTimeout = realTimers.set;
  globalThis.clearTimeout = realTimers.clear;
  delete globalThis.getComputedStyle;
  const hasBox = (node) =>
    node.type === "checkbox"
    || (Array.isArray(node.children) && node.children.some(hasBox));
  out.rows = {
    picker: pickerSteps,
    "built_on_init": builtOnInit,
    "built_after_steps": builtRows,
    rowclick_capture: wrap._captures?.click === true,
    // the fragment the page ends on: a rewritten one when it dropped a key,
    // else the one it loaded
    url: hashes[hashes.length - 1] ?? probe.rows.hash,
    toggle_states: toggleStates,
    card,
    axis_card: axisCard,
    rowClicks,
    day_value: elements.get("calc-day-value").textContent,
    day_empty: elements.get("calc-day-value").classList.contains("is-empty"),
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


def _monday_grid(year: int, month: int) -> list[str]:
    """The whole Monday-first weeks a month's calendar covers, 0-based month."""
    first = date(year, month + 1, 1)
    start = first - timedelta(days=first.weekday())
    following = date(year + (month + 1) // 12, (month + 1) % 12 + 1, 1)
    length = (first.weekday() + (following - first).days + 6) // 7 * 7
    return [(start + timedelta(days=index)).isoformat() for index in range(length)]


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


def test_a_rate_cell_click_opens_the_card_and_the_compare_cell_passes_through(tmp_path):
    """One meaning per target, the page's half of it: the row click registers
    in the capture phase, a click that missed a control opens the model's card
    and stops there, and the compare cell passes through to whatever handles
    it below. That the shipped controller's bubble handler is the one it
    passes to is the browser leg's business, not a stub's."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {
                "island": {"entries": [ENTRY, PLAIN]},
                "hash": "",
                "rowClicks": [
                    {"key": "fixture/m1", "cell": "button"},
                    {"key": "fixture/m1", "cell": "rate"},
                    {"key": "fixture/m1", "cell": "select"},
                ],
            },
        },
    )
    assert result["rows"]["rowclick_capture"] is True
    button, rate, select = result["rows"]["rowClicks"]
    assert button["stopped"] == 0
    assert button["card"]["name"] == ""
    assert rate["stopped"] == 1
    assert rate["card"]["name"] == "Fixture One"
    assert "model=fixture/m1" in rate["url"]
    assert select["stopped"] == 0
    assert select["url"] == rate["url"]
    assert select["card"]["name"] == "Fixture One"


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
        ("cache_read", "cached input", "false", "btn btn-secondary"),
    ]
    # the card's axis label and the table's column label name one rate one way:
    # both literals are reader-facing, and neither alone catches a reword
    sort = soup.select_one('#models-table .th-sort[data-sort="cache_read"]')
    assert sort is not None and sort.get_text(strip=True) == "cached input"
    # the no-js floor's header is the third copy of that label
    static = [th.get_text(strip=True) for th in soup.select("#models-static thead th")]
    assert static[static.index("cached input")] == "cached input"
    line = card.select_one(".chart .chart-line")
    assert line is not None and line.get("points") == ""


def test_the_header_names_the_page(tmp_path):
    """The h1 names the page instead of asserting a claim about it, and the
    meta and noscript lede stay short; pinned by equality so a reword is a
    test edit."""
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    header = soup.select_one(".page-header")
    assert header.select_one(".label").get_text(strip=True) == "genai pricing index"
    assert header.select_one("h1.page-title").get_text(strip=True) == "ai model prices"
    export = json.loads((out / "flat-v3.json").read_text(encoding="utf-8"))
    meta = [item.get_text(" ", strip=True) for item in header.select(".page-meta-item")]
    assert meta == [
        f"updated {header.select_one('.page-meta time')['datetime']}",
        f"{len(export['entries'])} models",
        f"{len({entry['source'] for entry in export['entries']})} sources",
    ]
    lede = soup.select_one("noscript .section-lede").get_text(" ", strip=True)
    assert lede == (
        "search, sorting and the comparison need javascript. every model is listed below."
    )


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
    """The calculator's mode control is the shipped select — standard first and
    selected, then every request mode the index carries (fast, the anthropic
    premium; batch, the openai image discount) — never a native `<select>`.

    The option set is pinned whole over the menu's own role=option rows.
    """
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    root = soup.select_one("#calc-mode")
    assert root is not None and "select" in root.get("class", [])
    trigger = root.select_one(".select-trigger")
    assert trigger is not None and trigger.name == "button"
    assert trigger.get("aria-labelledby") == "calc-mode-label calc-mode-value"
    label = soup.select_one("#calc-mode-label")
    assert label is not None and label.get_text(strip=True) == "request mode"
    value = soup.select_one("#calc-mode-value")
    assert value is not None and value.get_text(strip=True) == "standard"
    options = [
        (option.name, option.get_text(strip=True), option.get("aria-selected"))
        for option in root.select('[role="option"]')
    ]
    # the shipped rows are divs: the trigger keeps DOM focus for the menu's
    # whole life, so an option is a tab stop the keyboard model never had
    assert options == [
        ("div", "standard", "true"),
        ("div", "fast", "false"),
        ("div", "batch", "false"),
    ]


def test_the_mode_gate_accepts_every_option_the_select_offers(tmp_path):
    """The change handler and the fragment restore both reset a mode the
    script's gate does not carry, so a mode dropped from `MODES` silently
    unselects it for every interactive user while every gate stays green.

    Driven over the served page's own option list through the real init run:
    the select's change event carries each offered label, and the standard
    label is the empty, mode-less request.
    """
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    root = soup.select_one("#calc-mode")
    labels = [option.get_text(strip=True) for option in root.select('[role="option"]')]
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "#mode=no-such-mode",
            "modeChanges": labels + ["no-such-mode"],
        },
    )
    # the script's gate list and the select's labels are two lists that must
    # stay one set once the standard label's empty value is accounted for
    assert sorted(label for label in labels if label != "standard") == sorted(result["modes"])
    for label in labels:
        expected = "" if label == "standard" else label
        assert result["modeChanges"][label] == expected, f"mode {label!r} reset by the gate"
    assert result["modeChanges"]["no-such-mode"] == ""
    # the fragment restore applies the same gate: a crafted fragment naming a
    # mode neither list carries must land on standard, not on a ghost mode
    assert result["state"]["mode"] == ""


def test_the_page_carries_no_native_select_or_date_input(tmp_path):
    """The native select's popup is OS chrome over the ring cursor, and a
    native date input paints the platform calendar the same way."""
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    assert soup.select("select") == []
    assert soup.select('input[type="date"]') == []


def test_the_day_control_is_the_shipped_date_picker(tmp_path):
    """The calculator's priced-on field is the daterange component: a select
    trigger over a dialog panel, no UA calendar."""
    out = _built(tmp_path)
    soup = _soup((out / "index.html").read_text(encoding="utf-8"))
    root = soup.select_one("#calc-day-range")
    assert root is not None
    assert {"select", "daterange"} <= set(root.get("class", []))
    trigger = root.select_one(".select-trigger")
    assert trigger is not None and trigger.name == "button"
    assert trigger.get("aria-haspopup") == "dialog"
    assert trigger.get("aria-expanded") == "false"
    assert trigger.get("aria-labelledby") == "calc-day-label calc-day-value"
    value = soup.select_one("#calc-day-value")
    assert value is not None and value.get_text(strip=True) == "today"
    assert "is-empty" in value.get("class", [])
    panel = root.select_one(".daterange-panel")
    assert panel is not None and panel.has_attr("hidden")
    assert panel.get("role") == "dialog"
    assert [th.get_text(strip=True) for th in panel.select(".daterange-dow")] == [
        "mo",
        "tu",
        "we",
        "th",
        "fr",
        "sa",
        "su",
    ]
    assert panel.select_one("#calc-day-grid") is not None
    assert panel.select_one("#calc-day-month") is not None
    assert panel.select_one("#calc-day-today").get_text(strip=True) == "today"


def test_an_impossible_day_fragment_falls_back_to_today(tmp_path):
    """The day the picker consumes must be a real calendar date: a link naming
    the 30th of february prices nothing and would open the panel on a month it
    cannot draw."""
    bad = _node(tmp_path, {"cases": {}, "fragment": "#day=2026-02-30"})
    assert bad["state"]["day"] == ""
    real = _node(tmp_path, {"cases": {}, "fragment": "#day=2026-02-28"})
    assert real["state"]["day"] == "2026-02-28"


def test_the_month_grid_is_monday_first_whole_weeks(tmp_path):
    """The picker's calendar covers whole weeks from Monday, adjacent months
    included, so every row is seven cells and no month starts mid-row."""
    result = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "grid": [[2026, 8], [2026, 1], [2024, 1], [2026, 7], [2026, 11]],
        },
    )
    assert result["grid"] == [
        _monday_grid(2026, 8),
        _monday_grid(2026, 1),
        _monday_grid(2024, 1),
        _monday_grid(2026, 7),
        _monday_grid(2026, 11),
    ]


def test_a_day_fragment_reads_on_the_trigger(tmp_path):
    """A `day=` link names its date on the control; the empty default reads
    "today", the day the calculator falls back to."""
    on = _node(
        tmp_path,
        {
            "cases": {},
            "fragment": "",
            "rows": {"island": {"entries": []}, "hash": "#day=2026-09-07"},
        },
    )
    assert on["rows"]["day_value"] == "2026-09-07"
    assert on["rows"]["day_empty"] is False
    off = _node(
        tmp_path,
        {"cases": {}, "fragment": "", "rows": {"island": {"entries": []}, "hash": ""}},
    )
    assert off["rows"]["day_value"] == "today"
    assert off["rows"]["day_empty"] is True


# the picker probes pin the wall clock to a friday near a month edge, so a two
# day walk crosses into march and today's cell sits in both months' grids
PICKER_NOW = "2026-02-27T12:00:00Z"
PICKER_TODAY = PICKER_NOW[:10]
# a fixture duration, not the page's token: any value off the stub's 0s default
# proves the hide is timed off the panel, and 0.25 multiplies to 250 with no
# float residue, so the scheduled hide is 250 + the page's 20ms slack
PICKER_EXIT = "0.25s"
PICKER_HIDE_MS = 270


def _picker(
    tmp_path: Path,
    actions: list[str],
    hash_: str = "",
    trigger_rect: dict[str, int] | None = None,
) -> list[dict[str, object]]:
    rows: dict[str, object] = {
        "island": {"entries": []},
        "hash": hash_,
        "now": PICKER_NOW,
        "exitDuration": PICKER_EXIT,
        "picker": actions,
    }
    if trigger_rect is not None:
        rows["triggerRect"] = trigger_rect
    result = _node(tmp_path, {"cases": {}, "fragment": "", "rows": rows})
    steps = result["rows"]["picker"]
    assert [step["action"] for step in steps] == actions
    return steps


def _outside(grid: list[str], year: int, month: int) -> list[str]:
    prefix = f"{year}-{month + 1:02d}-"
    return [day for day in grid if not day.startswith(prefix)]


def test_the_day_picker_opens_on_today_and_walks_days_across_the_month_edge(tmp_path):
    """The trigger opens the panel on today's month with today's cell focused;
    the arrows walk a day or a week and redraw the month the anchor lands in."""
    steps = _picker(
        tmp_path,
        [
            "trigger",
            "key:ArrowRight",
            "key:ArrowRight",
            "key:ArrowLeft",
            "key:ArrowDown",
            "key:ArrowUp",
        ],
    )
    february = _monday_grid(2026, 1)
    march = _monday_grid(2026, 2)
    opened = steps[0]
    assert opened["open"] is True
    assert opened["closing"] is False
    assert opened["hidden"] is False
    assert opened["expanded"] == "true"
    assert opened["month"] == "february 2026"
    assert opened["days"] == february
    assert opened["outside"] == _outside(february, 2026, 1)
    assert opened["current"] == [PICKER_TODAY]
    assert opened["tabbable"] == [PICKER_TODAY]
    assert opened["focus"] == PICKER_TODAY
    assert opened["picked"] == []
    # a trigger with room below and to the right opens the panel unflipped
    assert (opened["up"], opened["end"]) == (False, False)

    walk = [(step["focus"], step["month"]) for step in steps[1:]]
    assert walk == [
        ("2026-02-28", "february 2026"),
        ("2026-03-01", "march 2026"),
        ("2026-02-28", "february 2026"),
        ("2026-03-07", "march 2026"),
        ("2026-02-28", "february 2026"),
    ]
    # the roving tab stop follows the focus: exactly one tabbable cell
    assert [step["tabbable"] for step in steps[1:]] == [[focus] for focus, _ in walk]
    in_march = steps[2]
    assert in_march["days"] == march
    assert in_march["outside"] == _outside(march, 2026, 2)
    # today is a february day the march grid still draws, and keeps its mark
    assert in_march["current"] == [PICKER_TODAY]
    # every walk key keeps the browser from scrolling the page under the panel
    assert [step["prevented"] for step in steps] == [None, True, True, True, True, True]
    # walking never picks: the panel stays open and the state stays empty
    assert all(step["open"] for step in steps)
    assert all(step["day_value"] == "today" for step in steps)


def test_the_day_picker_opens_on_the_picked_month_and_clamps_month_steps(tmp_path):
    """A `day=` fragment opens the panel on its own month with its cell marked;
    a month step keeps the date, clamped to the target month's last day."""
    steps = _picker(
        tmp_path,
        ["trigger", "key:PageUp", "key:PageDown", "next", "prev", "prev"],
        hash_="#day=2026-03-31",
    )
    opened = steps[0]
    assert opened["month"] == "march 2026"
    assert opened["days"] == _monday_grid(2026, 2)
    assert opened["picked"] == ["2026-03-31"]
    assert opened["tabbable"] == ["2026-03-31"]
    assert opened["focus"] == "2026-03-31"
    assert opened["day_value"] == "2026-03-31"

    walk = [(step["focus"], step["month"]) for step in steps[1:]]
    assert walk == [
        ("2026-02-28", "february 2026"),
        ("2026-03-28", "march 2026"),
        ("2026-04-28", "april 2026"),
        ("2026-03-28", "march 2026"),
        ("2026-02-28", "february 2026"),
    ]
    assert steps[3]["days"] == _monday_grid(2026, 3)
    # PageUp/PageDown would scroll the page a screen without the prevent
    assert [step["prevented"] for step in steps] == [None, True, True, None, None, None]
    # navigating draws other months but never moves the picked day: april's
    # grid opens on monday 2026-03-30, so it still draws the picked 31st
    assert [step["picked"] for step in steps[1:]] == [
        [],
        ["2026-03-31"],
        ["2026-03-31"],
        ["2026-03-31"],
        [],
    ]
    assert all(step["open"] and step["day_value"] == "2026-03-31" for step in steps)


def test_escape_closes_the_day_picker_and_the_panel_hides_after_its_exit(tmp_path):
    """Escape runs the exit costume: the panel stays drawn until the timer read
    off its animation fires, focus returns to the trigger, and a reopen during
    the exit cancels the pending hide."""
    steps = _picker(
        tmp_path, ["trigger", "key:Escape", "flush", "trigger", "key:Escape", "trigger"]
    )
    closing = steps[1]
    assert closing["open"] is False
    assert closing["closing"] is True
    assert closing["hidden"] is False
    assert closing["expanded"] == "false"
    assert closing["focus"] == "trigger"
    assert closing["timers"] == [PICKER_HIDE_MS]
    assert (closing["prevented"], steps[4]["prevented"]) == (True, True)

    hidden = steps[2]
    assert (hidden["open"], hidden["closing"], hidden["hidden"], hidden["timers"]) == (
        False,
        False,
        True,
        [],
    )

    reopened = steps[5]
    assert (reopened["open"], reopened["closing"], reopened["hidden"]) == (True, False, False)
    assert reopened["expanded"] == "true"
    # the hide queued by the second escape must not fire on the reopened panel
    assert reopened["timers"] == []
    assert reopened["focus"] == PICKER_TODAY


def test_a_picked_day_lands_in_the_fragment_and_reopens_marked(tmp_path):
    """A cell click and an Enter on the focused cell both write the day into
    state, the trigger label and the fragment, then close onto the trigger; the
    next open lands on the picked day."""
    steps = _picker(
        tmp_path,
        [
            "trigger",
            "day:2026-02-10",
            "flush",
            "trigger",
            "key:ArrowRight",
            "key:Enter",
            "flush",
            "trigger",
        ],
    )
    assert steps[0]["session_note"] == "priced at 12:00 UTC today"
    clicked = steps[1]
    assert (clicked["open"], clicked["closing"], clicked["focus"]) == (False, True, "trigger")
    assert clicked["day_value"] == "2026-02-10"
    assert clicked["day_empty"] is False
    assert re.search(r"(^|[#&])day=2026-02-10($|&)", clicked["url"])
    # the session reprices on the picked day, not only its label and link
    assert clicked["session_note"] == "priced at 12:00 UTC on 2026-02-10"

    reopened = steps[3]
    assert reopened["picked"] == ["2026-02-10"]
    assert reopened["tabbable"] == ["2026-02-10"]
    assert reopened["focus"] == "2026-02-10"
    # today keeps its own mark beside the picked day
    assert reopened["current"] == [PICKER_TODAY]

    entered = steps[5]
    assert (entered["open"], entered["focus"]) == (False, "trigger")
    assert (steps[4]["prevented"], entered["prevented"]) == (True, True)
    assert entered["day_value"] == "2026-02-11"
    assert re.search(r"(^|[#&])day=2026-02-11($|&)", entered["url"])
    assert entered["session_note"] == "priced at 12:00 UTC on 2026-02-11"
    assert steps[7]["picked"] == ["2026-02-11"]


def test_enter_and_space_pick_only_from_a_day_cell(tmp_path):
    """Enter or Space on a focused nav or today button bubbles to the panel's
    key handler and must leave the pick to the button itself; on a day cell
    either key picks the focused day."""
    steps = _picker(
        tmp_path,
        ["trigger", "focus:next", "key:Enter", "focus:today", "key: ", "key:ArrowRight", "key: "],
    )
    for step in steps[2:6]:
        assert step["open"] is True
        assert step["day_value"] == "today"
        assert "day=" not in step["url"]
    assert [step["focus"] for step in steps[1:6]] == [
        "next",
        "next",
        "today",
        "today",
        "2026-02-28",
    ]
    spaced = steps[6]
    assert (spaced["open"], spaced["focus"]) == (False, "trigger")
    assert spaced["day_value"] == "2026-02-28"
    assert re.search(r"(^|[#&])day=2026-02-28($|&)", spaced["url"])
    # a key on a nav button keeps its default, which is the button's own click;
    # on a day cell the handler takes the key over
    assert [step["prevented"] for step in steps[2::2]] == [False, False, True]
    assert steps[5]["prevented"] is True


@pytest.mark.parametrize(
    ("rect", "flips"),
    [
        # 68px below, under the 320px panel plus 8px, with 700px above; the
        # 300px panel from x=1200 overruns the 1280px width
        ({"top": 700, "bottom": 732, "left": 1100, "right": 1200}, (True, True)),
        # 240px below is too little, but 150px above is less: stay down
        ({"top": 150, "bottom": 560, "left": 100, "right": 300}, (False, False)),
        # 324px below fits the panel but not its 8px gap; the right edge, not
        # the left, decides the overrun: 1000 + 300 > 1280 while 900 + 300 is not
        ({"top": 444, "bottom": 476, "left": 900, "right": 1000}, (True, True)),
        # 300px both above and below, too little for the panel: a tie stays down
        ({"top": 300, "bottom": 500, "left": 100, "right": 300}, (False, False)),
        # exactly 328px below and exactly 1280px wide: both fit
        ({"top": 440, "bottom": 472, "left": 880, "right": 980}, (False, False)),
    ],
)
def test_the_day_picker_flips_up_and_to_the_end_near_the_viewport_edges(tmp_path, rect, flips):
    """The panel opens above the trigger when the room below cannot hold it plus
    its gap and the room above is larger, and aligns to the trigger's end when
    it would overrun the window's right edge (window 1280x800, panel 300x320)."""
    steps = _picker(tmp_path, ["trigger"], trigger_rect=rect)
    assert steps[0]["open"] is True
    assert (steps[0]["up"], steps[0]["end"]) == flips


def test_the_today_foot_clears_the_picked_day(tmp_path):
    """Today is the calculator's empty default, so the foot clears the state
    rather than writing today's date: the label reads "today" and the fragment
    drops its `day=` key."""
    steps = _picker(tmp_path, ["trigger", "today", "flush", "trigger"], hash_="#day=2026-03-31")
    assert steps[0]["day_value"] == "2026-03-31"
    assert steps[0]["session_note"] == "priced at 12:00 UTC on 2026-03-31"
    cleared = steps[1]
    assert (cleared["open"], cleared["focus"]) == (False, "trigger")
    assert cleared["day_value"] == "today"
    assert cleared["day_empty"] is True
    assert "day=" not in cleared["url"]
    assert cleared["session_note"] == "priced at 12:00 UTC today"
    reopened = steps[3]
    assert reopened["month"] == "february 2026"
    assert reopened["picked"] == []
    assert reopened["focus"] == PICKER_TODAY


def test_the_day_picker_closes_on_an_outside_click_or_focus_and_on_a_trigger_toggle(tmp_path):
    """A pointer or focus move inside the picker, a grid click between cells
    included, keeps it open; one outside closes it and leaves focus where the
    reader put it; a press outside an already closed picker changes nothing;
    and the trigger toggles it shut."""
    steps = _picker(
        tmp_path,
        [
            "trigger",
            "gridgap",
            "pointerdown:inside",
            "pointerdown:outside",
            "flush",
            "pointerdown:outside",
            "trigger",
            "focusout:inside",
            "focusout:outside",
            "trigger",
            "trigger",
        ],
    )
    opened, closed = (True, "true"), (False, "false")
    assert [(step["open"], step["expanded"]) for step in steps] == [
        opened,
        opened,
        opened,
        closed,
        closed,
        closed,
        opened,
        opened,
        closed,
        opened,
        closed,
    ]
    assert [step["focus"] for step in steps] == [
        PICKER_TODAY,
        PICKER_TODAY,
        "prev",
        "outside",
        "outside",
        "outside",
        PICKER_TODAY,
        "prev",
        "outside",
        PICKER_TODAY,
        "trigger",
    ]
    # the second outside press lands on a hidden picker: no exit replays
    settled = steps[5]
    assert (settled["closing"], settled["hidden"], settled["timers"]) == (False, True, [])
    assert all(step["day_value"] == "today" for step in steps)


def test_the_day_picker_closes_when_focus_leaves_the_page_or_the_page_is_pressed(tmp_path):
    """Focus leaving the document (a focusout with no related target) closes the
    picker; a press on an unfocusable stretch of the page closes it too and
    sends focus to the body, and the exit then hides the panel. A press that
    moves no focus (a button WebKit leaves unfocused) fires no
    focusout, so the page-wide press listener alone has to close it."""
    steps = _picker(
        tmp_path,
        [
            "trigger",
            "focusout:nowhere",
            "trigger",
            "pointerdown:page",
            "flush",
            "trigger",
            "pointerdown:still",
        ],
    )
    assert [(step["open"], step["expanded"]) for step in steps] == [
        (True, "true"),
        (False, "false"),
        (True, "true"),
        (False, "false"),
        (False, "false"),
        (True, "true"),
        (False, "false"),
    ]
    assert [step["focus"] for step in steps] == [
        PICKER_TODAY,
        None,
        PICKER_TODAY,
        None,
        None,
        PICKER_TODAY,
        PICKER_TODAY,
    ]
    assert (steps[4]["hidden"], steps[4]["closing"]) == (True, False)
    assert (steps[6]["closing"], steps[6]["timers"]) == (True, [PICKER_HIDE_MS])


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
        ["rate cached input", "0.5"],
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
        ["rate cached input", "0.5"],
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
        ["rate cached input", "0.5"],
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
    assert ["rate cached input", "0.5"] in info


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
