"use client";

import { useEffect, useRef } from "react";

/**
 * Listens to the mic for a sharp, sudden loud sound (a clap) while `enabled`
 * and calls `onClap`. This is a rough heuristic (RMS spike well above the
 * recent ambient average) - not clap-specific recognition, so any sudden
 * loud sound nearby (a door slam, a cough) can trigger it too. Good enough
 * for a "wake JARVIS back up" gesture, not a precision instrument.
 */
export function useClapDetector(enabled: boolean, onClap: () => void) {
  const onClapRef = useRef(onClap);
  onClapRef.current = onClap;

  useEffect(() => {
    if (!enabled || typeof navigator === "undefined" || !navigator.mediaDevices) return;

    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let raf = 0;
    let stopped = false;
    let lastClapAt = 0;

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (stopped) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        ctx = new AudioContext();
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        src.connect(analyser);
        const buf = new Uint8Array(analyser.frequencyBinCount);
        const history: number[] = [];

        const tick = () => {
          if (stopped) return;
          analyser.getByteTimeDomainData(buf);
          let sumSquares = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = (buf[i] - 128) / 128;
            sumSquares += v * v;
          }
          const rms = Math.sqrt(sumSquares / buf.length);
          history.push(rms);
          if (history.length > 30) history.shift();
          const avg = history.reduce((a, b) => a + b, 0) / history.length;

          const now = performance.now();
          if (rms > 0.28 && rms > avg * 3.2 && now - lastClapAt > 800) {
            lastClapAt = now;
            onClapRef.current();
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      } catch {
        /* mic permission denied/unavailable - silently do nothing */
      }
    })();

    return () => {
      stopped = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close().catch(() => {});
    };
  }, [enabled]);
}
