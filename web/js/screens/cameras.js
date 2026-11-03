import { h, friendly } from "../util.js";
import { CameraView } from "../camera.js";

export function create(cfg, ctx) {
  const cams = (cfg.cameras || []).map((c) => new CameraView(
    c.entity, c.name || friendly(ctx.st(c.entity), c.entity),
    { mode: cfg.mode, interval: cfg.snapshot_interval }));
  const el = h(`section.screen.screen-cameras.cams-${cams.length}`, cams.map((c) => c.el));
  return {
    el,
    update() {},
    show() { cams.forEach((c) => c.start()); },
    hide() { cams.forEach((c) => c.stop()); },
  };
}
