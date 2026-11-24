import { h, icon, fmtDate } from "../util.js";

// "Headlines": top stories from a few news feeds, plus Wikipedia's "On this day".

function ago(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return mins <= 1 ? "Just now" : `${mins} min ago`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

// Show only the items that fit (bigger TV text fits fewer), rather than
// cutting the last one off mid-line.
function fitList(list) {
  requestAnimationFrame(() => {
    while (list.children.length > 1 && list.scrollHeight > list.clientHeight + 2) list.lastElementChild.remove();
  });
}

export function create(cfg) {
  const list = h("div.headline-list");
  const events = h("div.otd-list");
  const otdDate = h("span.otd-date");
  const showOtd = cfg.on_this_day !== false;
  const el = h(`section.screen.screen-news${showOtd ? "" : ".no-otd"}`,
    h("div.panel.headlines-panel",
      h("div.panel-head", h("div.panel-title", "Top stories"),
        h("span.news-sources", (cfg.feeds || []).map((f) => f.name).filter(Boolean).join(" · "))),
      list),
    showOtd ? h("div.panel.otd-panel",
      h("div.panel-head", h("div.panel-title", "On this day"), otdDate), events) : null);

  let last;
  function update(c) {
    const data = c.data.news?.[cfg.id];
    // Re-render when data arrives, and every few minutes so "2h ago" stays right.
    const stamp = `${JSON.stringify(data)}|${Math.floor(Date.now() / 300000)}`;
    if (stamp === last) return;
    last = stamp;
    const items = data?.headlines || [];
    list.replaceChildren(...(items.length ? items.map((it) =>
      h("div.headline",
        h("span.news-badge", { "data-source": it.source }, it.source),
        h("div.headline-body", h("div.headline-title", it.title),
          it.published ? h("div.headline-time", ago(it.published)) : null)))
      : [h("div.news-empty", data ? "No headlines right now" : "Loading headlines…")]));
    fitList(list);
    if (showOtd) {
      otdDate.textContent = fmtDate(new Date(), { month: "long", day: "numeric" });
      const evs = data?.on_this_day || [];
      events.replaceChildren(...(evs.length ? evs.map((ev) =>
        h("div.otd", h("div.otd-year", String(ev.year)), h("div.otd-text", ev.text)))
        : [h("div.news-empty", data ? "Nothing for today" : "Loading…")]));
      fitList(events);
    }
  }
  return { el, update };
}
