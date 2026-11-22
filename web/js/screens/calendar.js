import { h, icon, fmtTime, fmtDate, dayKey, friendly } from "../util.js";

// "Coming Up": calendar events grouped by day, plus an optional to-do panel.
const isDateOnly = (v) => typeof v === "string" && v.length === 10;
const parse = (v) => (isDateOnly(v) ? new Date(`${v}T00:00:00`) : new Date(v));

function relativeDay(key, todayKey, tomorrowKey) {
  return key === todayKey ? "Today" : key === tomorrowKey ? "Tomorrow" : null;
}

function buildDays(cfg, c, maxColumns) {
  const data = c.data.calendar?.[cfg.id];
  const events = [];
  for (const [entity, list] of Object.entries(data || {})) {
    const calCfg = (cfg.calendars || []).find((x) => x.entity === entity) || {};
    for (const ev of list) {
      events.push({ ...ev, startDate: parse(ev.start), allDay: isDateOnly(ev.start),
        calendar: calCfg.name || friendly(c.st(entity), entity), color: calCfg.color });
    }
  }
  events.sort((a, b) => a.startDate - b.startDate);
  const days = new Map();
  for (const ev of events.slice(0, cfg.max_events || 8)) {
    const key = ev.allDay ? dayKey(new Date(ev.startDate.getTime() + 12 * 3600e3)) : dayKey(ev.startDate);
    if (!days.has(key)) days.set(key, { date: ev.startDate, events: [] });
    days.get(key).events.push(ev);
  }
  const todayKey = dayKey(new Date());
  const tomorrowKey = dayKey(new Date(Date.now() + 86400000));
  if (!days.size) {
    return [h("div.panel.cal-empty", icon("calendar", "cal-empty-icon"),
      h("div", "Nothing on the calendar"), h("div.metric-sub", `for the next ${cfg.days || 7} days`))];
  }
  return [...days.entries()].slice(0, maxColumns).map(([key, day]) => {
    const rel = relativeDay(key, todayKey, tomorrowKey);
    return h(`div.panel.cal-day${key === todayKey ? ".is-today" : ""}`,
      h("div.cal-head",
        h("div.cal-weekday", fmtDate(day.date, { weekday: "long" })),
        h("div.cal-date", fmtDate(day.date, { month: "long", day: "numeric" }),
          rel ? h("span.cal-rel", rel) : null)),
      h("div.cal-events", day.events.map((ev) =>
        h("div.cal-event", ev.color ? { style: `--cal-color:${ev.color}` } : null,
          h("div.cal-time", ev.allDay ? "All day" : fmtTime(ev.startDate)),
          h("div.cal-body", h("div.cal-title", ev.summary || "Event"),
            ev.location ? h("div.cal-meta", ev.location)
              : (cfg.calendars?.length > 1 ? h("div.cal-meta", ev.calendar) : null))))));
  });
}

function dueInfo(due) {
  if (!due) return null;
  const d = parse(due);
  if (isNaN(d)) return null;
  const todayKey = dayKey(new Date());
  const key = dayKey(d);
  const timeText = isDateOnly(due) ? "" : ` · ${fmtTime(d)}`;
  if (key < todayKey) return { text: `Overdue · ${fmtDate(d, { month: "short", day: "numeric" })}`, cls: "overdue" };
  if (key === todayKey) return { text: `Today${timeText}`, cls: "today" };
  const rel = relativeDay(key, todayKey, dayKey(new Date(Date.now() + 86400000)));
  return { text: (rel || fmtDate(d, { weekday: "short", month: "short", day: "numeric" })) + timeText, cls: "" };
}

function buildTasks(cfg, c) {
  const data = c.data.todo?.[cfg.id] || {};
  const lists = (cfg.todo_lists || []).map((t) => {
    const items = [...(data[t.entity] || [])].sort((a, b) => {
      if (a.due && b.due) return parse(a.due) - parse(b.due);
      return a.due ? -1 : b.due ? 1 : 0;   // dated tasks first, then the list's own order
    });
    return { name: t.name || friendly(c.st(t.entity), t.entity), items };
  });
  const total = lists.reduce((n, l) => n + l.items.length, 0);
  let budget = cfg.max_tasks || 10;
  const groups = lists.filter((l) => l.items.length).map((l) => {
    const shown = l.items.slice(0, Math.max(0, budget));
    budget -= shown.length;
    return h("div.task-group",
      lists.length > 1 ? h("div.task-list-name", l.name) : null,
      shown.map((it) => {
        const due = dueInfo(it.due);
        return h("div.task", h("span.task-check"),
          h("div.task-body", h("div.task-title", it.summary || "Task"),
            due ? h(`div.task-due${due.cls ? "." + due.cls : ""}`, due.text) : null));
      }),
      l.items.length > shown.length ? h("div.task-more", `+ ${l.items.length - shown.length} more`) : null);
  });
  const title = lists.length === 1 ? lists[0].name : "To do";
  return h("div.panel.tasks-panel",
    h("div.panel-head", h("div.panel-title", title), total ? h("span.task-count", `${total} open`) : null),
    total ? h("div.task-groups", groups)
      : h("div.tasks-empty", h("span.task-check.done"), h("div", "All done")));
}

export function create(cfg) {
  const hasCal = (cfg.calendars || []).length > 0;
  const hasTasks = (cfg.todo_lists || []).length > 0;
  const days = h("div.cal-days");
  const el = h(`section.screen.screen-calendar${hasTasks ? ".with-tasks" : ""}${hasCal ? "" : ".tasks-only"}`,
    hasCal ? days : null);
  let tasksEl = null;
  let lastCal, lastTodo;

  function update(c) {
    const cal = c.data.calendar?.[cfg.id];
    const todo = c.data.todo?.[cfg.id];
    if (hasCal && cal !== lastCal) {
      lastCal = cal;
      days.replaceChildren(...buildDays(cfg, c, hasTasks ? 3 : 4));
    }
    if (hasTasks && todo !== lastTodo) {
      lastTodo = todo;
      const next = buildTasks(cfg, c);
      if (tasksEl) tasksEl.replaceWith(next); else el.append(next);
      tasksEl = next;
    }
  }
  return { el, update };
}
