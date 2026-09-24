"use client";

import { useEffect, useState } from "react";
import { DOCK_BOTTOM, DOCK_TOP, PANEL_INNER_EDGE, panelHeight, type Corner } from "./HudPanel";
import { coreRadiusPx } from "./HoloCore";

const CORNERS: Corner[] = ["tl", "tr", "bl", "br"];

/** Energy beams from the reactor rim to the inner edge of each open panel. */
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
  const rim = coreRadiusPx(w, h) * 1.02;
  const ph = panelHeight(h);

  const target: Record<Corner, [number, number]> = {
    tl: [PANEL_INNER_EDGE, DOCK_TOP + ph / 2],
    tr: [w - PANEL_INNER_EDGE, DOCK_TOP + ph / 2],
    bl: [PANEL_INNER_EDGE, h - DOCK_BOTTOM - ph / 2],
    br: [w - PANEL_INNER_EDGE, h - DOCK_BOTTOM - ph / 2],
  };

  return (
    <svg
      width={w}
      height={h}
      className="pointer-events-none absolute inset-0 z-[5]"
      style={{ filter: "drop-shadow(0 0 3px rgba(90,216,255,0.75))" }}
    >
      <defs>
        {CORNERS.map((c) => {
          const [tx, ty] = target[c];
          const ang = Math.atan2(ty - cy, tx - cx);
          return (
            <linearGradient
              key={c}
              id={`beam-${c}`}
              gradientUnits="userSpaceOnUse"
              x1={cx + Math.cos(ang) * rim}
              y1={cy + Math.sin(ang) * rim}
              x2={tx}
              y2={ty}
            >
              <stop offset="0" stopColor="#e8fbff" stopOpacity="0.9" />
              <stop offset="1" stopColor="#5ad8ff" stopOpacity="0.25" />
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
          <g key={c} style={{ transition: "opacity 0.25s", opacity: on ? 1 : 0 }}>
            <line
              x1={sx}
              y1={sy}
              x2={tx}
              y2={ty}
              stroke={`url(#beam-${c})`}
              strokeWidth={1.4}
              strokeLinecap="round"
              strokeDasharray={len}
              strokeDashoffset={on ? 0 : len}
              style={{ transition: "stroke-dashoffset 0.35s ease" }}
            />
            {on && (
              <line
                x1={sx}
                y1={sy}
                x2={tx}
                y2={ty}
                stroke="#e8fbff"
                strokeWidth={2.2}
                strokeLinecap="round"
                strokeDasharray="6 34"
                className="beam-pulse"
                style={{ animationDelay: "0.4s" }}
              />
            )}
            <circle cx={sx} cy={sy} r={2.6} fill="#e8fbff" />
          </g>
        );
      })}
    </svg>
  );
}
