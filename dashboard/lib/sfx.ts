"use client";

type Kind = "blip" | "open" | "alert" | "boot";

let ctx: AudioContext | null = null;
let armed = false;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  // browsers keep audio suspended until the first user gesture
  if (!armed) {
    armed = true;
    const wake = () => ctx?.resume();
    window.addEventListener("pointerdown", wake, { once: true });
    window.addEventListener("keydown", wake, { once: true });
  }
  return ctx;
}

function tone(
  a: AudioContext,
  { type, f0, f1, at, dur, gain }: { type: OscillatorType; f0: number; f1: number; at: number; dur: number; gain: number },
) {
  const o = a.createOscillator();
  const g = a.createGain();
  o.type = type;
  o.frequency.setValueAtTime(f0, at);
  o.frequency.exponentialRampToValueAtTime(f1, at + dur);
  g.gain.setValueAtTime(0.0001, at);
  g.gain.exponentialRampToValueAtTime(gain, at + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  o.connect(g).connect(a.destination);
  o.start(at);
  o.stop(at + dur + 0.02);
}

/** Quiet synthesized interface sounds — nothing plays while audio is suspended or muted. */
export function sfx(kind: Kind, enabled: boolean) {
  if (!enabled) return;
  const a = audio();
  if (!a || a.state !== "running") return;
  const t = a.currentTime;
  switch (kind) {
    case "blip":
      tone(a, { type: "sine", f0: 1500, f1: 2300, at: t, dur: 0.05, gain: 0.025 });
      tone(a, { type: "sine", f0: 2300, f1: 2800, at: t + 0.06, dur: 0.05, gain: 0.018 });
      break;
    case "open":
      tone(a, { type: "triangle", f0: 280, f1: 1300, at: t, dur: 0.28, gain: 0.02 });
      break;
    case "alert":
      tone(a, { type: "square", f0: 880, f1: 880, at: t, dur: 0.08, gain: 0.012 });
      tone(a, { type: "square", f0: 1180, f1: 1180, at: t + 0.12, dur: 0.1, gain: 0.012 });
      break;
    case "boot":
      tone(a, { type: "sine", f0: 110, f1: 880, at: t, dur: 1.1, gain: 0.03 });
      tone(a, { type: "triangle", f0: 1760, f1: 2640, at: t + 0.9, dur: 0.35, gain: 0.012 });
      break;
  }
}
