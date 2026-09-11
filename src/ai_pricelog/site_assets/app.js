/* the models page: the pricing rules, the url-fragment state and the renderer.

   Everything above `init` is pure, so the build's node harness can price a
   fixture entry and compare the number against the python side. `init` is the
   only part that needs a document, and it never runs outside a browser.

   The page carries no network call: the table is built from the `flat-data`
   script island, which holds the same bytes the flat export file does. */

const DASH = "–";
const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
/* the session's own axis names against the export's rate axes. a cached input
   prices at `cache_read`, and at `input` when the entry carries no cache axis. */
const AXES = [
  ["input", "input"],
  ["cached", "cache_read"],
  ["output", "output"],
];
const SORT_KEYS = ["name", "vendor", "input", "cache_read", "output"];
const DEFAULT_TOKENS = { input: 1000000, cached: 0, output: 0 };
const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function axisRate(rates, axis) {
  const value = rates === undefined || rates === null ? undefined : rates[axis];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function keyOf(entry) {
  return `${entry.source}/${entry.model_id}`;
}

export function nameOf(entry) {
  return entry.name === undefined || entry.name === null || entry.name === ""
    ? String(entry.model_id)
    : String(entry.name);
}

/** A whole token count, or the fallback when the text is not one. */
export function tokenCount(text, fallback) {
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : fallback;
}

/** Today in UTC, the calendar the export's own dated fields use. */
export function todayUTC(now = new Date()) {
  return now.toISOString().slice(0, 10);
}

function weekdayOf(day) {
  const at = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(at.getTime()) ? "" : WEEKDAYS[at.getUTCDay()];
}

/** The one interval item covering `day`: `valid_from <= day < valid_to`. */
export function pickInterval(entry, day) {
  const chain = entry.intervals;
  if (!Array.isArray(chain)) return null;
  for (const item of chain) {
    const from = item.valid_from;
    const to = item.valid_to;
    if (typeof from !== "string" || from > day) continue;
    // an empty item carries valid_to === valid_from, and day >= to rules it out
    if (typeof to === "string" && day >= to) continue;
    return item;
  }
  return null;
}

/* A `when` matches on the entry's own scheduling convention: the export writes
   every window as UTC clock minutes and every day-set as UTC calendar days, so
   `timezone` never enters the test. `min_tokens` gates the whole prompt, the
   openrouter `min_prompt_tokens` it is mapped from. */
export function whenMatches(when, ctx) {
  if (when === undefined || when === null || typeof when !== "object") return true;
  if (Array.isArray(when.days) && when.days.length > 0 && !when.days.includes(ctx.weekday)) {
    return false;
  }
  if (Array.isArray(when.window) && when.window.length === 2) {
    const [start, end] = when.window;
    if (typeof start === "number" && typeof end === "number") {
      const at = ctx.minutes;
      // a window that runs past midnight matches on either side of it
      const inside = start <= end ? at >= start && at < end : at >= start || at < end;
      if (!inside) return false;
    }
  }
  const floor = when.min_tokens;
  if (typeof floor === "number" && Number.isFinite(floor) && ctx.inputTokens < floor) {
    return false;
  }
  return true;
}

/** An interval's rates with the last matching override applied: an axis the
    override leaves out keeps the base rate, and a multiplier-only entry prices
    nothing, so the base rates stand. */
export function effectiveRates(item, ctx) {
  const base = item.rates === undefined || item.rates === null ? {} : item.rates;
  const list = Array.isArray(item.overrides) ? item.overrides : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const entry = list[i];
    if (entry === null || typeof entry !== "object") continue;
    if (!whenMatches(entry.when, ctx)) continue;
    const rates = entry.rates;
    if (rates === null || typeof rates !== "object") return base;
    return { ...base, ...rates };
  }
  return base;
}

/**
 * The cost of a session on `day`, in USD, or null where the export prices it
 * with nothing: a day outside every interval, a removed span, or an axis the
 * entry has no rate for while the session uses it.
 *
 * `now` supplies the time of day, since a `when` window is a clock range and
 * only the date is a field of its own.
 */
export function priceSession(entry, day, tokens, now = new Date()) {
  const item = pickInterval(entry, day);
  if (item === null || item.removed === true) return null;
  const rates = effectiveRates(item, {
    weekday: weekdayOf(day),
    minutes: now.getUTCHours() * 60 + now.getUTCMinutes(),
    inputTokens: tokens.input + tokens.cached,
  });
  let total = 0;
  for (const [field, axis] of AXES) {
    const count = tokens[field];
    if (!count) continue;
    // a cached input with no cache axis of its own prices at the input rate
    const rate =
      axis === "cache_read" && axisRate(rates, "cache_read") === null
        ? axisRate(rates, "input")
        : axisRate(rates, axis);
    if (rate === null) return null;
    total += (count / 1e6) * rate;
  }
  return total;
}

/** A session priced at one flat rate, the calculator's typed-rate branch. */
export function priceAtRate(rate, tokens) {
  const count = tokens.input + tokens.cached + tokens.output;
  return (count / 1e6) * rate;
}

/** Money a reader can compare: two decimals from a dollar up, and enough
    digits below it that a small session never rounds away to zero. */
export function formatUSD(value) {
  if (!(value > 0)) return "0.00";
  if (value >= 1) return value.toFixed(2);
  if (value >= 0.01) return value.toFixed(4);
  return value.toPrecision(3);
}

/** The export writes a rate at the shortest form that round-trips it. */
export function formatRate(value) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : DASH;
}

export function multiplier(total, cheapest) {
  if (total === null || cheapest === null || cheapest === undefined) return DASH;
  if (cheapest === 0) return total === 0 ? "1.00×" : DASH;
  return `${(total / cheapest).toFixed(2)}×`;
}

export function defaultState() {
  return {
    q: "",
    sort: "",
    dir: "",
    sel: [],
    calc: { ...DEFAULT_TOKENS },
    day: "",
    rate: "",
  };
}

function rawParams(hash) {
  const text = hash === undefined || hash === null ? "" : String(hash);
  const out = new Map();
  for (const part of text.replace(/^#/, "").split("&")) {
    if (!part) continue;
    const eq = part.indexOf("=");
    out.set(eq === -1 ? part : part.slice(0, eq), eq === -1 ? "" : part.slice(eq + 1));
  }
  return out;
}

function decode(text) {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

/**
 * The page state a fragment names, over the defaults. Values arrive
 * percent-decoded here rather than through `URLSearchParams`, because `sel`
 * splits on a literal comma first: a model key carrying one would otherwise
 * come out of the decoder already split.
 */
export function decodeState(hash) {
  const state = defaultState();
  const params = rawParams(hash);
  const text = (key) => (params.has(key) ? decode(params.get(key)) : "");

  state.q = text("q");
  const sort = text("sort");
  const dir = text("dir");
  if (SORT_KEYS.includes(sort) && (dir === "asc" || dir === "desc")) {
    state.sort = sort;
    state.dir = dir;
  }
  if (params.has("sel")) {
    state.sel = params
      .get("sel")
      .split(",")
      .filter((part) => part !== "")
      .map(decode);
  }
  const calc = text("calc").split("|");
  if (calc.length === 3) {
    state.calc = {
      input: tokenCount(calc[0], DEFAULT_TOKENS.input),
      cached: tokenCount(calc[1], DEFAULT_TOKENS.cached),
      output: tokenCount(calc[2], DEFAULT_TOKENS.output),
    };
  }
  const day = text("day");
  if (DAY_PATTERN.test(day)) state.day = day;
  const rate = text("rate");
  if (rate !== "" && Number(rate) > 0 && Number.isFinite(Number(rate))) state.rate = rate;
  return state;
}

export function encodeState(state) {
  const parts = [];
  if (state.q) parts.push(`q=${encodeURIComponent(state.q)}`);
  if (state.sort && state.dir) {
    parts.push(`sort=${encodeURIComponent(state.sort)}`);
    parts.push(`dir=${encodeURIComponent(state.dir)}`);
  }
  if (state.sel.length > 0) parts.push(`sel=${state.sel.map(encodeURIComponent).join(",")}`);
  const { input, cached, output } = state.calc;
  parts.push(`calc=${input}|${cached}|${output}`);
  if (state.day) parts.push(`day=${encodeURIComponent(state.day)}`);
  if (state.rate) parts.push(`rate=${encodeURIComponent(state.rate)}`);
  return parts.join("&");
}

/* ------------------------------------------------------------------ render */

function cell(text, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  td.textContent = text;
  return td;
}

function tag(text, variant) {
  const span = document.createElement("span");
  span.className = `tag ${variant}`;
  span.textContent = text;
  return span;
}

function rateOf(entry, axis) {
  return axisRate(entry.rates, axis);
}

function sortValue(entry, key) {
  switch (key) {
    case "input":
    case "cache_read":
    case "output":
      return rateOf(entry, key);
    case "vendor":
      return entry.vendor ? String(entry.vendor).toLowerCase() : null;
    default:
      return nameOf(entry).toLowerCase();
  }
}

/* a model the export has no reading for sorts to the bottom in either
   direction: an empty cell is a missing fact, not a small number */
function compareOn(key, dir) {
  const sign = dir === "desc" ? -1 : 1;
  return (a, b) => {
    const left = sortValue(a, key);
    const right = sortValue(b, key);
    if (left === null || right === null) {
      if (left === null && right === null) return 0;
      return left === null ? 1 : -1;
    }
    if (left < right) return -sign;
    if (left > right) return sign;
    return 0;
  };
}

/**
 * The sort cycle lives in the shipped table controller's own memory, so a
 * fragment that restores one steps through the same clicks a reader would
 * make; the events it emits write the state back.
 *
 * The fragment's own dir is read before the first click: each click's handler
 * overwrites `state.dir` with the cycle's next value, so reading it after
 * lands on the cycle's `asc` and never gives a `desc` fragment its second
 * click.
 */
export function restoreSort(state, wrap) {
  if (!state.sort) return;
  const button = wrap.querySelector(`.th-sort[data-sort="${state.sort}"]`);
  if (!button) return;
  const dir = state.dir;
  button.click();
  if (dir === "desc") button.click();
}

/**
 * The page's ready report: the mark the page's load-time check reads back.
 *
 * It reports only once the shipped table controller has marked the wrap,
 * because a page whose controller never ran has sort headers that look live
 * and do nothing. Returns whether it reported.
 */
export function reportReady(doc, wrap) {
  if (wrap.dataset.uiTable === undefined) return false;
  doc.documentElement.dataset.site = "ready";
  return true;
}

function init() {
  const wrap = document.getElementById("models");
  const body = document.getElementById("models-body");
  const island = document.getElementById("flat-data");
  if (!wrap || !body || !island) return;

  let payload;
  try {
    payload = JSON.parse(island.textContent);
  } catch {
    return;
  }
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  const lookup = new Map(entries.map((entry) => [keyOf(entry), entry]));
  const state = decodeState(window.location.hash);

  const qBox = document.getElementById("q");
  const tokenBoxes = {
    input: document.getElementById("calc-input"),
    cached: document.getElementById("calc-cached"),
    output: document.getElementById("calc-output"),
  };
  const dayBox = document.getElementById("calc-day");
  const rateBox = document.getElementById("calc-rate");
  const sessionWrap = document.getElementById("session-wrap");
  const sessionBody = document.getElementById("session-body");
  const sessionEmpty = document.getElementById("session-empty");
  const sessionNote = document.getElementById("session-note");
  const rateLine = document.getElementById("rate-line");
  const countLine = document.getElementById("model-count");

  let lastHash = "";

  function push() {
    const encoded = encodeState(state);
    if (encoded === lastHash) return;
    lastHash = encoded;
    window.history.replaceState(null, "", `#${encoded}`);
  }

  function syncAriaSort() {
    const aria = { asc: "ascending", desc: "descending" };
    for (const th of wrap.querySelectorAll("th[aria-sort]")) {
      const button = th.querySelector(".th-sort");
      const on = button && button.dataset.sort === state.sort && state.dir !== "";
      th.setAttribute("aria-sort", on ? aria[state.dir] : "none");
    }
  }

  function rowFor(entry) {
    const key = keyOf(entry);
    const tr = document.createElement("tr");

    const pick = document.createElement("td");
    pick.className = "cell-select";
    const label = document.createElement("label");
    label.className = "checkbox-label";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.dataset.name = key;
    box.checked = state.sel.includes(key);
    box.setAttribute("aria-label", `compare ${nameOf(entry)}`);
    label.append(box);
    pick.append(label);
    tr.append(pick);

    const name = document.createElement("td");
    const title = document.createElement("span");
    title.className = "table-name";
    title.textContent = nameOf(entry);
    name.append(title);
    if (entry.removed_at) {
      name.append(document.createTextNode(" "));
      name.append(tag(`removed ${entry.removed_at}`, "tag-danger"));
    }
    const sub = document.createElement("div");
    sub.className = "td-sub";
    sub.textContent = `${entry.source} · ${entry.observed_at}`;
    name.append(sub);
    tr.append(name);

    tr.append(cell(entry.vendor ? String(entry.vendor) : DASH));
    tr.append(cell(formatRate(rateOf(entry, "input")), "num-col"));
    tr.append(cell(formatRate(rateOf(entry, "cache_read")), "num-col"));
    tr.append(cell(formatRate(rateOf(entry, "output")), "num-col"));
    return tr;
  }

  function renderRows() {
    const needle = state.q.trim().toLowerCase();
    let shown = entries;
    if (needle) {
      shown = entries.filter(
        (entry) =>
          nameOf(entry).toLowerCase().includes(needle) ||
          String(entry.vendor === null || entry.vendor === undefined ? "" : entry.vendor)
            .toLowerCase()
            .includes(needle),
      );
    }
    if (state.sort && state.dir) {
      // a stable sort keeps the export's own order inside every tie
      shown = shown.slice().sort(compareOn(state.sort, state.dir));
    }
    const fragment = document.createDocumentFragment();
    for (const entry of shown) fragment.append(rowFor(entry));
    body.replaceChildren(fragment);
    if (countLine) countLine.textContent = `${shown.length} of ${entries.length} models`;
    syncAriaSort();
  }

  function renderSession() {
    const day = state.day || todayUTC();
    const rows = [];
    for (const key of state.sel) {
      const entry = lookup.get(key);
      if (entry === undefined) continue;
      rows.push({ entry, total: priceSession(entry, day, state.calc) });
    }
    rows.sort((a, b) => {
      if (a.total === null || b.total === null) {
        if (a.total === null && b.total === null) return 0;
        return a.total === null ? 1 : -1;
      }
      return a.total - b.total;
    });
    const cheapest = rows.length > 0 && rows[0].total !== null ? rows[0].total : null;

    const fragment = document.createDocumentFragment();
    for (const { entry, total } of rows) {
      const tr = document.createElement("tr");
      tr.append(cell(nameOf(entry)));
      tr.append(cell(total === null ? DASH : formatUSD(total), "num-col"));
      tr.append(cell(multiplier(total, cheapest), "num-col"));
      fragment.append(tr);
    }
    sessionBody.replaceChildren(fragment);
    if (sessionWrap) sessionWrap.hidden = rows.length === 0;
    if (sessionEmpty) sessionEmpty.hidden = rows.length > 0;

    if (sessionNote) {
      const at = new Date();
      const hours = String(at.getUTCHours()).padStart(2, "0");
      const minutes = String(at.getUTCMinutes()).padStart(2, "0");
      sessionNote.textContent =
        todayUTC(at) === day
          ? `priced at ${hours}:${minutes} UTC today`
          : `priced at ${hours}:${minutes} UTC on ${day}`;
    }
    if (rateLine) {
      rateLine.textContent = state.rate
        ? `at your $${state.rate} rate: ${formatUSD(priceAtRate(Number(state.rate), state.calc))} this session`
        : "";
      rateLine.hidden = state.rate === "";
    }
  }

  function syncControls() {
    if (qBox) qBox.value = state.q;
    if (dayBox) dayBox.value = state.day;
    if (rateBox) rateBox.value = state.rate;
    for (const [field, box] of Object.entries(tokenBoxes)) {
      if (box) box.value = String(state.calc[field]);
    }
  }

  qBox?.addEventListener("input", () => {
    state.q = qBox.value;
    renderRows();
    push();
  });

  for (const [field, box] of Object.entries(tokenBoxes)) {
    box?.addEventListener("input", () => {
      state.calc[field] = tokenCount(box.value, 0);
      renderSession();
      push();
    });
  }

  dayBox?.addEventListener("input", () => {
    state.day = DAY_PATTERN.test(dayBox.value) ? dayBox.value : "";
    renderSession();
    push();
  });

  rateBox?.addEventListener("input", () => {
    state.rate = Number(rateBox.value) > 0 && Number.isFinite(Number(rateBox.value)) ? rateBox.value : "";
    renderSession();
    push();
  });

  wrap.addEventListener("table:sort", (event) => {
    const { key, dir } = event.detail;
    state.sort = dir === "none" ? "" : key;
    state.dir = dir === "none" ? "" : dir;
    renderRows();
    push();
  });

  wrap.addEventListener("table:selection", (event) => {
    // a row a search is hiding keeps its membership: only the boxes on screen
    // speak for their own name
    const shown = new Set(
      [...wrap.querySelectorAll('tbody input[type="checkbox"][data-name]')].map((box) => box.dataset.name),
    );
    state.sel = [...new Set([...state.sel.filter((key) => !shown.has(key)), ...event.detail.selected])];
    renderSession();
    push();
  });

  syncControls();
  renderRows();
  renderSession();
  lastHash = encodeState(state);

  restoreSort(state, wrap);

  // last, so nothing below it can leave the page reported ready
  reportReady(document, wrap);
}

if (typeof document !== "undefined") init();
