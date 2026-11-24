import { h, icon } from "./util.js";

const NAMED_POSITIONS = { top: "50% 0%", center: "50% 50%", middle: "50% 50%", bottom: "50% 100%" };
export function cameraPosition(pos) {
  if (pos == null || pos === "") return "50% 50%";
  if (typeof pos === "number") return `50% ${pos}%`;        // position: 20  -> 20% from the top
  return NAMED_POSITIONS[String(pos).toLowerCase()] || String(pos);
}

/** Find a camera's display settings wherever it's configured (for pop-ups). */
export function cameraOptions(config, entity) {
  for (const s of config?.screens || []) {
    if (s.type !== "cameras") continue;
    const cam = (s.cameras || []).find((c) => c.entity === entity);
    if (cam) return { position: cam.position ?? s.position, fit: cam.fit ?? s.fit };
  }
  return {};
}

/**
 * One camera tile. Shows a snapshot immediately, then switches to the live
 * HLS stream from Home Assistant when it starts playing. Falls back to
 * refreshing snapshots if live video isn't available (or mode: snapshot).
 */
export class CameraView {
  constructor(entity, name, { mode = "live", interval = 3, position = "center", fit = "cover" } = {}) {
    this.entity = entity;
    this.mode = mode;
    this.interval = Math.max(1, Number(interval) || 3) * 1000;
    this.img = h("img.cam-media", { alt: "" });
    this.video = h("video.cam-media", { muted: true, playsinline: true, autoplay: true });
    this.video.muted = true;
    // Which part of the picture to keep when it's cropped to fill the tile:
    // "top", "center", "bottom", or any CSS position such as "50% 20%".
    for (const media of [this.img, this.video]) {
      media.style.objectPosition = cameraPosition(position);
      media.style.objectFit = fit === "contain" ? "contain" : "cover";
    }
    this.badge = h("span.cam-badge", "LIVE");
    this.el = h("div.cam",
      this.img, this.video,
      h("div.cam-label", icon("cctv"), h("span", name || entity)),
      this.badge,
    );
    this.running = false;
  }

  async start() {
    if (this.running) return;
    this.running = true;
    this.el.classList.remove("is-live", "is-error");
    this._snapshot();
    if (this.mode === "live" && window.Hls) {
      try {
        const res = await fetch(`/api/camera/${this.entity}/stream`);
        const { url } = await res.json();
        if (url && this.running) return this._live(url);
      } catch { /* fall through to snapshots */ }
    }
    this._poll();
  }

  _snapshot() {
    const next = new Image();
    next.onload = () => {
      if (!this.running) return;
      this.img.src = next.src;
      this.el.classList.remove("is-error");
    };
    next.onerror = () => this.el.classList.add("is-error");
    next.src = `/api/camera/${this.entity}/snapshot?t=${Date.now()}`;
  }

  _poll() {
    this.badge.textContent = "SNAPSHOT";
    clearInterval(this.timer);
    this.timer = setInterval(() => this._snapshot(), this.interval);
  }

  _live(url) {
    const Hls = window.Hls;
    this.badge.textContent = "LIVE";
    if (Hls.isSupported()) {
      this.hls = new Hls({ lowLatencyMode: true, liveSyncDurationCount: 2, maxBufferLength: 8, backBufferLength: 0 });
      this.hls.on(Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) { this._teardownVideo(); if (this.running) this._poll(); }
      });
      this.hls.loadSource(url);
      this.hls.attachMedia(this.video);
    } else {
      this.video.src = url;
    }
    this.video.onplaying = () => this.el.classList.add("is-live");
    this.video.play().catch(() => {});
  }

  _teardownVideo() {
    this.el.classList.remove("is-live");
    if (this.hls) { this.hls.destroy(); this.hls = null; }
    this.video.removeAttribute("src");
    this.video.load();
  }

  stop() {
    this.running = false;
    clearInterval(this.timer);
    this._teardownVideo();
  }
}
