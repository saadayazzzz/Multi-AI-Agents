"use client";

import { useEffect, useState } from "react";
import { getGeoLatest, type GeoLatest } from "@/lib/api";

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

export function GeoScore() {
  const [data, setData] = useState<GeoLatest | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getGeoLatest()
        .then((d) => {
          if (alive && d) setData(d);
        })
        .catch(() => {});
    load();
    const iv = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  if (!data) {
    return (
      <div className="px-3 py-2 font-mono text-[10px] text-jarvis/35">
        no visibility check yet — ask AUREN to “check AI visibility for &lt;brand&gt;”
      </div>
    );
  }

  const s = data.score;
  const hits: Record<string, number> = { [s.brand]: 0, ...(s.detail?.per_competitor_hits ?? {}) };
  hits[s.brand] = data.queries.filter((q) => q.brand_mentioned).length;
  const top = Math.max(1, ...Object.values(hits));

  return (
    <div className="space-y-3 p-3">
      <div className="border border-jarvis/15 bg-black/25 px-3 py-2.5">
        <div className="label">AI Search Visibility · {s.brand}</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="holo font-mono text-2xl text-jarvis">
            {Number(s.score).toFixed(1)}
          </span>
          <span className="font-mono text-[10px] text-jarvis/40">
            / 100 · {s.engine}
          </span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[9px] text-jarvis/55">
          <span>presence {pct(s.presence_rate)}</span>
          <span>cited {pct(s.citation_rate)}</span>
          <span>recommended {pct(s.reco_rate)}</span>
          <span>SoV {pct(s.share_of_voice)}</span>
          {s.avg_position != null && <span>avg pos {Number(s.avg_position).toFixed(1)}</span>}
        </div>
      </div>

      <div className="border border-jarvis/15 bg-black/25 px-3 py-2">
        <div className="label">Share of voice</div>
        <div className="mt-2 space-y-1.5">
          {Object.entries(hits)
            .sort((a, b) => b[1] - a[1])
            .map(([name, n]) => (
              <div key={name} className="flex items-center gap-2 font-mono text-[9px] text-jarvis/55">
                <span className="w-24 shrink-0 truncate">
                  {name}
                  {name === s.brand ? " ◂" : ""}
                </span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-jarvis/10">
                  <span
                    className={`block h-full ${name === s.brand ? "bg-jarvis" : "bg-jarvis/40"}`}
                    style={{ width: `${(n / top) * 100}%` }}
                  />
                </span>
                <span className="w-5 text-right">{n}</span>
              </div>
            ))}
        </div>
      </div>

      <div className="border border-jarvis/15 bg-black/25 px-3 py-2">
        <div className="label">Per query</div>
        <div className="mt-1.5 space-y-0.5 font-mono text-[9px]">
          {data.queries.map((q, i) => (
            <div key={i} className="flex items-center gap-2">
              <span
                className={`w-12 shrink-0 ${
                  q.brand_mentioned ? "text-jarvis-ok" : "text-jarvis/30"
                }`}
              >
                {q.brand_mentioned ? `hit #${q.brand_position ?? "?"}` : "miss"}
              </span>
              <span className="truncate text-jarvis/55">{q.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
