"use client";

import { useMemo } from "react";
import type { TrendItem } from "@/lib/api";

/** Continuous trend-radar ticker along the bottom edge. */
export function MarketFeed({ items }: { items: TrendItem[] }) {
  const ticker = useMemo(
    () =>
      items
        .slice(-18)
        .reverse()
        .map((i) => `[${i.platform}] ${i.topic}`)
        .join("      ◆      "),
    [items],
  );

  if (items.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex h-6 items-center overflow-hidden border-t border-jarvis/15 bg-black/45">
      <span className="shrink-0 border-r border-jarvis/20 px-2 font-mono text-[9px] uppercase tracking-[0.2em] text-jarvis/50">
        trend radar
      </span>
      <div
        className="anim-ticker whitespace-nowrap pl-6 font-mono text-[10px] tracking-wide text-jarvis/55"
        style={{ animationDuration: `${Math.max(32, ticker.length * 0.22)}s` }}
      >
        {ticker}
        <span className="px-8 text-jarvis/25">◆</span>
        {ticker}
      </div>
    </div>
  );
}
