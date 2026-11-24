import { h, icon, num, isNum, power, watts, friendly } from "../util.js";
import { gauge } from "./air.js";

// "Inside": thermostat, room temperatures, ERV, indoor air quality, and
// optional duct temperatures / equipment power.

const MODES = { heat: "Heat", cool: "Cool", heat_cool: "Heat / Cool", auto: "Auto", off: "Off",
  fan_only: "Fan only", dry: "Dry" };
const ACTIONS = { heating: "Heating", cooling: "Cooling", idle: "Idle", off: "Off", fan: "Fan running",
  drying: "Drying", preheating: "Preheating", defrosting: "Defrosting" };
const ON_STATES = new Set(["on", "true", "open", "running", "home", "active", "heating", "cooling"]);

const deg = (v, digits = 0) => (isNum(v) ? `${num(v, digits)}°` : "—");
const title = (s) => (s ? String(s).replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "—");

function onOff(st) {
  if (!st || ["unknown", "unavailable"].includes(st.state)) return null;
  if (isNum(st.state)) return Number(st.state) > 0;
  return ON_STATES.has(String(st.state).toLowerCase());
}

export function create(cfg) {
  const ref = {};

  // --- thermostat
  ref.mode = h("span.hvac-mode");
  ref.current = h("div.hvac-current");
  ref.target = h("div.hvac-target");
  ref.extra = h("div.hvac-extra");
  const hvac = cfg.climate ? h("div.panel.hvac-panel",
    h("div.panel-head", h("div.panel-title", "Thermostat"), ref.mode),
    h("div.hvac-main", icon("thermometer", "hvac-icon"), h("div", ref.current, ref.target)),
    ref.extra) : null;

  // --- ERV
  const erv = cfg.erv || {};
  const chip = (label) => ({ label, el: h("span.state-chip", label) });
  ref.ervMode = h("div.erv-mode");
  ref.ervRun = chip("Running");
  ref.ervBoost = chip("Boost");
  const ervPanel = (erv.mode || erv.status || erv.boost) ? h("div.panel.erv-panel",
    h("div.panel-title", erv.name || "Ventilation"),
    h("div.erv-row", icon("air", "erv-icon"),
      h("div", h("span.metric-label", "Mode"), ref.ervMode)),
    h("div.erv-chips", erv.status ? ref.ervRun.el : null, erv.boost ? ref.ervBoost.el : null)) : null;

  // --- rooms
  ref.humidity = h("span.rooms-humidity");
  const rooms = (cfg.rooms || []).map((r) => ({
    r, temp: h("span.room-temp"), hum: h("span.room-hum"),
  }));
  const roomsPanel = rooms.length || cfg.humidity ? h("div.panel.rooms-panel",
    h("div.panel-head", h("div.panel-title", "Rooms"), ref.humidity),
    h("div.room-list", rooms.map((x) => h("div.room",
      h("span.room-name", x.r.name || friendly(null, x.r.temperature)), x.temp, x.hum)))) : null;

  // --- equipment (duct temperatures, power)
  const rows = [
    ...(cfg.duct_temps || []).map((t) => ({ t, kind: "temp", value: h("span.equip-value") })),
    ...(cfg.equipment_power || []).map((t) => ({ t, kind: "power", value: h("span.equip-value") })),
  ];
  const equipPanel = rows.length ? h("div.panel.equip-panel",
    h("div.panel-title", "Equipment"),
    h("div.equip-list", rows.map((x) => h("div.equip-row",
      icon(x.kind === "temp" ? "thermometer" : "flash", "equip-icon"),
      h("span.equip-name", x.t.name || x.t.entity), x.value)))) : null;

  // --- indoor air quality
  const gauges = (cfg.air_gauges || []).map(gauge);
  const airPanel = gauges.length ? h(`div.panel.indoor-air.n${gauges.length}`,
    h("div.panel-title", "Indoor air quality"),
    h("div.indoor-air-grid", gauges.map((g) => g.el))) : null;

  const el = h("section.screen.screen-indoor",
    hvac || ervPanel ? h("div.indoor-col", hvac, ervPanel) : null,
    roomsPanel || equipPanel ? h("div.indoor-col", roomsPanel, equipPanel) : null,
    airPanel);

  function update(c) {
    if (hvac) {
      const st = c.st(cfg.climate);
      const a = st?.attributes || {};
      const mode = st?.state;
      ref.mode.textContent = MODES[mode] || title(mode);
      ref.mode.dataset.mode = mode || "";
      ref.current.textContent = deg(a.current_temperature, 0);
      const action = ACTIONS[a.hvac_action] || (a.hvac_action ? title(a.hvac_action) : null);
      let target = "";
      if (isNum(a.target_temp_low) && isNum(a.target_temp_high)) target = `${deg(a.target_temp_low)} – ${deg(a.target_temp_high)}`;
      else if (isNum(a.temperature)) target = deg(a.temperature);
      ref.target.textContent = mode === "off" ? "System off"
        : [action, target ? `set to ${target}` : null].filter(Boolean).join(" · ");
      ref.target.dataset.action = a.hvac_action || "";
      const extra = [a.fan_mode ? `Fan ${String(a.fan_mode).toLowerCase()}` : null,
        isNum(a.current_humidity) ? `${num(a.current_humidity, 0)}% humidity` : null].filter(Boolean);
      ref.extra.textContent = extra.join("  ·  ");
    }
    if (ervPanel) {
      ref.ervMode.textContent = erv.mode ? title(c.st(erv.mode)?.state) : "—";
      for (const [x, ent] of [[ref.ervRun, erv.status], [ref.ervBoost, erv.boost]]) {
        if (!ent) continue;
        const on = onOff(c.st(ent));
        x.el.textContent = `${x.label}: ${on == null ? "—" : on ? "On" : "Off"}`;
        x.el.classList.toggle("is-on", on === true);
      }
    }
    if (roomsPanel) {
      const hum = c.st(cfg.humidity);
      ref.humidity.textContent = hum && isNum(hum.state) ? `${num(hum.state, 0)}% humidity` : "";
      for (const x of rooms) {
        x.temp.textContent = deg(c.st(x.r.temperature)?.state, 1);
        const rh = c.st(x.r.humidity);
        x.hum.textContent = rh && isNum(rh.state) ? `${num(rh.state, 0)}%` : "";
      }
    }
    for (const x of rows) {
      const st = c.st(x.t.entity);
      if (x.kind === "temp") x.value.textContent = deg(st?.state, 0);
      else { const p = power(watts(st)); x.value.textContent = p.unit ? `${p.value} ${p.unit}` : "—"; }
    }
    gauges.forEach((g) => g.update(c));
  }
  return { el, update };
}
