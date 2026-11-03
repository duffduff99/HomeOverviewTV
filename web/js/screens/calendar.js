import { h, icon, fmtTime, fmtDate, dayKey, friendly } from "../util.js";

const isAllDay = (v) => typeof v === "string" && v.length === 10;
const parse = (v) => (isAllDay(v) ? new Date(`${v}T00:00:00`) : new Date(v));

export function create(cfg, ctx) {
  const body = h("div.cal-days");
  const el = h("section.screen.screen-calendar", body);
  let last;

  function update(c) {
    const data = c.data.calendar?.[cfg.id];
    if (data === last) return;
    last = data;
    const events = [];
    for (const [entity, list] of Object.entries(data || {})) {
      const calCfg = (cfg.calendars || []).find((x) => x.entity === entity) || {};
      for (const ev of list) {
        events.push({ ...ev, startDate: parse(ev.start), allDay: isAllDay(ev.start),
          calendar: calCfg.name || friendly(c.st(entity), entity), color: calCfg.color });
      }
    }
    events.sort((a, b) => a.startDate - b.startDate);
    const days = new Map();
    const todayKey = dayKey(new Date());
    const tomorrowKey = dayKey(new Date(Date.now() + 86400000));
    for (const ev of events.slice(0, cfg.max_events || 8)) {
      const key = ev.allDay ? dayKey(new Date(ev.startDate.getTime() + 12 * 3600e3)) : dayKey(ev.startDate);
      if (!days.has(key)) days.set(key, { date: ev.startDate, events: [] });
      days.get(key).events.push(ev);
    }
    if (!days.size) {
      body.replaceChildren(h("div.panel.cal-empty", icon("calendar", "cal-empty-icon"),
        h("div", "Nothing on the calendar"), h("div.metric-sub", `for the next ${cfg.days || 7} days`)));
      return;
    }
    body.replaceChildren(...[...days.entries()].slice(0, 4).map(([key, day]) =>
      h(`div.panel.cal-day${key === todayKey ? ".is-today" : ""}`,
        h("div.cal-head",
          h("div.cal-weekday", key === todayKey ? "Today" : key === tomorrowKey ? "Tomorrow" : fmtDate(day.date, { weekday: "long" })),
          h("div.cal-date", fmtDate(day.date, { month: "long", day: "numeric" }))),
        h("div.cal-events", day.events.map((ev) =>
          h("div.cal-event", ev.color ? { style: `--cal-color:${ev.color}` } : null,
            h("div.cal-time", ev.allDay ? "All day" : fmtTime(ev.startDate)),
            h("div.cal-body", h("div.cal-title", ev.summary || "Event"),
              ev.location ? h("div.cal-meta", ev.location) : (cfg.calendars?.length > 1 ? h("div.cal-meta", ev.calendar) : null))))),
      )));
  }
  return { el, update };
}
