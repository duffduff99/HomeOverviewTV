import { h, icon, setIcon, weatherIcon, isNum, timeParts, fmtDate, setTimeOptions, resetFormatCache, friendly } from "./util.js";
import { Particles } from "./particles.js";
import { MusicPlayer } from "./music.js";
import { CameraView } from "./camera.js";
import * as weather from "./screens/weather.js";
import * as energy from "./screens/energy.js";
import * as cameras from "./screens/cameras.js";
import * as calendar from "./screens/calendar.js";
import * as tiles from "./screens/tiles.js";
import * as air from "./screens/air.js";

const SCREEN_TYPES = { weather, energy, cameras, calendar, tiles, air };
const $ = (sel) => document.querySelector(sel);

const app = {
  config: null, states: {}, data: {}, screens: new Map(), current: null,
  alerts: [], message: "", interrupt: null, theme: null, track: null,
};
const ctx = {
  get states() { return app.states; },
  get data() { return app.data; },
  get h12() { return app.config?.display?.time_format !== "24h"; },
  st: (id) => (id ? app.states[id] : undefined),
};

// ---------------------------------------------------------------- scaling
function fit() {
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  $("#stage").style.transform = `translate(-50%, -50%) scale(${scale})`;
}
window.addEventListener("resize", fit);
fit();

// ------------------------------------------------------------- websocket
let ws;
function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (ev) => handle(JSON.parse(ev.data));
  ws.onopen = () => setConnection(true);
  ws.onclose = () => { setConnection(false); setTimeout(connect, 3000); };
}
const send = (msg) => ws?.readyState === 1 && ws.send(JSON.stringify(msg));

function setConnection(ok, haOk = true) {
  const el = $("#conn");
  el.hidden = ok && haOk;
  el.textContent = !ok ? "Reconnecting to channel server…" : "Waiting for Home Assistant…";
}

function handle(msg) {
  switch (msg.type) {
    case "init":
      app.config = msg.config;
      app.states = msg.states || {};
      app.data = msg.data || {};
      app.alerts = msg.alerts || [];
      app.message = msg.message || "";
      setTimeOptions({ timezone: msg.config.timezone, ...msg.config.display });
      resetFormatCache();
      applyTheme(msg.theme);
      buildScreens();
      music.apply(msg.music);
      setScreen(msg.screen);
      setInterrupt(msg.interrupt);
      setConnection(true, msg.connected);
      renderAll();
      break;
    case "states":
      Object.assign(app.states, msg.states);
      for (const [k, v] of Object.entries(msg.states)) if (v == null) delete app.states[k];
      setConnection(true, true);
      renderAll();
      break;
    case "data":
      if (msg.id != null) app.data[msg.key] = { ...(app.data[msg.key] || {}), [msg.id]: msg.value };
      else app.data[msg.key] = msg.value;
      renderAll();
      break;
    case "screen": setScreen(msg.screen); break;
    case "theme": applyTheme(msg.theme); break;
    case "alerts": app.alerts = msg.alerts; renderAlerts(); break;
    case "message": app.message = msg.message; renderTicker(); break;
    case "interrupt": setInterrupt(msg.interrupt); break;
    case "music": music.apply(msg.music); break;
    case "music_cmd": if (msg.cmd === "skip") music.next(); break;
  }
}

// ----------------------------------------------------------------- theme
const particles = new Particles($("#particles"));
function applyTheme(theme) {
  if (!theme) return;
  app.theme = theme;
  const root = document.documentElement;
  const bg = $("#bg");
  bg.replaceChildren();
  bg.style.background = theme.background || "";
  if (theme.background_image) {
    bg.append(h("div.bg-image", { style: `background-image:url('${theme.base_url}${encodeURI(theme.background_image)}')` }));
  }
  if (theme.background_video) {
    const v = h("video.bg-video", { autoplay: true, muted: true, loop: true, playsinline: true, src: theme.base_url + encodeURI(theme.background_video) });
    v.muted = true;
    bg.append(v);
  }
  if (theme.decor) bg.append(h("div.bg-decor", { html: theme.decor }));
  bg.style.setProperty("--dim", theme.dim ?? 0.25);
  for (const [k, v] of Object.entries(theme.colors || {})) root.style.setProperty(`--${k}`, v);
  let link = $("#theme-css");
  if (theme.css) {
    if (!link) { link = h("link#theme-css", { rel: "stylesheet" }); link.id = "theme-css"; document.head.append(link); }
    link.href = theme.css;
  } else if (link) link.remove();
  document.body.dataset.theme = theme.id;
  particles.set(theme.particles, app.config?.display?.effects !== false);
}

// --------------------------------------------------------------- screens
function buildScreens() {
  for (const s of app.screens.values()) s.hide?.();
  app.screens.clear();
  app.current = null;
  const host = $("#screens");
  host.replaceChildren();
  const display = app.config.display || {};
  document.body.classList.toggle("no-effects", display.effects === false);
  $("#stage").style.setProperty("--safe-x", `${(display.safe_area ?? 3) * 19.2}px`);
  $("#stage").style.setProperty("--safe-y", `${(display.safe_area ?? 3) * 10.8}px`);
  $("#stage").style.setProperty("--fade", `${Math.max(0, Number(display.transition_seconds ?? 1))}s`);
  $("#brand-name").textContent = app.config.name;
  $("#brand-sub").textContent = app.config.subtitle;
  document.title = `${app.config.name} TV`;

  const pills = $("#pills");
  pills.replaceChildren();
  for (const cfg of app.config.screens) {
    const mod = SCREEN_TYPES[cfg.type];
    if (!mod) continue;
    try {
      const screen = mod.create(cfg, ctx);
      screen.cfg = cfg;
      screen.pill = h("div.pill", h("span.pill-label", cfg.title || cfg.type), h("span.pill-bar"));
      pills.append(screen.pill);
      host.append(screen.el);
      app.screens.set(cfg.id, screen);
    } catch (err) {
      console.error("Screen failed to build", cfg, err);
    }
  }
  if (!app.screens.size) {
    host.append(h("div.screen.is-active.empty-state", h("div.panel",
      h("h2", "No screens configured yet"), h("p", "Add screens to config.yaml - see config.example.yaml."))));
  }
}

function setScreen(info) {
  if (!info?.id) return;
  const next = app.screens.get(info.id);
  if (!next) return;
  const prev = app.current;
  if (prev !== next) {
    if (prev) {
      prev.el.classList.remove("is-active");
      prev.pill.classList.remove("is-active");
      const fadeMs = Math.max(0, Number(app.config.display?.transition_seconds ?? 1)) * 1000;
      setTimeout(() => { if (app.current !== prev) prev.hide?.(); }, fadeMs + 100);
    }
    next.el.classList.add("is-active");
    next.show?.();
  }
  app.current = next;
  try { next.update(ctx); } catch (e) { console.error(e); }
  // progress bar: restart animation for the remaining time
  next.pill.classList.remove("is-active");
  void next.pill.offsetWidth;
  next.pill.style.setProperty("--dur", `${info.remaining ?? info.duration}s`);
  next.pill.classList.add("is-active");
  renderTicker();
}

let renderQueued = false;
function renderAll() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderHeader();
    for (const s of app.screens.values()) {
      // only the visible screen (and the one fading out) need fresh numbers
      if (s === app.current || s.el.classList.contains("is-active")) {
        try { s.update(ctx); } catch (e) { console.error(e); }
      } else s.stale = true;
    }
    renderTicker();
    renderAlerts();
  });
}

// ---------------------------------------------------------------- header
function renderClock() {
  const now = new Date();
  const t = timeParts(now);
  $("#clock-time").textContent = t.time;
  $("#clock-period").textContent = t.period;
  $("#clock-date").textContent = fmtDate(now);
}
setInterval(renderClock, 1000);
renderClock();

function renderHeader() {
  const hdr = app.config?.header || {};
  const w = ctx.st(hdr.weather);
  const t = ctx.st(hdr.temperature);
  const night = ctx.st("sun.sun")?.state === "below_horizon";
  const box = $("#hdr-weather");
  box.hidden = !w && !t;
  if (w) setIcon($("#hdr-weather-icon"), weatherIcon(w.state, night));
  $("#hdr-weather-icon").hidden = !w;
  const temp = t && isNum(t.state) ? t.state : w?.attributes?.temperature;
  $("#hdr-temp").textContent = isNum(temp) ? `${Math.round(Number(temp))}°` : "";
}

// ------------------------------------------------------- lower third ticker
let tickerItems = [], tickerIndex = 0, tickerKey = "";
function buildTickerItems() {
  const items = [];
  for (const mp of app.config?.now_playing?.media_players || []) {
    const st = ctx.st(mp.entity);
    if (!st || st.state !== "playing") continue;
    const a = st.attributes || {};
    const title = a.media_title || a.media_channel || a.app_name;
    if (!title) continue;
    items.push({ kind: "playing", tag: "Now Playing", icon: "radio", title, sub: [a.media_artist || a.media_album_name, `on ${mp.name || friendly(st)}`].filter(Boolean).join("  ·  "), art: a.entity_picture });
  }
  if (app.message) items.push({ kind: "message", tag: "Message", icon: "message", title: app.message });
  return items;
}
function renderTicker() {
  if (!app.config) return;
  const items = buildTickerItems();
  const key = JSON.stringify(items);
  if (key !== tickerKey) {
    tickerKey = key;
    tickerItems = items;
    if (tickerIndex >= items.length) tickerIndex = 0;
    showTickerItem();
  }
  const tr = app.track;
  $("#bgm").hidden = !tr;
  if (tr) $("#bgm-title").textContent = [tr.title, tr.artist].filter(Boolean).join(" — ");
}
function upNextItem() {
  const ids = [...app.screens.keys()];
  if (ids.length < 2 || !app.current) return null;
  const nxt = app.screens.get(ids[(ids.indexOf(app.current.cfg.id) + 1) % ids.length]);
  return { kind: "next", tag: "Up Next", icon: "info", title: nxt.cfg.title || nxt.cfg.type, sub: app.config.name };
}
function showTickerItem() {
  const item = tickerItems[tickerIndex] || upNextItem();
  const box = $("#ticker-item");
  if (!item) { box.replaceChildren(); return; }
  $("#ticker-tag-label").textContent = item.tag;
  setIcon($("#ticker-tag-icon"), item.icon);
  $("#ticker-tag").dataset.kind = item.kind;
  const content = h("div.ticker-content",
    item.art ? h("img.ticker-art", { src: item.art, alt: "" }) : null,
    h("div.ticker-text", h("div.ticker-title", item.title), item.sub ? h("div.ticker-sub", item.sub) : null));
  box.replaceChildren(content);
}
setInterval(() => {
  if (tickerItems.length > 1) { tickerIndex = (tickerIndex + 1) % tickerItems.length; showTickerItem(); }
  else if (!tickerItems.length) showTickerItem();
}, 9000);

// ----------------------------------------------------------------- alerts
let alertKey = "";
function renderAlerts() {
  const key = JSON.stringify(app.alerts);
  if (key === alertKey) return;
  alertKey = key;
  const band = $("#alert");
  band.hidden = !app.alerts.length;
  document.body.classList.toggle("has-alert", app.alerts.length > 0);
  if (!app.alerts.length) return;
  band.dataset.level = app.alerts.some((a) => a.level === "critical") ? "critical" : "warning";
  const text = app.alerts.map((a) => a.text).join("     •     ");
  const track = $("#alert-track");
  track.replaceChildren(h("span", text), h("span", { "aria-hidden": "true" }, text));
  track.style.animationDuration = `${Math.max(14, text.length * 0.22)}s`;
}

// -------------------------------------------------------------- interrupt
let interruptCam = null;
function setInterrupt(info) {
  const box = $("#interrupt");
  if (interruptCam) { interruptCam.stop(); interruptCam = null; }
  app.interrupt = info;
  box.hidden = !info;
  document.body.classList.toggle("has-interrupt", !!info);
  music.duck(!!info);
  if (app.current?.cfg.type === "cameras") info ? app.current.hide?.() : app.current.show?.();
  if (!info) return;
  interruptCam = new CameraView(info.camera, info.title, { mode: "live", interval: 2 });
  const remaining = Math.max(1, (info.until ? info.until * 1000 - Date.now() : info.duration * 1000) / 1000);
  const bar = h("div.int-bar");
  bar.style.animationDuration = `${remaining}s`;
  box.replaceChildren(interruptCam.el,
    h("div.int-banner", h("span.int-dot"), icon("bell", "int-icon"), h("span", info.title)), bar);
  interruptCam.start();
}

// ------------------------------------------------------------------ music
const music = new MusicPlayer((track) => {
  app.track = track ? { title: track.title, artist: track.artist } : null;
  renderTicker();
  send({ type: "track", track: app.track });
});

connect();
