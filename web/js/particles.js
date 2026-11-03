// Lightweight seasonal particle effects on a canvas (snow, leaves, petals, fireflies, sparkles).
const KINDS = {
  snow: { count: 70, colors: ["#ffffff"], size: [2, 5], vy: [0.3, 1.0], vx: [-0.3, 0.3], shape: "dot", alpha: [0.4, 0.9] },
  leaves: { count: 22, colors: ["#d9622b", "#e8a33d", "#b8401f", "#c97b2a"], size: [8, 14], vy: [0.5, 1.2], vx: [-0.6, 0.4], shape: "leaf", alpha: [0.7, 0.95] },
  petals: { count: 26, colors: ["#f6c6d6", "#fbe3ea", "#f3a6c0"], size: [5, 9], vy: [0.35, 0.8], vx: [-0.2, 0.5], shape: "petal", alpha: [0.6, 0.9] },
  fireflies: { count: 26, colors: ["#fde68a", "#fcd34d"], size: [2, 3.5], vy: [-0.15, 0.15], vx: [-0.2, 0.2], shape: "glow", alpha: [0.2, 1] },
  sparkles: { count: 40, colors: ["#fff4cc", "#ffffff", "#ffd36b"], size: [1.5, 3.5], vy: [0.2, 0.6], vx: [-0.15, 0.15], shape: "glow", alpha: [0.3, 1] },
};
const rand = ([a, b]) => a + Math.random() * (b - a);

export class Particles {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.kind = null;
    this.items = [];
    this.last = 0;
    this._frame = this._frame.bind(this);
  }

  set(kind, enabled = true) {
    const spec = enabled && KINDS[kind];
    this.kind = spec ? kind : null;
    this.items = spec ? Array.from({ length: spec.count }, () => this._spawn(spec, true)) : [];
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (spec && !this.running) { this.running = true; requestAnimationFrame(this._frame); }
  }

  _spawn(spec, anywhere) {
    const { width, height } = this.canvas;
    return {
      x: Math.random() * width, y: anywhere ? Math.random() * height : -20,
      vx: rand(spec.vx), vy: rand(spec.vy), r: rand(spec.size), a: rand(spec.alpha),
      rot: Math.random() * Math.PI * 2, vr: (Math.random() - 0.5) * 0.03, phase: Math.random() * Math.PI * 2,
      color: spec.colors[Math.floor(Math.random() * spec.colors.length)],
    };
  }

  _frame(t) {
    if (!this.kind) { this.running = false; return; }
    requestAnimationFrame(this._frame);
    if (t - this.last < 33) return; // ~30 fps is plenty and kind to small CPUs
    const dt = Math.min(3, (t - this.last) / 16.7);
    this.last = t;
    const spec = KINDS[this.kind];
    const { width, height } = this.canvas;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, width, height);
    for (let i = 0; i < this.items.length; i++) {
      const p = this.items[i];
      p.phase += 0.02 * dt;
      p.x += (p.vx + Math.sin(p.phase) * 0.3) * dt;
      p.y += p.vy * dt;
      p.rot += p.vr * dt;
      if (p.y > height + 20 || p.x < -30 || p.x > width + 30 || (spec.shape === "glow" && p.y < -20)) {
        this.items[i] = this._spawn(spec, spec.shape === "glow");
        continue;
      }
      ctx.globalAlpha = spec.shape === "glow" ? p.a * (0.55 + 0.45 * Math.sin(p.phase * 2)) : p.a;
      ctx.fillStyle = p.color;
      if (spec.shape === "dot") {
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
      } else if (spec.shape === "glow") {
        ctx.shadowColor = p.color; ctx.shadowBlur = 12;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      } else {
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
        ctx.beginPath();
        if (spec.shape === "leaf") {
          ctx.moveTo(0, -p.r); ctx.quadraticCurveTo(p.r * 0.9, 0, 0, p.r); ctx.quadraticCurveTo(-p.r * 0.9, 0, 0, -p.r);
        } else {
          ctx.ellipse(0, 0, p.r, p.r * 0.55, 0, 0, Math.PI * 2);
        }
        ctx.fill(); ctx.restore();
      }
    }
    ctx.globalAlpha = 1;
  }
}
