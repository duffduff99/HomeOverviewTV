// Background music: plays the server's track list on a loop (shuffled by default).
export class MusicPlayer {
  constructor(onTrack) {
    this.audio = new Audio();
    this.audio.preload = "auto";
    this.onTrack = onTrack;
    this.settings = { enabled: false, volume: 35, tracks: [] };
    this.queue = [];
    this.ducked = false;
    this.audio.addEventListener("ended", () => this.next());
    this.audio.addEventListener("error", () => setTimeout(() => this.next(), 1500));
    // Some browsers block autoplay until a gesture; keep retrying quietly.
    setInterval(() => { if (this.settings.enabled && this.audio.paused && this.current) this.audio.play().catch(() => {}); }, 5000);
  }

  apply(settings) {
    const changedTracks = JSON.stringify(settings.tracks) !== JSON.stringify(this.settings.tracks);
    this.settings = settings;
    this._volume();
    if (changedTracks) this.queue = [];
    if (!settings.enabled || !settings.tracks.length) {
      this.audio.pause();
      if (!settings.tracks.length) this.current = null;
      this.onTrack(null);
      return;
    }
    if (!this.current || changedTracks && !settings.tracks.some((t) => t.url === this.current.url)) this.next();
    else if (this.audio.paused) { this.audio.play().catch(() => {}); this.onTrack(this.current); }
  }

  duck(on) { this.ducked = on; this._volume(); }

  _volume() {
    const v = this.ducked ? Math.min(this.settings.volume, this.settings.duck_volume ?? 10) : this.settings.volume;
    this.audio.volume = Math.max(0, Math.min(1, (v ?? 35) / 100));
  }

  next() {
    const tracks = this.settings.tracks || [];
    if (!this.settings.enabled || !tracks.length) return;
    if (!this.queue.length) {
      this.queue = [...tracks];
      if (this.settings.shuffle !== false) {
        for (let i = this.queue.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [this.queue[i], this.queue[j]] = [this.queue[j], this.queue[i]];
        }
        if (this.queue.length > 1 && this.queue[0].url === this.current?.url) this.queue.push(this.queue.shift());
      }
    }
    this.current = this.queue.shift();
    this.audio.src = this.current.url;
    this.audio.play().catch(() => {});
    this.onTrack(this.current);
  }
}
