// Small hand-written SVG charts (no library) sized for a 1080p TV.
const NS = "http://www.w3.org/2000/svg";
const s = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};

function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
}

const hourLabel = (h, h12) => h12 ? `${h % 12 || 12}${h < 12 ? "a" : "p"}` : `${String(h).padStart(2, "0")}`;

/**
 * Grouped hourly bar chart.
 * series: [{label, color, values[24]}]; currentHour highlights "now".
 */
export function hourlyBars(width, height, series, { currentHour = null, unit = "kWh", h12 = true } = {}) {
  const pad = { l: 56, r: 12, t: 16, b: 40 };
  const w = width - pad.l - pad.r;
  const hgt = height - pad.t - pad.b;
  const max = niceMax(Math.max(0.1, ...series.flatMap((x) => x.values)));
  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart" });
  const y = (v) => pad.t + hgt - (v / max) * hgt;

  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    svg.append(s("line", { x1: pad.l, x2: width - pad.r, y1: y(v), y2: y(v), class: i ? "grid" : "axis" }));
    const t = s("text", { x: pad.l - 12, y: y(v) + 7, class: "tick", "text-anchor": "end" });
    t.textContent = +v.toFixed(2);
    if (i) svg.append(t);
  }
  const slot = w / 24;
  const gap = 2;
  const barW = Math.max(3, (slot - 8) / series.length - gap);
  if (currentHour != null) {
    svg.append(s("rect", { x: pad.l + currentHour * slot, y: pad.t, width: slot, height: hgt, class: "now-band" }));
  }
  for (let hr = 0; hr < 24; hr++) {
    series.forEach((ser, i) => {
      const v = ser.values[hr] || 0;
      if (v <= 0) return;
      const x = pad.l + hr * slot + 4 + i * (barW + gap);
      const top = y(v);
      const bh = Math.max(2, pad.t + hgt - top);
      const r = Math.min(4, barW / 2, bh);
      // rounded data end, square at the baseline
      const d = `M${x},${pad.t + hgt} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${pad.t + hgt} Z`;
      svg.append(s("path", { d, fill: ser.color, opacity: currentHour != null && hr > currentHour ? 0.35 : 1 }));
    });
    if (hr % 3 === 0) {
      const t = s("text", { x: pad.l + hr * slot + slot / 2, y: height - 10, class: "tick", "text-anchor": "middle" });
      t.textContent = hourLabel(hr, h12);
      svg.append(t);
    }
  }
  return svg;
}

/** Area chart over the day: points [[hour(0-24), value]], fixed y range. */
export function dayArea(width, height, points, { min = 0, max = 100, color = "currentColor", unit = "%", h12 = true } = {}) {
  const pad = { l: 72, r: 16, t: 12, b: 34 };
  const w = width - pad.l - pad.r;
  const hgt = height - pad.t - pad.b;
  const x = (hr) => pad.l + (hr / 24) * w;
  const y = (v) => pad.t + hgt - ((v - min) / (max - min)) * hgt;
  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart" });
  for (const v of [min, (min + max) / 2, max]) {
    svg.append(s("line", { x1: pad.l, x2: width - pad.r, y1: y(v), y2: y(v), class: v === min ? "axis" : "grid" }));
    const t = s("text", { x: pad.l - 10, y: y(v) + 6, class: "tick", "text-anchor": "end" });
    t.textContent = `${v}${unit}`;
    svg.append(t);
  }
  for (let hr = 0; hr <= 24; hr += 6) {
    const t = s("text", { x: x(hr), y: height - 8, class: "tick", "text-anchor": hr === 0 ? "start" : hr === 24 ? "end" : "middle" });
    t.textContent = hourLabel(hr % 24, h12);
    svg.append(t);
  }
  if (points.length > 1) {
    const id = `g${Math.random().toString(36).slice(2, 8)}`;
    const grad = s("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 });
    grad.append(s("stop", { offset: "0", "stop-color": color, "stop-opacity": "0.35" }));
    grad.append(s("stop", { offset: "1", "stop-color": color, "stop-opacity": "0" }));
    const defs = s("defs");
    defs.append(grad);
    svg.append(defs);
    const line = points.map(([hr, v], i) => `${i ? "L" : "M"}${x(hr).toFixed(1)},${y(Math.min(max, Math.max(min, v))).toFixed(1)}`).join(" ");
    const last = points[points.length - 1];
    svg.append(s("path", { d: `${line} L${x(last[0])},${y(min)} L${x(points[0][0])},${y(min)} Z`, fill: `url(#${id})` }));
    svg.append(s("path", { d: line, fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linejoin": "round" }));
    svg.append(s("circle", { cx: x(last[0]), cy: y(last[1]), r: 6, fill: color, stroke: "var(--panel-solid)", "stroke-width": 2 }));
  }
  return svg;
}
