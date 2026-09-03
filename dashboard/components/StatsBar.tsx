"use client";

import type { Stats } from "@/lib/api";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="panel px-4 py-3">
      <div className="label">{label}</div>
      <div className="mt-1 font-mono text-2xl text-jarvis">{value}</div>
    </div>
  );
}

export function StatsBar({ stats }: { stats: Stats | null }) {
  const scraped = stats?.sites?.scraped ?? 0;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label="Sites" value={stats?.sites_total ?? "–"} />
      <Stat label="Scraped" value={scraped} />
      <Stat label="Products" value={stats?.products ?? "–"} />
      <Stat label="Brands built" value={stats?.brands ?? "–"} />
    </div>
  );
}
