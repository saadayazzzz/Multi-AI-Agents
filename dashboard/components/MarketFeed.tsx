"use client";

import { useMemo } from "react";
import type { MarketItem } from "@/lib/api";

/** Continuous worldwide-market headline ticker along the bottom edge. */
export function MarketFeed({ items }: { items: MarketItem[] }) {
  const ticker = useMemo(
    () =>
      items
        .slice(-18)
        .reverse()
        .map((i) => `${i.tag ? `[${i.tag}] ` : ""}${i.headline}`)
        .join("      ◆      "),
    [items],
  );

  if (items.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex h-6 items-center overflow-hidden border-t border-jarvis/15 bg-black/45">
      <span className="relative z-10 shrink-0 border-r border-jarvis/25 bg-void px-3 font-display text-[7.5px] uppercase tracking-[0.22em] text-jarvis/70">
        ai search pulse
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
