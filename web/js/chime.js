// Message chime: a soft two-note "ding" made with Web Audio (no sound file
// needed), or a custom sound from config/sounds/ (message.chime_sound).
let ctx = null;

function audioContext() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

function bell(ac, out, freq, start, length) {
  // A sine with a quieter octave above it, quick attack and a long soft decay.
  for (const [mult, level] of [[1, 1], [2, 0.18], [3, 0.06]]) {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = "sine";
    osc.frequency.value = freq * mult;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(level, start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + length);
    osc.connect(gain).connect(out);
    osc.start(start);
    osc.stop(start + length + 0.05);
  }
}

/** Play the chime. volume: 0-100. Returns roughly how long it lasts (ms). */
export function playChime({ volume = 60, sound = null } = {}) {
  const level = Math.max(0, Math.min(100, Number(volume) || 0)) / 100;
  if (level === 0) return 0;
  if (sound) {
    const audio = new Audio(`/sounds/${encodeURIComponent(sound)}`);
    audio.volume = level;
    audio.play().catch(() => {});
    return 2500;
  }
  const ac = audioContext();
  if (!ac) return 0;
  const out = ac.createGain();
  out.gain.value = 0.35 * level;
  out.connect(ac.destination);
  const t = ac.currentTime + 0.02;
  bell(ac, out, 783.99, t, 1.1);         // G5
  bell(ac, out, 1046.5, t + 0.22, 1.6);  // C6
  return 1900;
}
