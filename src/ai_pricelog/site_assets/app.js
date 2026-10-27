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

/** Whether `text` is a real calendar day, not only a YYYY-MM-DD-shaped one: a
    link naming the 30th of february must fall back rather than reach the
    picker's month arithmetic. */
function isDay(text) {
  if (!DAY_PATTERN.test(text)) return false;
  const at = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(at.getTime()) && at.toISOString().slice(0, 10) === text;
}
/* the request modes the calculator offers; "" is the standard request. the
   row schema keeps `mode` an open string, but the page never invents modes */
export const MODES = ["fast", "batch"];
/* the price axes the detail card's chart offers, in selector order */
export const CHART_AXES = ["input", "output", "cache_read"];

function axisRate(rates, axis) {
  const value = rates === undefined || rates === null ? undefined : rates[axis];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Whether a `when` names a clock window, the one override shape that
    schedules a price: the structural read `whenMatches` gates on, numeric
    minute pair included. */
function hasClockWindow(when) {
  if (when === null || typeof when !== "object") return false;
  const window = when.window;
  if (!Array.isArray(window) || window.length !== 2) return false;
  const [start, end] = window;
  return Number.isFinite(start) && Number.isFinite(end);
}

/** The per-axis peak: the highest of the base rate and every override whose
    `when` names a clock window. A threshold, mode, day-only or quota-only
    override prices no clock range, so none enters the peak; `null` when
    nothing prices the axis. An interval item reads the same way. */
export function peakRate(entry, axis) {
  const values = [];
  const base = axisRate(entry.rates, axis);
  if (base !== null) values.push(base);
  const overrides = Array.isArray(entry.overrides) ? entry.overrides : [];
  for (const override of overrides) {
    if (override === null || typeof override !== "object") continue;
    if (!hasClockWindow(override.when)) continue;
    const value = axisRate(override.rates, axis);
    if (value !== null) values.push(value);
  }
  return values.length === 0 ? null : Math.max(...values);
}

export function keyOf(entry) {
  return `${entry.source}/${entry.model_id}`;
}

export function nameOf(entry) {
  return entry.name === undefined || entry.name === null || entry.name === ""
    ? String(entry.model_id)
    : String(entry.name);
}

/** Whether the entry prices a chat session: a non-text row carries a
    modality and never enters the token calculator. */
export function isChatPriced(entry) {
  return !(typeof entry.modality === "string" && entry.modality !== "");
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

/** The whole Monday-first weeks a month's calendar covers, adjacent-month days
    included, so every row is seven cells and no month starts mid-row. 0-based
    month; a flat list of `YYYY-MM-DD` strings. */
export function monthGrid(year, month) {
  const first = Date.UTC(year, month, 1);
  const lead = (new Date(first).getUTCDay() + 6) % 7;
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const length = Math.ceil((lead + daysInMonth) / 7) * 7;
  const days = [];
  for (let index = 0; index < length; index += 1) {
    days.push(new Date(Date.UTC(year, month, 1 - lead + index)).toISOString().slice(0, 10));
  }
  return days;
}

/**
 * The price history one axis carries, split into the unbroken runs of the
 * timeline: one point per interval that prices the axis, and a run ends where an
 * interval stops pricing it or removes the model. A later era that prices the
 * axis again opens a new run, so a gap never grows a price the source did not
 * charge. With `peak`, a point is the interval's own peak rate instead of its
 * base rate. `removed` is the model's own state today, which is the entry's,
 * not any single era's.
 */
export function chartPoints(entry, axis, peak = false) {
  const runs = [];
  let run = null;
  const chain = Array.isArray(entry.intervals) ? entry.intervals : [];
  for (const item of chain) {
    if (item.valid_to === item.valid_from) continue;
    const value =
      item.removed === true ? null : peak ? peakRate(item, axis) : axisRate(item.rates, axis);
    if (value === null) {
      if (run !== null) {
        run.end = item.valid_from ?? null;
        runs.push(run);
        run = null;
      }
      continue;
    }
    if (run === null) run = { points: [], end: null };
    run.points.push({ date: item.valid_from, value });
  }
  if (run !== null) runs.push(run);
  const removedAt = typeof entry.removed_at === "string" ? entry.removed_at : "";
  return { runs, removed: removedAt !== "" };
}

function dayMs(day) {
  return Date.parse(`${day}T00:00:00Z`);
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

/** The span every run is drawn across: the first point of the oldest run to the
    last run's own end, or today while that run is still open. */
function chartDomain(runs) {
  const finish = runs[runs.length - 1].end ?? todayUTC();
  return { start: runs[0].points[0].date, finish };
}

function chartPeak(runs) {
  return Math.max(
    ...runs.flatMap((run) => run.points.map((point) => point.value)),
    0,
  );
}

/**
 * One run's step polyline in the shared 0 0 100 100 box: each price holds from
 * its own point to the next, so the vertices run
 * `(x0,y0) (x1,y0) (x1,y1) ... (x_last,y_last)`, and the last tread holds to
 * the domain end. y is inverted, and x is a percentage of the shared domain.
 *
 * A history that never moved draws through the middle of its box: pinned to the
 * top it would read as the cell's own rule rather than as a flat price.
 */
export function stepPolyline(run, domain, peak, flat) {
  const points = run.points;
  if (points.length === 0) return "";
  const start = dayMs(domain.start);
  const span = Math.max(dayMs(domain.finish) - start, 1);
  const last = Math.min(100, ((dayMs(run.end ?? domain.finish) - start) / span) * 100);
  const x = (date) => Math.min(100, Math.max(0, ((dayMs(date) - start) / span) * 100));
  const y = (value) => {
    if (flat) return 50;
    return peak > 0 ? 100 - (value / peak) * 100 : 100;
  };
  const coords = [];
  let level = y(points[0].value);
  coords.push(`${round2(x(points[0].date))},${round2(level)}`);
  for (const point of points.slice(1)) {
    const column = round2(x(point.date));
    coords.push(`${column},${round2(level)}`);
    level = y(point.value);
    coords.push(`${column},${round2(level)}`);
  }
  coords.push(`${round2(last)},${round2(level)}`);
  return coords.join(" ");
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
   openrouter `min_prompt_tokens` it is mapped from. `mode` names the request
   mode the override prices (anthropic fast mode); the calculator's empty
   string is the standard, mode-less request. */
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
  if (typeof floor === "number" && Number.isFinite(floor) && ctx.inputTokens <= floor) {
    return false;
  }
  if (when.mode !== undefined && when.mode !== ctx.mode) return false;
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
 * with nothing: an entry the page treats as not chat-priced, a day outside
 * every interval, a removed span, or an axis the entry has no rate for while
 * the session uses it.
 *
 * `now` supplies the time of day, since a `when` window is a clock range and
 * only the date is a field of its own. `mode` is the request mode the session
 * runs under; the empty string is the standard, mode-less request.
 */
export function priceSession(entry, day, tokens, now = new Date(), mode = "") {
  if (!isChatPriced(entry)) return null;
  const item = pickInterval(entry, day);
  if (item === null || item.removed === true) return null;
  const rates = effectiveRates(item, {
    weekday: weekdayOf(day),
    minutes: now.getUTCHours() * 60 + now.getUTCMinutes(),
    inputTokens: tokens.input + tokens.cached,
    mode,
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
    mode: "",
    model: "",
    peak: false,
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
  if (isDay(day)) state.day = day;
  const rate = text("rate");
  if (rate !== "" && Number(rate) > 0 && Number.isFinite(Number(rate))) state.rate = rate;
  const mode = text("mode");
  if (MODES.includes(mode)) state.mode = mode;
  state.model = text("model");
  state.peak = text("peak") === "1";
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
  if (state.mode) parts.push(`mode=${encodeURIComponent(state.mode)}`);
  // the slash is the key's own separator, so it is the one character the
  // fragment keeps literal; everything else still percent-encodes
  if (state.model) parts.push(`model=${encodeURIComponent(state.model).replaceAll("%2F", "/")}`);
  // peak rides last, the one key a shared link gains after model
  if (state.peak) parts.push("peak=1");
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

function sortValue(entry, key, peak) {
  switch (key) {
    case "input":
    case "cache_read":
    case "output":
      return peak ? peakRate(entry, key) : rateOf(entry, key);
    case "vendor":
      return entry.vendor ? String(entry.vendor).toLowerCase() : null;
    default:
      return nameOf(entry).toLowerCase();
  }
}

/* a model the export has no reading for sorts to the bottom in either
   direction: an empty cell is a missing fact, not a small number */
function compareOn(key, dir, peak) {
  const sign = dir === "desc" ? -1 : 1;
  return (a, b) => {
    const left = sortValue(a, key, peak);
    const right = sortValue(b, key, peak);
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

function svgNode(tag) {
  // the node harness stubs a minimal document with no SVG factory
  return typeof document.createElementNS === "function"
    ? document.createElementNS("http://www.w3.org/2000/svg", tag)
    : document.createElement(tag);
}

/* the rate-axis labels a reader reads; cache_read matches the table's own
   column label, the rest spell out with spaces */
const AXIS_LABELS = { cache_read: "cached input" };

function axisLabel(axis) {
  const text = String(axis);
  return Object.hasOwn(AXIS_LABELS, text) ? AXIS_LABELS[text] : text.replaceAll("_", " ");
}

function clockText(minutes) {
  const whole = ((Math.floor(minutes) % 1440) + 1440) % 1440;
  const hours = String(Math.floor(whole / 60)).padStart(2, "0");
  return `${hours}:${String(whole % 60).padStart(2, "0")}`;
}

/** An override window as the UTC clock range every `when` is written in. */
function whenText(when) {
  if (when === null || typeof when !== "object") return "any request";
  const parts = [];
  if (Array.isArray(when.days) && when.days.length > 0) parts.push(when.days.join(", "));
  if (
    Array.isArray(when.window) &&
    when.window.length === 2 &&
    when.window.every((minute) => typeof minute === "number" && Number.isFinite(minute))
  ) {
    parts.push(`${clockText(when.window[0])} to ${clockText(when.window[1])} UTC`);
  }
  if (typeof when.min_tokens === "number" && Number.isFinite(when.min_tokens)) {
    parts.push(`above ${when.min_tokens} tokens`);
  }
  if (typeof when.mode === "string" && when.mode !== "") parts.push(`mode ${when.mode}`);
  // the window is UTC clock minutes whatever zone the schedule was written in,
  // so the zone rides as the provenance it is and never beside the window
  if (typeof when.timezone === "string" && when.timezone !== "") {
    parts.push(`schedule zone ${when.timezone}`);
  }
  return parts.length > 0 ? parts.join(", ") : "any request";
}

function ratesText(rates) {
  return Object.entries(rates)
    .filter(([, value]) => typeof value === "number" && Number.isFinite(value))
    .map(([axis, value]) => `${axisLabel(axis)} ${formatRate(value)}`)
    .join(", ");
}

function overrideText(override) {
  const when = whenText(override.when);
  const rates =
    override.rates !== null && typeof override.rates === "object" ? ratesText(override.rates) : "";
  const quota =
    typeof override.quota_multiplier === "number" && Number.isFinite(override.quota_multiplier)
      ? `× ${override.quota_multiplier}`
      : "";
  return [when, rates, quota].filter(Boolean).join(": ");
}

function detailRow(label, value) {
  const tr = document.createElement("tr");
  const key = document.createElement("td");
  key.textContent = label;
  const cell = document.createElement("td");
  cell.textContent = String(value);
  tr.append(key, cell);
  return tr;
}

/** The interval the entry's own rates came from: the priced era observed at the
    entry's own observation, or the last priced era when none carries it. */
function currentEra(entry) {
  const chain = Array.isArray(entry.intervals) ? entry.intervals : [];
  const priced = chain.filter(
    (item) => item.removed !== true && item.valid_to !== item.valid_from,
  );
  const stamped = priced.filter((item) => item.observed_at === entry.observed_at);
  if (stamped.length > 0) return stamped[stamped.length - 1];
  return priced.length > 0 ? priced[priced.length - 1] : null;
}

/** The rate axes the entry's peak schedule prices: the base's axes plus every
    axis a clock-window override carries, so a window-only axis still reads. */
function peakAxes(entry) {
  const axes = new Set();
  const base = entry.rates !== null && typeof entry.rates === "object" ? entry.rates : {};
  for (const axis of Object.keys(base)) axes.add(axis);
  const overrides = Array.isArray(entry.overrides) ? entry.overrides : [];
  for (const override of overrides) {
    if (override === null || typeof override !== "object") continue;
    if (!hasClockWindow(override.when)) continue;
    const rates = override.rates;
    if (rates === null || typeof rates !== "object") continue;
    for (const axis of Object.keys(rates)) axes.add(axis);
  }
  return axes;
}

function renderInfo(tbody, entry, peak) {
  const rows = [];
  const add = (label, value) => rows.push(detailRow(label, value));
  if (peak) {
    for (const axis of peakAxes(entry)) {
      const value = peakRate(entry, axis);
      if (value !== null) add(`rate ${axisLabel(axis)}`, formatRate(value));
    }
  } else {
    const rates = entry.rates !== null && typeof entry.rates === "object" ? entry.rates : {};
    for (const [axis, value] of Object.entries(rates)) {
      if (typeof value === "number" && Number.isFinite(value)) {
        add(`rate ${axisLabel(axis)}`, formatRate(value));
      }
    }
  }
  if (typeof entry.currency === "string" && entry.currency !== "") {
    add("quoted in", entry.currency);
  }
  const limits = entry.limits !== null && typeof entry.limits === "object" ? entry.limits : {};
  for (const [key, value] of Object.entries(limits)) {
    if (value !== null && value !== undefined) add(`limit ${axisLabel(key)}`, String(value));
  }
  const overrides = Array.isArray(entry.overrides) ? entry.overrides : [];
  overrides.forEach((override, index) => {
    if (override !== null && typeof override === "object") {
      add(`override ${index + 1}`, overrideText(override));
    }
  });
  if (entry.first_seen) add("first seen", entry.first_seen);
  if (entry.observed_at) add("observed", entry.observed_at);
  const era = currentEra(entry);
  if (era !== null) {
    if (era.valid_from) add("valid from", era.valid_from);
    add("valid to", era.valid_to ?? DASH);
  }
  if (entry.removed_at) add("removed", entry.removed_at);
  tbody.replaceChildren(...rows);
}

function renderTags(container, entry) {
  const tags = [];
  if (typeof entry.vendor === "string" && entry.vendor !== "") {
    tags.push(tag(entry.vendor, "tag-default"));
  }
  if (typeof entry.modality === "string" && entry.modality !== "") {
    tags.push(tag(entry.modality, "tag-info"));
  }
  if (entry.removed_at) tags.push(tag(`removed ${entry.removed_at}`, "tag-danger"));
  container.replaceChildren(...tags);
}

function drawGrid(grid, runs) {
  grid.replaceChildren();
  if (runs.length === 0) return;
  // the bottom tick is the plot's own axis line, so the grid carries the two above it
  for (const at of [0, 50]) {
    const line = svgNode("line");
    line.setAttribute("x1", "0");
    line.setAttribute("y1", String(at));
    line.setAttribute("x2", "100");
    line.setAttribute("y2", String(at));
    grid.append(line);
  }
}

function drawYTicks(container, runs) {
  container.replaceChildren();
  if (runs.length === 0) return;
  const peak = chartPeak(runs);
  for (const value of [peak, peak / 2, 0]) {
    const tick = document.createElement("span");
    tick.className = "chart-tick";
    tick.textContent = formatRate(value);
    container.append(tick);
  }
}

function drawXTicks(container, runs, domain) {
  container.replaceChildren();
  if (runs.length === 0 || domain === null) return;
  for (const [date, at] of [
    [domain.start, "0%"],
    [domain.finish, "100%"],
  ]) {
    const tick = document.createElement("span");
    tick.className = "chart-tick";
    tick.style.setProperty("--at", at);
    tick.textContent = date;
    container.append(tick);
  }
}

function describeChart(entry, axis, runs, removed) {
  const label = axisLabel(axis);
  if (runs.length === 0) return `no ${label} rate is recorded for ${nameOf(entry)}.`;
  const spans = runs.map((run) => {
    const steps = run.points.map((point) => `${formatRate(point.value)} from ${point.date}`);
    return run.end === null ? steps.join(", ") : `${steps.join(", ")}, the line stops at ${run.end}`;
  });
  let tail = "";
  const lastEnd = runs[runs.length - 1].end;
  if (lastEnd !== null) {
    tail = removed ? `; the model was removed there` : `; no later era prices ${label}`;
  }
  return `${label} price per million tokens: ${spans.join("; then ")}${tail}.`;
}

/** One series group per run, each carrying its own line, tint and end mark: the
    controller keeps one line's marks per group, so a second line in the same
    group would share the first one's. */
function drawRuns(detail, shapes) {
  const groups = [...detail.svg.querySelectorAll(".chart-series")];
  const keep = Math.max(shapes.length, 1);
  for (const extra of groups.slice(keep)) extra.remove();
  for (let index = 0; index < keep; index += 1) {
    let group = groups[index];
    if (group === undefined) {
      group = svgNode("g");
      group.setAttribute("class", "chart-series chart-series-1");
      detail.svg.append(group);
    }
    let line = group.querySelector(".chart-line");
    if (line === null) {
      line = svgNode("polyline");
      line.setAttribute("class", "chart-line");
      group.append(line);
    }
    line.setAttribute("points", shapes[index] ?? "");
  }
}

function drawChart(detail, entry, peak) {
  const { runs, removed } = chartPoints(entry, detail.axis, peak);
  const domain = runs.length === 0 ? null : chartDomain(runs);
  const top = chartPeak(runs);
  // the card's chart carries an axis, so every line sits at its own reading; the
  // centred flat line is the sparkline's rule, where there is no axis to read
  const shapes =
    domain === null ? [] : runs.map((run) => stepPolyline(run, domain, top, false));
  drawRuns(detail, shapes);
  // a run past the first is a group the controller never scanned at boot, so it
  // gets no tint and no end mark until the module looks again
  wireLineMarks();
  drawGrid(detail.grid, runs);
  drawYTicks(detail.ticksY, runs);
  drawXTicks(detail.ticksX, runs, domain);
  const title = detail.svg.querySelector("title");
  if (title) title.textContent = `${nameOf(entry)} ${axisLabel(detail.axis)} price history`;
  const desc = detail.svg.querySelector("desc");
  if (desc) desc.textContent = describeChart(entry, detail.axis, runs, removed);
  // the body ships hidden, so the entrance observer never saw this chart
  detail.chart.classList.add("is-drawn");
}

function renderDetail(detail, entry, peak) {
  detail.name.textContent = nameOf(entry);
  detail.id.textContent = keyOf(entry);
  renderTags(detail.tags, entry);
  detail.empty.hidden = true;
  detail.body.hidden = false;
  detail.card.dataset.empty = "false";
  if (detail.close !== null) detail.close.hidden = false;
  renderInfo(detail.info, entry, peak);
  drawChart(detail, entry, peak);
}

/** Back to the empty card: the state key goes with the body, so a reload or a
    shared url does not reopen it. */
function emptyDetail(detail) {
  detail.name.textContent = "model detail";
  detail.id.textContent = "";
  renderTags(detail.tags, {});
  detail.body.hidden = true;
  detail.empty.hidden = false;
  detail.card.dataset.empty = "true";
  if (detail.close !== null) detail.close.hidden = true;
}

function detailNodes() {
  const card = document.getElementById("model-detail");
  const chart = document.getElementById("detail-chart");
  if (card === null || chart === null) return null;
  const svg = chart.querySelector(".chart-svg");
  const grid = chart.querySelector(".chart-grid");
  // the series group and its line are the chart's skeleton; every draw rebuilds
  // them from the runs, and a missing one means the markup moved
  const skeleton = chart.querySelector(".chart-series") && chart.querySelector(".chart-line");
  if (svg === null || grid === null || !skeleton) return null;
  return {
    card,
    chart,
    svg,
    grid,
    name: document.getElementById("detail-name"),
    id: document.getElementById("detail-id"),
    tags: document.getElementById("detail-tags"),
    empty: document.getElementById("detail-empty"),
    body: document.getElementById("detail-body"),
    close: document.getElementById("detail-close"),
    ticksY: document.getElementById("detail-ticks-y"),
    ticksX: document.getElementById("detail-ticks-x"),
    info: document.getElementById("detail-info"),
    axis: CHART_AXES[0],
  };
}

/* The vendored controller draws a sparkline's tint and end dot from its
   polyline, but it scans once at boot and these rows are built after that.
   Re-running it is the module's own idempotent entry: every line it already
   wired is skipped. The import is dynamic because the build's node harness
   loads this module with no ui.js beside it. */
let chartController;

function wireLineMarks() {
  if (typeof document === "undefined" || typeof document.createElementNS !== "function") return;
  chartController ??= import("./ui.js")
    .then((ui) => ui.initChart)
    .catch(() => null);
  chartController.then((initChart) => initChart?.());
}

/* the row's own price history, always on the input axis: the card's selector
   filters the card, never the list */
function sparkShape(entry) {
  const { runs } = chartPoints(entry, "input");
  if (runs.length === 0) return null;
  const domain = chartDomain(runs);
  const peak = chartPeak(runs);
  const flat = runs.every((run) => run.points.every((point) => point.value === peak));
  const spark = document.createElement("div");
  spark.className = "stat-spark";
  spark.setAttribute("aria-hidden", "true");
  // one svg per run: the controller keeps one line's marks per svg, so two runs
  // in one svg would share a single tint and end dot
  for (const run of runs) {
    const svg = svgNode("svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("preserveAspectRatio", "none");
    const line = svgNode("polyline");
    line.setAttribute("points", stepPolyline(run, domain, peak, flat));
    svg.append(line);
    spark.append(svg);
  }
  return spark;
}

function sparkCell(entry) {
  const td = document.createElement("td");
  td.className = "spark-cell";
  const spark = sparkShape(entry);
  // an entry whose history prices input nowhere (an auto-router) has no shape
  // to draw, and an empty cell reads as a bug: it takes the table's own dash
  td.append(spark ?? document.createTextNode(DASH));
  return td;
}

export function init() {
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
  const arrived = encodeState(state);
  // a fragment can name a key no box can clear any more (a modality row, or a
  // model that left the tree); drop it so the URL and the session agree
  state.sel = state.sel.filter((key) => {
    const entry = lookup.get(key);
    return entry !== undefined && isChatPriced(entry);
  });
  // the same rule for the detail card: a fragment naming no entry selects nothing
  if (state.model !== "" && !lookup.has(state.model)) state.model = "";
  // a dropped key leaves the url too, or a reload resurrects the dead selection
  if (encodeState(state) !== arrived) {
    window.history.replaceState(null, "", `#${encodeState(state)}`);
  }
  const detail = detailNodes();

  const qBox = document.getElementById("q");
  const tokenBoxes = {
    input: document.getElementById("calc-input"),
    cached: document.getElementById("calc-cached"),
    output: document.getElementById("calc-output"),
  };
  const dayBox = document.getElementById("calc-day");
  const rateBox = document.getElementById("calc-rate");
  const modeBox = document.getElementById("calc-mode");
  const dayRange = document.getElementById("calc-day-range");
  const dayPanel = document.getElementById("calc-day-panel");
  const dayValue = document.getElementById("calc-day-value");
  const modeValue = document.getElementById("calc-mode-value");
  const modeOptions = modeBox === null ? [] : [...modeBox.querySelectorAll('[role="option"]')];
  const sessionWrap = document.getElementById("session-wrap");
  const sessionBody = document.getElementById("session-body");
  const sessionEmpty = document.getElementById("session-empty");
  const sessionNote = document.getElementById("session-note");
  const rateLine = document.getElementById("rate-line");
  const countLine = document.getElementById("model-count");
  const peakToggle = document.getElementById("peak-toggle");

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

  const modelButtons = new Map();

  function rowFor(entry) {
    const key = keyOf(entry);
    const tr = document.createElement("tr");

    const pick = document.createElement("td");
    pick.className = "cell-select";
    if (isChatPriced(entry)) {
      const label = document.createElement("label");
      label.className = "checkbox-label";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.dataset.name = key;
      box.checked = state.sel.includes(key);
      box.setAttribute("aria-label", `compare ${nameOf(entry)}`);
      label.append(box);
      pick.append(label);
    }
    tr.append(pick);

    const name = document.createElement("td");
    const title = document.createElement("button");
    title.type = "button";
    title.className = "table-name model-button";
    title.dataset.key = key;
    title.setAttribute("aria-controls", "model-detail");
    title.textContent = nameOf(entry);
    title.addEventListener("click", () => selectModel(key));
    modelButtons.set(key, title);
    name.append(title);
    const modalityTag = isChatPriced(entry) ? null : tag(entry.modality, "tag-info");
    if (modalityTag !== null) {
      name.append(document.createTextNode(" "));
      name.append(modalityTag);
    }
    const removedTag = entry.removed_at
      ? tag(`removed ${entry.removed_at}`, "tag-danger")
      : null;
    if (removedTag !== null) {
      name.append(document.createTextNode(" "));
      name.append(removedTag);
    }
    // built once here so a toggle appends the very node instead of constructing
    // one per flip
    const peakTag = tag("peak", "tag-warning");
    const sub = document.createElement("div");
    sub.className = "td-sub";
    sub.textContent = `${entry.source} · ${entry.observed_at}`;
    name.append(sub);
    tr.append(name);

    const vendor = document.createElement("td");
    vendor.className = "col-vendor";
    vendor.textContent = entry.vendor ? String(entry.vendor) : DASH;
    tr.append(vendor);
    // the three rate cells the peak toggle rewrites in place
    const rateCells = AXES.map(([, axis]) => cell(formatRate(rateOf(entry, axis)), "num-col"));
    for (const rateCell of rateCells) tr.append(rateCell);
    tr.append(sparkCell(entry));
    return { tr, entry, name, title, modalityTag, removedTag, peakTag, sub, rateCells };
  }

  /* the mark moves between the one button carrying it and the new pick: the
     scan it replaces touched every model button on every render */
  let currentButton = null;

  function syncModelCurrent() {
    const button = state.model === "" ? null : modelButtons.get(state.model) ?? null;
    if (button === currentButton) return;
    if (currentButton !== null) currentButton.setAttribute("aria-current", "false");
    if (button !== null) button.setAttribute("aria-current", "true");
    currentButton = button;
  }

  function selectModel(key) {
    const entry = lookup.get(key);
    if (entry === undefined) return;
    state.model = key;
    syncModelCurrent();
    if (detail !== null) {
      renderDetail(detail, entry, state.peak);
      // one column puts the card above the table, so a pick below the fold must
      // bring it back into view or the page reads as if the tap did nothing
      if (detail.card.getBoundingClientRect().top < 0) {
        detail.card.scrollIntoView({ block: "start" });
      }
    }
    push();
  }

  function clearModel() {
    state.model = "";
    syncModelCurrent();
    if (detail !== null) emptyDetail(detail);
    push();
  }

  function showSelectedModel() {
    if (detail === null || state.model === "") return;
    const entry = lookup.get(state.model);
    if (entry !== undefined) renderDetail(detail, entry, state.peak);
  }

  /* the filter's own predicate: the one definition of "on screen", shared by
     the row pass and the selection merge so the two can never disagree */
  function matchesFilter(entry) {
    const needle = state.q.trim().toLowerCase();
    if (needle === "") return true;
    return (
      nameOf(entry).toLowerCase().includes(needle) ||
      String(entry.vendor === null || entry.vendor === undefined ? "" : entry.vendor)
        .toLowerCase()
        .includes(needle)
    );
  }

  function shownKeys() {
    return new Set(entries.filter(matchesFilter).map(keyOf));
  }

  /* a sort lives only on a column the current layout draws: the th's own
     client rects decide that, never a breakpoint restated in the script */
  function sortColumnVisible(key) {
    const button = wrap.querySelector(`.th-sort[data-sort="${key}"]`);
    const column = button === null ? null : button.closest("th");
    return column !== null && column.getClientRects().length > 0;
  }

  /* the filter half: rows exist once, so a keystroke only toggles `hidden`
     on the nodes that are already in the table */
  function syncRows() {
    let shown = 0;
    for (const entry of entries) {
      const hit = matchesFilter(entry);
      rows.get(keyOf(entry)).tr.hidden = !hit;
      if (hit) shown += 1;
    }
    if (countLine) countLine.textContent = `${shown} of ${entries.length} models`;
  }

  /* the sort half: appending to a fragment moves the live rows, so one write
     reorders the whole table and no node is constructed. a rate sort reads the
     same printed value the cells carry, so peaking on or off reorders it */
  function reorderRows() {
    let ordered = entries;
    if (state.sort && state.dir) {
      // a stable sort keeps the export's own order inside every tie
      ordered = entries.slice().sort(compareOn(state.sort, state.dir, state.peak));
    }
    const fragment = document.createDocumentFragment();
    for (const entry of ordered) fragment.append(rows.get(keyOf(entry)).tr);
    body.replaceChildren(fragment);
  }

  /* the peak half of a row: the three rate cells print the entry's peak while
     the toggle is on, and the `peak` tag marks a row whose printed rate moved
     off its base. the name cell is rebuilt from its own stored nodes, so a
     flip never constructs a row */
  function syncRowPeak(row) {
    for (let index = 0; index < AXES.length; index += 1) {
      const axis = AXES[index][1];
      const value = state.peak ? peakRate(row.entry, axis) : rateOf(row.entry, axis);
      row.rateCells[index].textContent = formatRate(value);
    }
    const moved =
      state.peak &&
      AXES.some(([, axis]) => peakRate(row.entry, axis) !== rateOf(row.entry, axis));
    const children = [row.title];
    if (row.modalityTag !== null) children.push(" ", row.modalityTag);
    if (row.removedTag !== null) children.push(" ", row.removedTag);
    if (moved) children.push(" ", row.peakTag);
    children.push(row.sub);
    row.name.replaceChildren(...children);
  }

  function syncPeakControl() {
    peakToggle?.setAttribute("aria-pressed", String(Boolean(state.peak)));
    peakToggle?.classList.toggle("on", Boolean(state.peak));
  }

  function syncPeak() {
    for (const row of rows.values()) syncRowPeak(row);
    syncPeakControl();
  }

  function renderSession() {
    const day = state.day || todayUTC();
    const rows = [];
    for (const key of state.sel) {
      const entry = lookup.get(key);
      if (entry === undefined || !isChatPriced(entry)) continue;
      rows.push({ entry, total: priceSession(entry, day, state.calc, new Date(), state.mode) });
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

  /* the two controls the shipped component wears: the value span, the option
     marks and the root's own value mirror the state, so the fragment restore
     and a pick after it agree on what the eye reads */
  function syncDay() {
    if (dayValue) {
      dayValue.textContent = state.day === "" ? "today" : state.day;
      dayValue.classList.toggle("is-empty", state.day === "");
    }
  }

  function syncMode() {
    // standard is the label of the empty, mode-less request
    const label = state.mode === "" ? "standard" : state.mode;
    if (modeValue) modeValue.textContent = label;
    if (modeBox) modeBox.dataset.value = state.mode;
    for (const option of modeOptions) {
      option.setAttribute("aria-selected", String(option.textContent.trim() === label));
    }
  }

  function syncControls() {
    if (qBox) qBox.value = state.q;
    if (rateBox) rateBox.value = state.rate;
    for (const [field, box] of Object.entries(tokenBoxes)) {
      if (box) box.value = String(state.calc[field]);
    }
    syncDay();
    syncMode();
  }

  // a fragment restoring a sort on a column this layout hides would order
  // rows by a fact no reader can see: drop it and let the url follow
  if (state.sort !== "" && !sortColumnVisible(state.sort)) {
    state.sort = "";
    state.dir = "";
    push();
  }

  qBox?.addEventListener("input", () => {
    state.q = qBox.value;
    syncRows();
    push();
  });

  for (const [field, box] of Object.entries(tokenBoxes)) {
    box?.addEventListener("input", () => {
      state.calc[field] = tokenCount(box.value, 0);
      renderSession();
      push();
    });
  }

  rateBox?.addEventListener("input", () => {
    state.rate = Number(rateBox.value) > 0 && Number.isFinite(Number(rateBox.value)) ? rateBox.value : "";
    renderSession();
    push();
  });

  // the shipped select's change event carries the picked label in detail.value;
  // standard is the empty, mode-less request, so the gate resets anything the
  // option list does not offer
  modeBox?.addEventListener("change", (event) => {
    const label = event.detail && event.detail.value !== undefined ? String(event.detail.value) : "";
    state.mode = MODES.includes(label) ? label : "";
    syncMode();
    renderSession();
    push();
  });

  // the page owns the peak state; the controller's own toggle class flip lands
  // on the value this handler writes afterwards
  peakToggle?.addEventListener("click", () => {
    state.peak = !state.peak;
    syncPeak();
    reorderRows();
    showSelectedModel();
    push();
  });

  if (detail !== null) {
    for (const button of detail.card.querySelectorAll("[data-axis]")) {
      button.addEventListener("click", () => {
        const axis = button.dataset.axis;
        if (!CHART_AXES.includes(axis)) return;
        detail.axis = axis;
        for (const peer of detail.card.querySelectorAll("[data-axis]")) {
          peer.setAttribute("aria-pressed", peer === button ? "true" : "false");
        }
        if (state.model === "") return;
        const entry = lookup.get(state.model);
        if (entry !== undefined) drawChart(detail, entry, state.peak);
      });
    }
    detail.close?.addEventListener("click", () => clearModel());
  }

  /* set while the synthetic clicks below re-run the controller's cycle, so
     the events they emit never write page state */
  let cyclingSort = false;

  wrap.addEventListener("table:sort", (event) => {
    if (cyclingSort) return;
    const { key, dir } = event.detail;
    if (dir !== "none" && !sortColumnVisible(key)) {
      // a click on a column the layout hides cannot start a sort the reader
      // has no way to read: the same drop the init and resize paths run
      state.sort = "";
      state.dir = "";
    } else {
      state.sort = dir === "none" ? "" : key;
      state.dir = dir === "none" ? "" : dir;
    }
    reorderRows();
    syncAriaSort();
    push();
  });

  wrap.addEventListener("table:selection", (event) => {
    // a row a search is hiding keeps its membership: only the boxes on screen
    // speak for their own name, and the filter state is what decides on screen
    const shown = shownKeys();
    state.sel = [...new Set([...state.sel.filter((key) => !shown.has(key)), ...event.detail.selected])];
    renderSession();
    push();
  });

  /* one meaning per target: a click that missed a control opens the row's
     model, captured before the shipped controller's row handler can read it
     as a selection; the compare cell stays that handler's */
  wrap.addEventListener(
    "click",
    (event) => {
      const target = event.target;
      if (target === null || typeof target.closest !== "function") return;
      if (target.closest(".cell-select")) return;
      if (target.closest("button, a, input, select, textarea, label")) return;
      const key = target.closest("tr")?.querySelector(".model-button")?.dataset?.key;
      if (key === undefined || key === null) return;
      event.stopPropagation();
      selectModel(key);
    },
    true,
  );

  // the same reading on resize: a width change that hides the sorted column
  // drops the sort, since a reader on the new layout cannot see the fact it
  // orders by
  window.addEventListener?.("resize", () => {
    if (state.sort === "" || sortColumnVisible(state.sort)) return;
    const key = state.sort;
    // the controller's cycle lives in the vendored module's own memory, so it
    // has to be re-run to `none` here or the next click on this column would
    // step on from the stale direction; restoreSort drives the same cycle
    // through the same clicks
    const steps = state.dir === "desc" ? 1 : 2;
    state.sort = "";
    state.dir = "";
    const button = wrap.querySelector(`.th-sort[data-sort="${key}"]`);
    if (button !== null) {
      cyclingSort = true;
      try {
        for (let step = 0; step < steps; step += 1) button.click();
      } finally {
        cyclingSort = false;
      }
    }
    reorderRows();
    syncAriaSort();
    push();
  });

  /* the day picker is the page's own controller: the shipped module wires the
     select's menu and ships no daterange panel. the grid draws whole
     Monday-first weeks, the arrows walk a day across the month edge,
     PageUp/PageDown walk a month, and the panel opens on the month of the
     current value, today when the day is unset */
  if (dayRange !== null && dayBox !== null && dayPanel !== null) {
    const dayGrid = dayPanel.querySelector("#calc-day-grid");
    const dayMonth = dayPanel.querySelector("#calc-day-month");
    const dayToday = dayPanel.querySelector("#calc-day-today");
    const dayNav = dayPanel.querySelectorAll(".daterange-head .btn");
    const dayPrev = dayNav[0] ?? null;
    const dayNext = dayNav[1] ?? null;

    const MONTHS = [
      "january",
      "february",
      "march",
      "april",
      "may",
      "june",
      "july",
      "august",
      "september",
      "october",
      "november",
      "december",
    ];
    const monthOf = (day) => {
      const [year, month] = day.split("-").map(Number);
      return { year, month: month - 1 };
    };
    const monthKey = (view) => `${view.year}-${String(view.month + 1).padStart(2, "0")}`;
    // one calendar step; the month edge is Date.UTC's own rollover
    const moved = (day, offset) => {
      const [year, month, date] = day.split("-").map(Number);
      return new Date(Date.UTC(year, month - 1, date + offset)).toISOString().slice(0, 10);
    };

    let view = monthOf(todayUTC());
    let anchor = todayUTC();
    let closeTimer = 0;

    const renderGrid = () => {
      dayMonth.textContent = `${MONTHS[view.month]} ${view.year}`;
      const today = todayUTC();
      const key = monthKey(view);
      const fragment = document.createDocumentFragment();
      const days = monthGrid(view.year, view.month);
      for (let start = 0; start < days.length; start += 7) {
        const row = document.createElement("tr");
        for (const day of days.slice(start, start + 7)) {
          const cell = document.createElement("td");
          const button = document.createElement("button");
          button.type = "button";
          button.className = "daterange-day";
          button.dataset.day = day;
          if (!day.startsWith(`${key}-`)) button.classList.add("is-outside");
          if (day === today) button.setAttribute("aria-current", "date");
          if (day === state.day) button.classList.add("is-start", "is-end");
          button.tabIndex = day === anchor ? 0 : -1;
          button.textContent = String(Number(day.slice(8)));
          cell.append(button);
          row.append(cell);
        }
        fragment.append(row);
      }
      dayGrid.replaceChildren(fragment);
    };

    const focusAnchor = () => {
      const button = dayGrid.querySelector('[tabindex="0"]');
      if (button !== null) button.focus();
    };

    // the exit costume's own clock, read off the panel so a token change
    // retimes the hide without a number here
    const exitMs = () =>
      (parseFloat(getComputedStyle(dayPanel).animationDuration) || 0) * 1000 + 20;

    const open = () => {
      if (dayRange.classList.contains("open")) return;
      clearTimeout(closeTimer);
      dayRange.classList.remove("closing");
      anchor = state.day === "" ? todayUTC() : state.day;
      view = monthOf(anchor);
      renderGrid();
      dayPanel.hidden = false;
      // the flips measure the laid-out panel before the open costume draws it
      const rect = dayBox.getBoundingClientRect();
      const below = window.innerHeight - rect.bottom;
      dayRange.classList.toggle("daterange-up", below < dayPanel.offsetHeight + 8 && rect.top > below);
      dayRange.classList.toggle("daterange-end", rect.right + dayPanel.offsetWidth > window.innerWidth);
      dayRange.classList.add("open");
      dayBox.setAttribute("aria-expanded", "true");
      focusAnchor();
    };

    const close = ({ focus = false } = {}) => {
      if (!dayRange.classList.contains("open")) return;
      dayRange.classList.remove("open");
      dayRange.classList.add("closing");
      dayBox.setAttribute("aria-expanded", "false");
      clearTimeout(closeTimer);
      closeTimer = setTimeout(() => {
        dayRange.classList.remove("closing");
        dayPanel.hidden = true;
      }, exitMs());
      if (focus) dayBox.focus();
    };

    const pick = (day) => {
      state.day = isDay(day) ? day : "";
      syncDay();
      renderSession();
      push();
      close({ focus: true });
    };

    const stepDay = (offset) => {
      anchor = moved(anchor, offset);
      view = monthOf(anchor);
      renderGrid();
      focusAnchor();
    };

    const stepMonth = (offset) => {
      const at = new Date(`${anchor}T00:00:00Z`);
      const last = new Date(
        Date.UTC(at.getUTCFullYear(), at.getUTCMonth() + offset + 1, 0),
      ).getUTCDate();
      anchor = new Date(
        Date.UTC(at.getUTCFullYear(), at.getUTCMonth() + offset, Math.min(at.getUTCDate(), last)),
      ).toISOString().slice(0, 10);
      view = monthOf(anchor);
      renderGrid();
      focusAnchor();
    };

    dayBox.addEventListener("click", () => {
      if (dayRange.classList.contains("open")) close();
      else open();
    });

    dayPrev?.addEventListener("click", () => stepMonth(-1));
    dayNext?.addEventListener("click", () => stepMonth(1));

    dayGrid.addEventListener("click", (event) => {
      const button = event.target.closest(".daterange-day");
      if (button === null) return;
      anchor = button.dataset.day;
      pick(anchor);
    });

    // today is the empty default the calculator prices on, so the foot clears
    // the state rather than writing today's date into it
    dayToday?.addEventListener("click", () => {
      state.day = "";
      syncDay();
      renderSession();
      push();
      close({ focus: true });
    });

    dayPanel.addEventListener("keydown", (event) => {
      switch (event.key) {
        case "ArrowLeft":
          event.preventDefault();
          stepDay(-1);
          break;
        case "ArrowRight":
          event.preventDefault();
          stepDay(1);
          break;
        case "ArrowUp":
          event.preventDefault();
          stepDay(-7);
          break;
        case "ArrowDown":
          event.preventDefault();
          stepDay(7);
          break;
        case "PageUp":
          event.preventDefault();
          stepMonth(-1);
          break;
        case "PageDown":
          event.preventDefault();
          stepMonth(1);
          break;
        case "Enter":
        case " ": {
          if (event.target.matches(".daterange-day")) {
            event.preventDefault();
            pick(anchor);
          }
          break;
        }
        case "Escape":
          event.preventDefault();
          close({ focus: true });
          break;
      }
    });

    dayRange.addEventListener("focusout", (event) => {
      if (!dayRange.contains(event.relatedTarget)) close();
    });

    document.addEventListener("pointerdown", (event) => {
      if (!dayRange.contains(event.target)) close();
    });
  }

  syncControls();
  // build each row once: a filter toggles `hidden` on these nodes and a sort
  // reorders them, so no keystroke re-runs the per-row construction
  const rows = new Map(entries.map((entry) => [keyOf(entry), rowFor(entry)]));
  reorderRows();
  syncRows();
  // the fragment's peak key reprices the rows it restored
  syncPeak();
  // the rows exist from here on, so their line marks wire once; a chart
  // redraw keeps its own call for the groups it rebuilds
  wireLineMarks();
  syncAriaSort();
  syncModelCurrent();
  renderSession();
  lastHash = encodeState(state);

  restoreSort(state, wrap);
  showSelectedModel();

  // last, so nothing below it can leave the page reported ready
  reportReady(document, wrap);
}

if (typeof document !== "undefined") init();
