"use client";

import { useEffect, useRef } from "react";

type Star = {
  x: number;
  y: number;
  r: number;
  baseAlpha: number;
  twinkleSpeed: number;
  phase: number;
  driftX: number;
  driftY: number;
  hue: "teal" | "amber" | "white";
};

const HUE_RGB: Record<Star["hue"], string> = {
  teal: "150, 240, 230",
  amber: "255, 200, 140",
  white: "255, 255, 255",
};

/** A calm, live starfield + nebula glow behind the HUD - purely decorative, non-interactive. */
export function StarField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let stars: Star[] = [];
    let w = 0;
    let h = 0;

    const rand = (a: number, b: number) => a + Math.random() * (b - a);

    const buildStars = () => {
      const density = 0.00012; // stars per px^2
      const count = Math.min(420, Math.round(w * h * density));
      const hues: Star["hue"][] = ["white", "white", "white", "teal", "amber"];
      stars = Array.from({ length: count }, () => ({
        x: rand(0, w),
        y: rand(0, h),
        r: rand(0.4, 1.6),
        baseAlpha: rand(0.25, 0.95),
        twinkleSpeed: rand(0.4, 1.6),
        phase: rand(0, Math.PI * 2),
        driftX: rand(-0.006, 0.006),
        driftY: rand(0.004, 0.018),
        hue: hues[Math.floor(rand(0, hues.length))],
      }));
    };

    const resize = () => {
      w = canvas.width = canvas.offsetWidth * devicePixelRatio;
      h = canvas.height = canvas.offsetHeight * devicePixelRatio;
      buildStars();
    };
    resize();
    window.addEventListener("resize", resize);

    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(64, now - last);
      last = now;
      ctx.clearRect(0, 0, w, h);
      for (const s of stars) {
        s.phase += (s.twinkleSpeed * dt) / 1000;
        s.x += s.driftX * dt * devicePixelRatio;
        s.y += s.driftY * dt * devicePixelRatio;
        if (s.y > h + 4) {
          s.y = -4;
          s.x = rand(0, w);
        }
        if (s.x > w + 4) s.x = -4;
        if (s.x < -4) s.x = w + 4;

        const twinkle = 0.55 + 0.45 * Math.sin(s.phase);
        const alpha = s.baseAlpha * twinkle;
        ctx.beginPath();
        ctx.fillStyle = `rgba(${HUE_RGB[s.hue]}, ${alpha.toFixed(3)})`;
        ctx.arc(s.x, s.y, s.r * devicePixelRatio, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      <div className="nebula-glow absolute inset-0" />
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
    </div>
  );
}
