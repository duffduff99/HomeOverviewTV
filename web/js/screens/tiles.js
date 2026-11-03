import { h, icon, setIcon, stateParts, friendly, num, isNum } from "../util.js";

const CLASS_ICONS = {
  temperature: "thermometer", humidity: "water", power: "flash", energy: "flash", battery: "battery",
  pm25: "air", aqi: "air", wind_speed: "windy", precipitation: "rain", pressure: "gauge",
  door: "door", garage_door: "door", motion: "motion", occupancy: "motion", illuminance: "lightbulb",
};
const DOMAIN_ICONS = { light: "lightbulb", camera: "cctv", media_player: "radio", calendar: "calendar", weather: "partly" };

function guessIcon(st) {
  const dc = st?.attributes?.device_class;
  if (dc && CLASS_ICONS[dc]) return CLASS_ICONS[dc];
  const domain = st?.entity_id?.split(".")[0];
  return DOMAIN_ICONS[domain] || "info";
}

/** A grid of value tiles; used by the tiles screen and as extras on others. */
export function tileGrid(tiles, extraClass = "") {
  const items = tiles.map((t) => {
    const ref = { icon: icon(t.icon || "info", "tile-icon"), value: h("span.tile-value"), unit: h("span.tile-unit"), name: h("div.tile-name") };
    ref.el = h("div.tile", ref.icon, h("div.tile-body", h("div", ref.value, ref.unit), ref.name));
    return { t, ref };
  });
  const el = h(`div.tile-grid.${extraClass || "tiles-normal"}`, items.map((i) => i.ref.el));
  const n = Math.max(1, tiles.length);
  el.style.setProperty("--count", n);
  el.style.setProperty("--cols", n <= 3 ? n : n === 4 ? 2 : n <= 6 ? 3 : 4);
  function update(c) {
    for (const { t, ref } of items) {
      const st = c.st(t.entity);
      let parts = stateParts(st);
      if (st && t.attribute) {
        const v = st.attributes?.[t.attribute];
        parts = { value: isNum(v) ? num(v, t.digits) : v ?? "—", unit: t.unit || "" };
      } else if (st && isNum(st.state) && t.digits != null) {
        parts.value = num(st.state, t.digits);
      }
      ref.value.textContent = parts.value;
      ref.unit.textContent = t.unit ?? parts.unit;
      ref.name.textContent = t.name || friendly(st, t.entity);
      if (!t.icon) setIcon(ref.icon, guessIcon(st));
      ref.el.classList.toggle("is-unavailable", !st || st.state === "unavailable");
    }
  }
  return { el, update };
}

export function create(cfg) {
  const grid = tileGrid(cfg.tiles || []);
  const el = h("section.screen.screen-tiles", h("div.panel.tiles-panel", grid.el));
  return { el, update: grid.update };
}
