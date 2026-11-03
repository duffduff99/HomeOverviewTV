import { h, icon, setIcon, power, watts, num, isNum, hourOf, friendly } from "../util.js";
import { hourlyBars, dayArea } from "../charts.js";
import { tileGrid } from "./tiles.js";

const W = 760, H = 600;
const CENTER = { x: W / 2, y: H / 2 };
const NODES = {
  solar: { x: W / 2, y: 92, label: "Solar", icon: "solar" },
  grid: { x: 100, y: H / 2, label: "Grid", icon: "grid" },
  home: { x: W - 100, y: H / 2, label: "Home", icon: "home" },
  battery: { x: W / 2, y: H - 92, label: "Battery", icon: "battery" },
};
const R = 78;
const SVGNS = "http://www.w3.org/2000/svg";

function spoke(key) {
  const n = NODES[key];
  const dx = CENTER.x - n.x, dy = CENTER.y - n.y;
  const len = Math.hypot(dx, dy);
  const sx = n.x + (dx / len) * (R + 8), sy = n.y + (dy / len) * (R + 8);
  const path = document.createElementNS(SVGNS, "path");
  path.setAttribute("d", `M${sx},${sy} L${CENTER.x},${CENTER.y}`);
  path.setAttribute("class", `spoke spoke-${key}`);
  const dots = document.createElementNS(SVGNS, "path");
  dots.setAttribute("d", `M${sx},${sy} L${CENTER.x},${CENTER.y}`);
  dots.setAttribute("class", `flow flow-${key}`);
  return { path, dots };
}

export function create(cfg, ctx) {
  const p = cfg.power || {};
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "flow-svg");
  const spokes = {};
  for (const key of Object.keys(NODES)) {
    spokes[key] = spoke(key);
    svg.append(spokes[key].path, spokes[key].dots);
  }
  const hubDot = document.createElementNS(SVGNS, "circle");
  hubDot.setAttribute("cx", CENTER.x); hubDot.setAttribute("cy", CENTER.y); hubDot.setAttribute("r", 10);
  hubDot.setAttribute("class", "flow-hub");
  svg.append(hubDot);

  const nodes = {};
  for (const [key, n] of Object.entries(NODES)) {
    const ref = { value: h("span.node-value"), unit: h("span.node-unit"), sub: h("div.node-sub") };
    ref.el = h(`div.node.node-${key}`, { style: `left:${n.x - R}px;top:${n.y - R}px` },
      icon(n.icon, "node-icon"), h("div.node-reading", ref.value, ref.unit),
      h("div.node-label", n.label), ref.sub);
    if (key === "battery") {
      ref.ring = h("div.soc-ring");
      ref.el.prepend(ref.ring);
    }
    nodes[key] = ref;
  }
  const flow = h("div.flow", svg, Object.values(nodes).map((n) => n.el));

  const stat = (key, label, cls) => {
    const value = h("span.stat-value"), unit = h("span.stat-unit");
    return { key, value, unit, el: h(`div.stat.${cls || key}`, h("div.stat-label", label), h("div", value, unit)) };
  };
  const stats = [stat("solar", "Produced today", "c-solar"), stat("home", "Used today", "c-home"),
    stat("grid_in", "From grid", "c-grid"), stat("grid_out", "To grid", "c-grid"),
    stat("self_powered", "Self-powered", "c-battery")];
  const chartBox = h("div.chart-box");
  const socBox = h("div.chart-box.soc-box");
  const legend = h("div.legend",
    h("span.legend-item", h("i.sw.sw-solar"), "Solar"),
    h("span.legend-item", h("i.sw.sw-home"), "Home use"));
  const extra = tileGrid(cfg.tiles || [], "tiles-row");

  const el = h("section.screen.screen-energy",
    h("div.panel.flow-panel", flow, (cfg.tiles || []).length ? extra.el : null),
    h("div.energy-side",
      h("div.stats-row", stats.map((x) => x.el)),
      h("div.panel.chart-panel", h("div.panel-head", h("div.panel-title", "Today by hour · kWh"), legend), chartBox),
      p.battery_soc ? h("div.panel.soc-panel", h("div.panel-title", "Battery charge today"), socBox) : null,
    ),
  );

  let lastEnergy, lastHist, lastHour;
  function update(c) {
    const get = (k) => watts(c.st(p[k]));
    const solar = Math.max(0, get("solar") ?? 0);
    let battery = get("battery");
    let grid = get("grid");
    if (battery != null && p.battery_invert) battery = -battery;
    if (grid != null && p.grid_invert) grid = -grid;
    let home = get("home");
    if (home == null) home = solar + (grid ?? 0) + (battery ?? 0);

    const show = (key, w, sub) => {
      const pw = power(w);
      nodes[key].value.textContent = pw.value;
      nodes[key].unit.textContent = pw.unit;
      nodes[key].sub.textContent = sub || "";
      nodes[key].el.classList.toggle("is-missing", w == null);
    };
    show("solar", p.solar ? solar : null, "");
    show("home", home, "");
    show("grid", grid == null ? null : Math.abs(grid),
      grid == null ? "" : grid > 20 ? "Importing" : grid < -20 ? "Exporting" : "Idle");
    show("battery", battery == null ? null : Math.abs(battery),
      battery == null ? "" : battery > 20 ? "Discharging" : battery < -20 ? "Charging" : "Idle");

    const socSt = c.st(p.battery_soc);
    const soc = socSt && isNum(socSt.state) ? Number(socSt.state) : null;
    if (nodes.battery.ring) {
      nodes.battery.ring.style.setProperty("--soc", soc ?? 0);
      if (soc != null) nodes.battery.sub.textContent = `${Math.round(soc)}% · ${nodes.battery.sub.textContent}`;
    }
    // direction: "in" flows toward the centre, "out" flows away from it
    const setFlow = (key, w, inward) => {
      const active = w != null && Math.abs(w) > 20;
      const d = spokes[key].dots;
      d.classList.toggle("active", active);
      d.classList.toggle("reverse", active && !inward);
      const speed = active ? Math.max(0.5, 2.6 - Math.log10(Math.abs(w)) * 0.5) : 0;
      d.style.animationDuration = `${speed}s`;
      spokes[key].path.classList.toggle("active", active);
    };
    setFlow("solar", solar, true);
    setFlow("grid", grid, (grid ?? 0) > 0);
    setFlow("battery", battery, (battery ?? 0) > 0);
    setFlow("home", home, false);

    const e = c.data.energy;
    if (e !== lastEnergy) {
      for (const s of stats) {
        const v = e?.totals?.[s.key];
        if (s.key === "self_powered") {
          s.value.textContent = v == null ? "—" : Math.round(v);
          s.unit.textContent = v == null ? "" : "%";
        } else {
          s.value.textContent = v == null ? "—" : num(v, v >= 100 ? 0 : 1);
          s.unit.textContent = v == null ? "" : "kWh";
        }
        s.el.hidden = e && e.has && s.key.startsWith("grid") && !e.has[s.key];
      }
    }
    const hour = hourOf(new Date());
    if (e !== lastEnergy || hour !== lastHour) {
      lastEnergy = e; lastHour = hour;
      chartBox.replaceChildren(e
        ? hourlyBars(1000, 360, [
          { label: "Solar", color: "var(--series-solar)", values: e.hourly.solar },
          { label: "Home", color: "var(--series-home)", values: e.hourly.home }],
        { currentHour: hour, h12: c.h12 })
        : h("div.empty", "Waiting for Energy dashboard data…"));
    }
    const hist = c.data.history?.[p.battery_soc];
    if (p.battery_soc && hist !== lastHist) {
      lastHist = hist;
      socBox.replaceChildren(dayArea(1000, 170, hist || [], { color: "var(--battery)", h12: c.h12 }));
    }
    extra.update(c);
  }
  return { el, update };
}
