import { h, icon, num, isNum, aqiInfo, friendly } from "../util.js";

// Health bands per measurement. Labels always accompany colours.
// PM thresholds follow the US EPA (2024) AQI breakpoints; PM1 has no official
// standard so it borrows the PM2.5 bands. VOC/NOx are Sensirion index values
// (100 = typical for VOC, 1 = typical for NOx). CO2 bands are common indoor/outdoor guidance.
const KINDS = {
  pm25: { name: "PM2.5", unit: "µg/m³", max: 75, bands: [[9, "Good", "good"], [35.4, "Moderate", "moderate"], [55.4, "Sensitive", "usg"], [125.4, "Unhealthy", "unhealthy"], [225.4, "Very unhealthy", "very"], [Infinity, "Hazardous", "hazard"]] },
  pm10: { name: "PM10", unit: "µg/m³", max: 200, bands: [[54, "Good", "good"], [154, "Moderate", "moderate"], [254, "Sensitive", "usg"], [354, "Unhealthy", "unhealthy"], [424, "Very unhealthy", "very"], [Infinity, "Hazardous", "hazard"]] },
  pm1: { name: "PM1", unit: "µg/m³", max: 75, bands: [[9, "Good", "good"], [35.4, "Moderate", "moderate"], [55.4, "Sensitive", "usg"], [125.4, "Unhealthy", "unhealthy"], [Infinity, "Very unhealthy", "very"]] },
  voc: { name: "VOC index", unit: "", max: 500, bands: [[150, "Good", "good"], [250, "Moderate", "moderate"], [400, "Unhealthy", "unhealthy"], [Infinity, "Very unhealthy", "very"]] },
  nox: { name: "NOx index", unit: "", max: 500, bands: [[20, "Good", "good"], [150, "Moderate", "moderate"], [300, "Unhealthy", "unhealthy"], [Infinity, "Very unhealthy", "very"]] },
  co2: { name: "CO₂", unit: "ppm", min: 400, max: 2000, bands: [[800, "Good", "good"], [1000, "Moderate", "moderate"], [1500, "Poor", "usg"], [2000, "Unhealthy", "unhealthy"], [Infinity, "Very unhealthy", "very"]] },
  pm03: { name: "PM0.3", unit: "particles/dL", max: 3000, bands: null },
  other: { name: "", unit: "", max: 100, bands: null },
};

const R = 88, CX = 110, CY = 104, LEN = Math.PI * R;
const arc = `M${CX - R},${CY} A${R},${R} 0 0 1 ${CX + R},${CY}`;

function gauge(g) {
  const kind = KINDS[g.kind] || KINDS.other;
  const ref = {
    value: h("span.g-value"), unit: h("span.g-unit"), level: h("div.g-level"),
    svg: h("div.g-svg", { html: `<svg viewBox="0 0 220 120"><path class="g-track" d="${arc}"/><path class="g-fill" d="${arc}" stroke-dasharray="0 ${LEN}"/></svg>` }),
  };
  ref.fill = ref.svg.querySelector(".g-fill");
  ref.el = h("div.gauge", ref.svg,
    h("div.g-readout", ref.value, ref.unit),
    h("div.g-name", g.name || kind.name), ref.level);
  return {
    update(c) {
      const st = c.st(g.entity);
      const v = st && isNum(st.state) ? Number(st.state) : null;
      ref.value.textContent = v == null ? "—" : num(v, v >= 100 ? 0 : 1);
      ref.unit.textContent = g.unit ?? st?.attributes?.unit_of_measurement ?? kind.unit;
      if (!g.name && !kind.name) ref.el.querySelector(".g-name").textContent = friendly(st, g.entity);
      const min = g.min ?? kind.min ?? 0, max = g.max ?? kind.max;
      const frac = v == null ? 0 : Math.max(0.02, Math.min(1, (v - min) / (max - min)));
      ref.fill.setAttribute("stroke-dasharray", `${(frac * LEN).toFixed(1)} ${LEN}`);
      const band = v == null || !kind.bands ? null : kind.bands.find(([lim]) => v <= lim);
      ref.el.dataset.level = band ? band[2] : "neutral";
      ref.level.textContent = band ? band[1] : "";
    },
    el: ref.el,
  };
}

export function create(cfg) {
  const gauges = (cfg.gauges || []).map(gauge);
  const pm25 = cfg.pm25 || (cfg.gauges || []).find((g) => g.kind === "pm25")?.entity;
  const hero = { value: h("div.air-aqi"), label: h("div.air-label"), note: h("div.air-note"), icon: icon("air", "air-icon"),
    marker: h("span.aqi-marker") };
  hero.scale = h("div.aqi-scale.air-scale", ...["good", "moderate", "usg", "unhealthy", "very", "hazard"].map((l) => h(`span.lvl-${l}`)), hero.marker);
  const extras = (cfg.tiles || []).map((t) => ({ t, value: h("span.metric-value"), unit: h("span.metric-sub") }));
  const el = h("section.screen.screen-air",
    pm25 ? h("div.panel.air-hero",
      h("div.panel-title", "Air Quality Index"),
      h("div.air-hero-main", hero.icon, hero.value),
      hero.label, hero.scale, hero.note,
      extras.length ? h("div.air-extras", extras.map((x) => h("div.metric",
        h("div.metric-body", h("span.metric-label", x.t.name || ""), h("div", x.value, x.unit))))) : null,
    ) : null,
    h(`div.panel.air-gauges.n${Math.min(gauges.length, 6)}`, gauges.map((g) => g.el)),
  );
  return {
    el,
    update(c) {
      gauges.forEach((g) => g.update(c));
      if (pm25) {
        const info = aqiInfo({ ...c.st(pm25), attributes: { unit_of_measurement: "µg/m³" } });
        hero.value.textContent = info ? info.value : "—";
        hero.label.textContent = info ? info.label : "";
        hero.el = hero.el || el.querySelector(".air-hero");
        hero.el.dataset.level = info?.level || "";
        hero.note.textContent = "Calculated from current PM2.5 (US EPA scale)";
        hero.marker.style.left = info ? `${Math.min(100, (info.value / 300) * 100)}%` : "-100px";
      }
      for (const x of extras) {
        const st = c.st(x.t.entity);
        x.value.textContent = st && isNum(st.state) ? num(st.state) : st?.state ?? "—";
        x.unit.textContent = x.t.unit ?? st?.attributes?.unit_of_measurement ?? "";
      }
    },
  };
}
