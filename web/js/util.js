import { ICONS } from "./icons-data.js";

/** Create an element: h("div.card.big", {style: "..."}, child, "text") */
export function h(tag, attrs, ...children) {
  const [name, ...classes] = tag.split(".");
  const el = document.createElement(name || "div");
  if (classes.length) el.className = classes.join(" ");
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "html") el.innerHTML = v;
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function icon(name, cls = "") {
  const path = ICONS[name] || ICONS.info;
  const span = document.createElement("span");
  span.className = `icon ${cls}`.trim();
  span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
  return span;
}

export function setIcon(el, name) {
  const path = ICONS[name] || ICONS.info;
  const p = el.querySelector("path");
  if (p && p.getAttribute("d") !== path) p.setAttribute("d", path);
}

const WEATHER_ICONS = {
  "clear-night": "night", cloudy: "cloudy", exceptional: "exceptional", fog: "fog",
  hail: "hail", lightning: "lightning", "lightning-rainy": "lightningRainy",
  partlycloudy: "partly", pouring: "pouring", rainy: "rainy", snowy: "snowy",
  "snowy-rainy": "snowyRainy", sunny: "sun", windy: "windy", "windy-variant": "windyVariant",
};
const WEATHER_LABELS = {
  "clear-night": "Clear", cloudy: "Cloudy", exceptional: "Exceptional", fog: "Foggy",
  hail: "Hail", lightning: "Thunderstorms", "lightning-rainy": "Thunderstorms",
  partlycloudy: "Partly Cloudy", pouring: "Heavy Rain", rainy: "Rain", snowy: "Snow",
  "snowy-rainy": "Sleet", sunny: "Sunny", windy: "Windy", "windy-variant": "Windy",
};
export const weatherIcon = (cond, night = false) =>
  night && cond === "partlycloudy" ? "partlyNight" : night && cond === "sunny" ? "night" : WEATHER_ICONS[cond] || "cloudy";
export const weatherLabel = (cond) => WEATHER_LABELS[cond] || (cond ? String(cond).replace(/-/g, " ") : "—");

export const isNum = (v) => v !== null && v !== "" && !isNaN(Number(v));

/** Format a number with sensible precision. */
export function num(v, digits) {
  if (!isNum(v)) return "—";
  const n = Number(v);
  const d = digits ?? (Math.abs(n) >= 100 ? 0 : Math.abs(n) >= 10 ? 1 : 1);
  return n.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 });
}

/** Watts -> "3.42 kW" / "640 W" split into value + unit. */
export function power(w) {
  if (!isNum(w)) return { value: "—", unit: "" };
  const n = Math.abs(Number(w));
  if (n >= 1000) return { value: (n / 1000).toFixed(n >= 10000 ? 1 : 2), unit: "kW" };
  return { value: Math.round(n).toString(), unit: "W" };
}

/** Power entity state to watts, honouring kW units. */
export function watts(st) {
  if (!st || !isNum(st.state)) return null;
  const unit = (st.attributes?.unit_of_measurement || "W").toLowerCase();
  const n = Number(st.state);
  return unit === "kw" ? n * 1000 : unit === "mw" ? n * 1e6 : n;
}

export function friendly(st, fallback) {
  return st?.attributes?.friendly_name || fallback || st?.entity_id || "";
}

/** Value + unit for a generic tile. */
export function stateParts(st) {
  if (!st) return { value: "—", unit: "" };
  const unit = st.attributes?.unit_of_measurement || "";
  if (isNum(st.state)) return { value: num(st.state), unit };
  if (["unknown", "unavailable"].includes(st.state)) return { value: "—", unit: "" };
  const s = String(st.state);
  return { value: s.length <= 3 ? s.toUpperCase() : s.charAt(0).toUpperCase() + s.slice(1), unit };
}

let TZ, LOCALE = "en-US", H12 = true;
export function setTimeOptions({ timezone, locale, time_format }) {
  TZ = timezone || undefined;
  LOCALE = locale || "en-US";
  H12 = time_format !== "24h";
}
const fmtCache = new Map();
function fmt(opts) {
  const key = JSON.stringify(opts);
  if (!fmtCache.has(key)) {
    try { fmtCache.set(key, new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, ...opts })); }
    catch { fmtCache.set(key, new Intl.DateTimeFormat(LOCALE, opts)); }
  }
  return fmtCache.get(key);
}
export const resetFormatCache = () => fmtCache.clear();
export function timeParts(d = new Date()) {
  const parts = fmt({ hour: "numeric", minute: "2-digit", hour12: H12 }).formatToParts(d);
  const time = parts.filter((p) => p.type !== "dayPeriod").map((p) => p.value).join("").trim();
  const period = parts.find((p) => p.type === "dayPeriod")?.value || "";
  return { time, period };
}
export const fmtTime = (d) => { const t = timeParts(d); return t.period ? `${t.time} ${t.period}` : t.time; };
export const fmtDate = (d, opts) => fmt(opts || { weekday: "long", month: "long", day: "numeric" }).format(d);
export const dayKey = (d) => fmt({ year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
export const hourOf = (d) => Number(fmt({ hour: "numeric", hour12: false }).format(d)) % 24;

/** Moon phase from the date (no sensor needed). */
export function moonPhase(date = new Date()) {
  const synodic = 29.530588853;
  const known = Date.UTC(2000, 0, 6, 18, 14) / 86400000;
  let age = (date.getTime() / 86400000 - known) % synodic;
  if (age < 0) age += synodic;
  const frac = age / synodic;
  const names = ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"];
  const illum = (1 - Math.cos(2 * Math.PI * frac)) / 2;
  return { frac, name: names[Math.round(frac * 8) % 8], illumination: Math.round(illum * 100) };
}

/** US EPA AQI category. Accepts an AQI value, or PM2.5 in µg/m³ (converted). */
const PM25_BP = [[0, 9, 0, 50], [9.1, 35.4, 51, 100], [35.5, 55.4, 101, 150],
  [55.5, 125.4, 151, 200], [125.5, 225.4, 201, 300], [225.5, 500, 301, 500]];
export function aqiInfo(st) {
  if (!st || !isNum(st.state)) return null;
  let value = Number(st.state);
  const unit = st.attributes?.unit_of_measurement || "";
  let pm = null;
  if (/µg|ug/i.test(unit)) {
    pm = value;
    const bp = PM25_BP.find(([lo, hi]) => value <= hi) || PM25_BP[PM25_BP.length - 1];
    value = Math.round(((bp[3] - bp[2]) / (bp[1] - bp[0])) * (Math.min(value, bp[1]) - bp[0]) + bp[2]);
  }
  const levels = [[50, "Good", "good"], [100, "Moderate", "moderate"], [150, "Unhealthy for Sensitive Groups", "usg"],
    [200, "Unhealthy", "unhealthy"], [300, "Very Unhealthy", "very"], [Infinity, "Hazardous", "hazard"]];
  const [, label, level] = levels.find(([max]) => value <= max);
  return { value, label, level, pm };
}
