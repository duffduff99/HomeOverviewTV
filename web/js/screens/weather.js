import { h, icon, setIcon, weatherIcon, weatherLabel, num, isNum, aqiInfo, moonPhase,
  fmtTime, fmtDate } from "../util.js";
import { tileGrid } from "./tiles.js";
import { gauge } from "./air.js";

export function create(cfg, ctx) {
  const ref = {};
  const metric = (key, iconName, label) => {
    ref[key] = { value: h("span.metric-value"), sub: h("span.metric-sub") };
    return h(`div.metric.metric-${key}`, icon(iconName, "metric-icon"),
      h("div.metric-body", h("span.metric-label", label), h("div", ref[key].value, ref[key].sub)));
  };

  ref.icon = icon("cloudy", "hero-icon");
  ref.temp = h("span.hero-temp");
  ref.unit = h("span.hero-unit");
  ref.cond = h("div.hero-cond");
  ref.hilo = h("div.hero-hilo");
  ref.forecast = h("div.forecast");
  ref.sunrise = h("span.big-value");
  ref.sunset = h("span.big-value");
  ref.moonName = h("span.big-value");
  ref.moonSub = h("span.metric-sub");
  ref.moonIcon = h("span.moon-disc");
  ref.aqiBar = h("div.aqi-scale", ...["good", "moderate", "usg", "unhealthy", "very", "hazard"].map((l) => h(`span.lvl-${l}`)));
  ref.aqiMarker = h("span.aqi-marker");
  ref.aqiBar.append(ref.aqiMarker);
  const tiles = tileGrid(cfg.tiles || [], "tiles-compact");
  const gauges = (cfg.air_gauges || []).map(gauge);

  const el = h("section.screen.screen-weather",
    h("div.panel.hero",
      h("div.hero-main", ref.icon,
        h("div", h("div.hero-temp-wrap", ref.temp, ref.unit), ref.cond, ref.hilo)),
      h("div.metrics",
        cfg.humidity ? metric("humidity", "water", "Humidity") : null,
        cfg.air_quality ? metric("aqi", "air", "Air Quality") : null,
        metric("wind", "windy", "Wind"),
      ),
      cfg.air_quality ? ref.aqiBar : null,
    ),
    h("div.weather-side",
      h("div.panel.forecast-panel", h("div.panel-title", cfg.forecast === "hourly" ? "Next hours" : "Forecast"), ref.forecast),
      h("div.weather-bottom",
        h("div.panel.sunmoon",
          h("div.sm-item", icon("sunrise", "sm-icon"), h("div", h("span.metric-label", "Sunrise"), ref.sunrise)),
          h("div.sm-item", icon("sunset", "sm-icon"), h("div", h("span.metric-label", "Sunset"), ref.sunset)),
          h("div.sm-item", ref.moonIcon, h("div", h("span.metric-label", "Moon"), ref.moonName, ref.moonSub)),
        ),
        gauges.length ? h(`div.panel.weather-air.n${gauges.length}`,
          h("div.panel-title", "Air quality"), h("div.weather-air-grid", gauges.map((g) => g.el))) : null,
        (cfg.tiles || []).length ? h("div.panel.weather-tiles", tiles.el) : null,
      ),
    ),
  );

  let lastForecast = null;
  function update(c) {
    const w = c.st(cfg.weather);
    const t = c.st(cfg.temperature);
    const night = c.st("sun.sun")?.state === "below_horizon";
    const cond = w?.state;
    setIcon(ref.icon, weatherIcon(cond, night));
    const tempVal = t && isNum(t.state) ? t.state : w?.attributes?.temperature;
    ref.temp.textContent = isNum(tempVal) ? Math.round(Number(tempVal)) : "—";
    ref.unit.textContent = t?.attributes?.unit_of_measurement || w?.attributes?.temperature_unit || "°";
    ref.cond.textContent = weatherLabel(cond);

    const fc = c.data.forecast?.[cfg.id] || [];
    const today = fc[0];
    ref.hilo.textContent = today && cfg.forecast !== "hourly" && isNum(today.temperature)
      ? `High ${Math.round(today.temperature)}°  ·  Low ${isNum(today.templow) ? Math.round(today.templow) + "°" : "—"}` : "";

    if (ref.humidity) {
      const hum = c.st(cfg.humidity);
      ref.humidity.value.textContent = hum ? num(hum.state, 0) : "—";
      ref.humidity.sub.textContent = "%";
    }
    if (ref.aqi) {
      const info = aqiInfo(c.st(cfg.air_quality));
      ref.aqi.value.textContent = info ? info.value : "—";
      ref.aqi.sub.textContent = info ? info.label : "";
      ref.aqi.value.closest(".metric").dataset.level = info?.level || "";
      ref.aqiMarker.style.left = info ? `${Math.min(100, (info.value / 300) * 100)}%` : "-100px";
    }
    const windSt = c.st(cfg.wind);
    const windVal = windSt ? windSt.state : w?.attributes?.wind_speed;
    ref.wind.value.textContent = isNum(windVal) ? Math.round(Number(windVal)) : "—";
    ref.wind.sub.textContent = windSt?.attributes?.unit_of_measurement || w?.attributes?.wind_speed_unit || "";

    const sun = c.st("sun.sun");
    const rise = sun?.attributes?.next_rising, set = sun?.attributes?.next_setting;
    ref.sunrise.textContent = rise ? fmtTime(new Date(rise)) : "—";
    ref.sunset.textContent = set ? fmtTime(new Date(set)) : "—";
    const moon = moonPhase();
    ref.moonName.textContent = moon.name;
    ref.moonSub.textContent = `${moon.illumination}% lit`;
    // shadow disc slides across: waxing lights the right side, waning the left
    const off = moon.frac < 0.5 ? -moon.frac * 2 * 46 : (1 - moon.frac) * 2 * 46;
    ref.moonIcon.style.setProperty("--moon-off", `${off}px`);

    if (fc !== lastForecast) {
      lastForecast = fc;
      ref.forecast.replaceChildren(...fc.slice(0, cfg.forecast_count || 5).map((f, i) => {
        const d = new Date(f.datetime);
        const label = cfg.forecast === "hourly" ? fmtTime(d)
          : i === 0 ? "Today" : fmtDate(d, { weekday: "short" });
        return h("div.fc-day",
          h("div.fc-label", label),
          icon(weatherIcon(f.condition), "fc-icon"),
          h("div.fc-temp", isNum(f.temperature) ? `${Math.round(f.temperature)}°` : "—",
            isNum(f.templow) ? h("span.fc-low", `${Math.round(f.templow)}°`) : null),
          h("div.fc-precip", isNum(f.precipitation_probability) && f.precipitation_probability > 0
            ? [icon("rain"), `${Math.round(f.precipitation_probability)}%`] : " "),
        );
      }));
    }
    tiles.update(c);
    gauges.forEach((g) => g.update(c));
  }

  return { el, update };
}
