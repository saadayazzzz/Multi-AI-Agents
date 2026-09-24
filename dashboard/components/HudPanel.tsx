"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

export type Corner = "tl" | "tr" | "bl" | "br";

/** Dock geometry in px/rem — TetherLines and HoloToasts read the same numbers. */
export const DOCK_SIDE = 24;
export const DOCK_TOP = 70;
export const DOCK_BOTTOM = 42;
export const PANEL_W = 336;
// panels swing in at this angle, then rest flat — a 3D-transformed layer resamples its text
const ENTRY_TILT = 18;

export function panelHeight(vh: number) {
  return vh * 0.5 - DOCK_TOP;
}

/** Distance from the viewport edge to a docked panel's inner edge. */
export const PANEL_INNER_EDGE = DOCK_SIDE + PANEL_W;

const FOLDED: Record<Corner, string> = {
  tl: "translate(40vw, 28vh) scale(0.04)",
  tr: "translate(-40vw, 28vh) scale(0.04)",
  bl: "translate(40vw, -24vh) scale(0.04)",
  br: "translate(-40vw, -24vh) scale(0.04)",
};

const CHAMFER = 12;

function framePath(w: number, h: number) {
  const c = CHAMFER;
  return `M ${c} 0.75 H ${w - 0.75} V ${h - c} L ${w - c} ${h - 0.75} H 0.75 V ${c} Z`;
}

function useHexCode() {
  const [code, setCode] = useState("0x0000");
  useEffect(() => {
    const iv = setInterval(
      () => setCode("0x" + Math.floor(Math.random() * 0xffff).toString(16).toUpperCase().padStart(4, "0")),
      1400,
    );
    return () => clearInterval(iv);
  }, []);
  return code;
}

/** A holographic window that bursts out of the core, tilted toward the operator. */
export function HudPanel({
  corner,
  open,
  title,
  count,
  pulseKey = 0,
  children,
}: {
  corner: Corner;
  open: boolean;
  title: ReactNode;
  count?: ReactNode;
  pulseKey?: number;
  children: ReactNode;
}) {
  const [mounted, setMounted] = useState(open);
  const [cycle, setCycle] = useState(0);
  const [flare, setFlare] = useState(0);
  const [size, setSize] = useState({ w: PANEL_W, h: 300 });
  const boxRef = useRef<HTMLDivElement>(null);
  const code = useHexCode();

  const left = corner === "tl" || corner === "bl";
  const top = corner === "tl" || corner === "tr";

  useEffect(() => {
    if (open) {
      setMounted(true);
      setCycle((c) => c + 1);
      return;
    }
    const t = setTimeout(() => setMounted(false), 520);
    return () => clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (pulseKey > 0 && open) setFlare((f) => f + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pulseKey]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [mounted, cycle]);

  if (!mounted) return null;

  const tilt = `perspective(1400px) rotateY(${left ? ENTRY_TILT : -ENTRY_TILT}deg)`;

  return (
    <div
      className="absolute z-10"
      style={{
        width: PANEL_W,
        height: `calc(50vh - ${DOCK_TOP}px)`,
        ...(left ? { left: DOCK_SIDE } : { right: DOCK_SIDE }),
        ...(top ? { top: DOCK_TOP } : { bottom: DOCK_BOTTOM }),
        transform: open ? "none" : `${FOLDED[corner]} ${tilt}`,
        transformOrigin: `${left ? "0%" : "100%"} 50%`,
        opacity: open ? 1 : 0,
        transition: "transform 0.55s cubic-bezier(0.16, 1, 0.3, 1) 0.2s, opacity 0.3s ease 0.2s",
      }}
    >
      <div ref={boxRef} key={cycle} className="glass-wipe relative h-full w-full" style={{ animationDelay: "0.35s" }}>
        <div
          key={`g${flare}`}
          className={`hud-panel pointer-events-auto flex h-full flex-col overflow-hidden ${flare ? "updated-glow" : ""}`}
        >
          {flare > 0 && <span key={`s${flare}`} className="scan-line" />}

          <div className="flex h-9 shrink-0 items-center justify-between border-b border-jarvis/20 px-3">
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rotate-45 bg-jarvis shadow-[0_0_6px_rgba(90,216,255,0.9)]" />
              <span className="label holo">{title}</span>
            </div>
            <div className="flex items-center gap-2 font-mono text-[10px]">
              <span className="text-jarvis/30">{code}</span>
              {count !== undefined && <span className="holo text-jarvis">{count}</span>}
            </div>
          </div>
          <div className="holo-flicker min-h-0 flex-1 overflow-y-auto" style={{ animationDelay: "0.6s" }}>
            {children}
          </div>
        </div>
      </div>

      {/* drawn-on frame, replayed every time the panel opens */}
      <svg
        key={`f${cycle}`}
        className="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
        style={{ filter: "drop-shadow(0 0 2.5px rgba(90,216,255,0.8))" }}
      >
        <path
          d={framePath(size.w, size.h)}
          pathLength={1}
          fill="none"
          stroke="rgba(90,216,255,0.8)"
          strokeWidth="1.2"
          className="frame-draw"
        />
        <path
          d={`M 0 36 H ${size.w}`}
          pathLength={1}
          fill="none"
          stroke="rgba(90,216,255,0.35)"
          strokeWidth="1"
          className="frame-draw"
          style={{ animationDelay: "0.35s" }}
        />
        {/* bright corner accents */}
        <path
          d={`M ${size.w - 40} 1 H ${size.w - 1} V 22`}
          fill="none"
          stroke="#e8fbff"
          strokeWidth="2"
          pathLength={1}
          className="frame-draw"
          style={{ animationDelay: "0.5s" }}
        />
        <path
          d={`M 1 ${size.h - 22} V ${size.h - 1} H 40`}
          fill="none"
          stroke="#e8fbff"
          strokeWidth="2"
          pathLength={1}
          className="frame-draw"
          style={{ animationDelay: "0.5s" }}
        />
        {/* edge ruler */}
        <g stroke="rgba(90,216,255,0.45)" strokeWidth="1">
          {Array.from({ length: 14 }, (_, i) => (
            <line
              key={i}
              x1={left ? size.w - 1 : 1}
              x2={left ? size.w - (i % 4 === 0 ? 9 : 5) : i % 4 === 0 ? 9 : 5}
              y1={48 + i * 10}
              y2={48 + i * 10}
              className="holo-flicker"
              style={{ animationDelay: `${0.7 + i * 0.02}s` }}
            />
          ))}
        </g>
        {/* the node where the core's beam lands */}
        <rect
          x={left ? size.w - 5 : -5}
          y={size.h / 2 - 5}
          width="10"
          height="10"
          transform={`rotate(45 ${left ? size.w : 0} ${size.h / 2})`}
          fill="rgba(90,216,255,0.25)"
          stroke="#5ad8ff"
          strokeWidth="1"
        />
      </svg>
    </div>
  );
}
