"use client";

import { useEffect, useState } from "react";
import type { TrendItem } from "@/lib/api";

// spoke angles (deg; 0 = right, clockwise) — kept away from straight up/down
const SLOTS = [-146, -34, 34, 146];
const CYCLE_MS = 4200;

const PLATFORM_COLOR: Record<string, string> = {
  youtube: "#ff5c72",
  instagram: "#e0538e",
  linkedin: "#38e0d0",
};

/** Live trend headlines that flow in on the core's radial lines. */
export function CoreCallouts({ items }: { items: TrendItem[] }) {
  const [d, setD] = useState({ w: 0, h: 0 });
  const [rot, setRot] = useState(0);

  useEffect(() => {
    const on = () => setD({ w: window.innerWidth, h: window.innerHeight });
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  useEffect(() => {
    if (items.length === 0) return;
    const iv = setInterval(() => setRot((r) => r + 1), CYCLE_MS);
    return () => clearInterval(iv);
  }, [items.length]);

  const { w, h } = d;
  if (!w || items.length === 0) return null;

  const cx = w / 2;
  const cy = h / 2;
  const core = Math.min(w * 0.82, h * 0.64, 600);
  const rNode = core * 0.4; // connector starts here (on a ring)
  const rCard = core * 0.54; // card anchor

  const slots = SLOTS.map((deg, i) => {
    const a = (deg * Math.PI) / 180;
    return {
      deg,
      i,
      it: items[(rot + i) % items.length],
      nx: cx + Math.cos(a) * rNode,
      ny: cy + Math.sin(a) * rNode,
      kx: cx + Math.cos(a) * rCard,
      ky: cy + Math.sin(a) * rCard,
      leftSide: Math.cos(a) < 0,
    };
  });

  return (
    <div className="pointer-events-none absolute inset-0 z-[6]">
      <svg width={w} height={h} className="absolute inset-0">
        {slots.map((s) => {
          if (!s.it) return null;
          const len = Math.hypot(s.kx - s.nx, s.ky - s.ny);
          const color = PLATFORM_COLOR[s.it.platform] ?? "#38e0d0";
          return (
            <g key={`${s.deg}-${s.it.id}-${rot}`}>
              <line
                x1={s.nx}
                y1={s.ny}
                x2={s.kx}
                y2={s.ky}
                stroke={color}
                strokeWidth="1.2"
                strokeOpacity="0.7"
                strokeLinecap="round"
                style={{
                  strokeDasharray: len,
                  strokeDashoffset: len,
                  animation: `draw 0.4s ease ${s.i * 90}ms both`,
                  filter: "drop-shadow(0 0 4px currentColor)",
                }}
              />
              <circle cx={s.nx} cy={s.ny} r="2.4" fill={color} />
              <circle cx={s.kx} cy={s.ky} r="2.4" fill={color} />
            </g>
          );
        })}
      </svg>

      {slots.map((s) => {
        if (!s.it) return null;
        const color = PLATFORM_COLOR[s.it.platform] ?? "#38e0d0";
        return (
          <div
            key={`${s.deg}-${s.it.id}-${rot}`}
            className="anim-rise absolute w-56"
            style={{
              left: s.kx,
              top: s.ky,
              transform: `translate(${s.leftSide ? "-100%" : "0"}, -50%)`,
              textAlign: s.leftSide ? "right" : "left",
              animationDelay: `${s.i * 90 + 220}ms`,
            }}
          >
            <div
              className="inline-flex flex-col gap-0.5 bg-black/55 px-2 py-1 backdrop-blur-sm"
              style={{
                borderLeft: s.leftSide ? "none" : `2px solid ${color}`,
                borderRight: s.leftSide ? `2px solid ${color}` : "none",
              }}
            >
              <span className="font-mono text-[8px] uppercase tracking-[0.18em] text-jarvis/45">
                {s.it.platform} · {s.it.format ?? "trend"}
              </span>
              <span className="text-[11px] font-medium leading-tight text-jarvis-soft">
                {s.it.topic.length > 84 ? s.it.topic.slice(0, 82) + "…" : s.it.topic}
              </span>
              <span className="font-mono text-[8px] text-jarvis/35">{s.it.source ?? "—"}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
