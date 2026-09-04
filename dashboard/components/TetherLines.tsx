"use client";

import { useEffect, useState } from "react";
import type { Corner } from "./HudPanel";

const CORNERS: Corner[] = ["tl", "tr", "bl", "br"];

// keep in sync with HudPanel: w-[21rem], top-16 (64px), inset-4 (16px), h-[42vh]
const PANEL_W = 21 * 16;
const PAD = 16;
const TOP = 64;

/**
 * Connector beams that leave the RIM of the core (not its centre) and run out to
 * the inner corner of each panel. Geometry is measured from the viewport so the
 * start point sits exactly on the core's outer ring.
 */
export function TetherLines({ shown }: { shown: Corner[] }) {
  const [d, setD] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const on = () => setD({ w: window.innerWidth, h: window.innerHeight });
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  const { w, h } = d;
  if (!w) return null;

  const cx = w / 2;
  const cy = h / 2;
  const coreSize = Math.min(w * 0.78, h * 0.6, 560);
  const rim = (coreSize * 0.9) / 2; // ≈ outer tick-ring radius of the core
  const panelH = h * 0.42;

  const target: Record<Corner, [number, number]> = {
    tl: [PAD + PANEL_W, TOP + panelH],
    tr: [w - PAD - PANEL_W, TOP + panelH],
    bl: [PAD + PANEL_W, h - PAD - panelH],
    br: [w - PAD - PANEL_W, h - PAD - panelH],
  };

  return (
    <svg
      width={w}
      height={h}
      className="pointer-events-none absolute inset-0 z-[5]"
      style={{ filter: "drop-shadow(0 0 6px rgba(56,224,208,0.5))" }}
    >
      <defs>
        {CORNERS.map((c) => {
          const [tx, ty] = target[c];
          const ang = Math.atan2(ty - cy, tx - cx);
          const sx = cx + Math.cos(ang) * rim;
          const sy = cy + Math.sin(ang) * rim;
          return (
            <linearGradient
              key={c}
              id={`beam-${c}`}
              gradientUnits="userSpaceOnUse"
              x1={sx}
              y1={sy}
              x2={tx}
              y2={ty}
            >
              <stop offset="0" stopColor="#7cf5ea" stopOpacity="0.85" />
              <stop offset="1" stopColor="#38e0d0" stopOpacity="0.12" />
            </linearGradient>
          );
        })}
      </defs>

      {CORNERS.map((c) => {
        const [tx, ty] = target[c];
        const ang = Math.atan2(ty - cy, tx - cx);
        const sx = cx + Math.cos(ang) * rim;
        const sy = cy + Math.sin(ang) * rim;
        const len = Math.hypot(tx - sx, ty - sy);
        const on = shown.includes(c);
        return (
          <g key={c}>
            <line
              x1={sx}
              y1={sy}
              x2={tx}
              y2={ty}
              stroke={`url(#beam-${c})`}
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeDasharray={len}
              strokeDashoffset={on ? 0 : len}
              style={{
                transition: "stroke-dashoffset 0.32s ease, opacity 0.25s",
                opacity: on ? 1 : 0,
              }}
            />
            {/* node where the beam leaves the core rim */}
            <circle
              cx={sx}
              cy={sy}
              r={2.5}
              fill="#7cf5ea"
              style={{ transition: "opacity 0.25s", opacity: on ? 0.9 : 0 }}
            />
            {/* node where it meets the panel */}
            <circle
              cx={tx}
              cy={ty}
              r={3.5}
              fill="#38e0d0"
              style={{ transition: "opacity 0.25s ease 0.28s", opacity: on ? 0.9 : 0 }}
            />
          </g>
        );
      })}
    </svg>
  );
}
