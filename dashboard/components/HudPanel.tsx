"use client";

import { useEffect, useState, type ReactNode } from "react";

export type Corner = "tl" | "tr" | "bl" | "br";

const DOCK: Record<Corner, string> = {
  tl: "left-4 top-16",
  tr: "right-4 top-16",
  bl: "left-4 bottom-4",
  br: "right-4 bottom-4",
};
// collapsed transform: yank the panel back toward the core and shrink it
const FOLDED: Record<Corner, string> = {
  tl: "translate(42vw, 30vh) scale(0.05)",
  tr: "translate(-42vw, 30vh) scale(0.05)",
  bl: "translate(42vw, -26vh) scale(0.05)",
  br: "translate(-42vw, -26vh) scale(0.05)",
};
const ORIGIN: Record<Corner, string> = {
  tl: "100% 100%",
  tr: "0% 100%",
  bl: "100% 0%",
  br: "0% 0%",
};
const NODE: Record<Corner, string> = {
  tl: "-bottom-1.5 -right-1.5",
  tr: "-bottom-1.5 -left-1.5",
  bl: "-top-1.5 -right-1.5",
  br: "-top-1.5 -left-1.5",
};

/** A holographic window that bursts out of the core toward a screen corner. */
export function HudPanel({
  corner,
  open,
  title,
  count,
  children,
}: {
  corner: Corner;
  open: boolean;
  title: ReactNode;
  count?: ReactNode;
  children: ReactNode;
}) {
  const [mounted, setMounted] = useState(open);
  const [scan, setScan] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      const t = setTimeout(() => setScan(true), 180); // let the beam reach first
      const t2 = setTimeout(() => setScan(false), 1100);
      return () => {
        clearTimeout(t);
        clearTimeout(t2);
      };
    }
    const t = setTimeout(() => setMounted(false), 520);
    return () => clearTimeout(t);
  }, [open]);

  if (!mounted) return null;

  return (
    <div
      className={`absolute z-10 h-[42vh] w-[21rem] ${DOCK[corner]}`}
      style={{
        transform: open ? "none" : FOLDED[corner],
        opacity: open ? 1 : 0,
        transformOrigin: ORIGIN[corner],
        // wait ~0.2s so the connector beam visibly extends before the panel unfolds
        transition:
          "transform 0.5s cubic-bezier(0.16, 1, 0.3, 1) 0.2s, opacity 0.3s ease 0.2s",
      }}
    >
      <div className="hud-panel pointer-events-auto flex h-full flex-col overflow-hidden">
        <span className="hud-corner tl" />
        <span className="hud-corner tr" />
        <span className="hud-corner bl" />
        <span className="hud-corner br" />
        <span
          className={`absolute h-3 w-3 rotate-45 border border-jarvis/80 bg-jarvis/20 ${NODE[corner]}`}
        />
        {scan && <span className="scan-line" />}

        <div className="flex h-9 shrink-0 items-center justify-between border-b border-jarvis/20 px-3">
          <span className="label holo">{title}</span>
          <span className="font-mono text-[10px] text-jarvis/45">{count}</span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
