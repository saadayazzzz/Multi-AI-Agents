"use client";

import { useEffect, useState } from "react";
import { getOutreachLatest, type OutreachLatest } from "@/lib/api";

const STAGES = ["new", "enriched", "scored", "drafted", "sent", "replied", "positive"];
const STAGE_COLOR: Record<string, string> = {
  new: "text-jarvis/50",
  enriched: "text-jarvis/70",
  scored: "text-jarvis",
  drafted: "text-jarvis-soft",
  sent: "text-jarvis-amber",
  replied: "text-jarvis-amber",
  positive: "text-jarvis-ok",
};

export function OutreachPanel() {
  const [d, setD] = useState<OutreachLatest | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getOutreachLatest()
        .then((r) => alive && r && setD(r))
        .catch(() => {});
    load();
    const iv = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  if (!d) {
    return (
      <div className="px-3 py-2 font-mono text-[10px] text-jarvis/35">
        no campaign yet — ask AUREN to “run outreach” with an ICP and an offer
      </div>
    );
  }

  const max = Math.max(1, ...STAGES.map((s) => d.counts[s] ?? 0));

  return (
    <div className="space-y-3 p-3">
      <div className="border border-jarvis/15 bg-black/25 px-3 py-2">
        <div className="label">Pipeline · {d.total} leads</div>
        <div className="mt-2 space-y-1">
          {STAGES.filter((s) => d.counts[s]).map((s) => (
            <div key={s} className="flex items-center gap-2 font-mono text-[9px]">
              <span className={`w-16 shrink-0 uppercase tracking-wider ${STAGE_COLOR[s]}`}>{s}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-jarvis/10">
                <span
                  className="block h-full bg-jarvis/60"
                  style={{ width: `${((d.counts[s] ?? 0) / max) * 100}%` }}
                />
              </span>
              <span className="w-5 text-right text-jarvis/55">{d.counts[s]}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="border border-jarvis/15 bg-black/25 px-3 py-2">
        <div className="label">Leads</div>
        <div className="mt-1.5 space-y-1 font-mono text-[9px]">
          {d.leads.map((l) => (
            <div key={l.id} className="flex items-center gap-2">
              <span className={`w-14 shrink-0 uppercase ${STAGE_COLOR[l.status] ?? "text-jarvis/40"}`}>
                {l.status}
              </span>
              <span className="w-8 shrink-0 text-right text-jarvis/45">
                {l.geo_score != null ? Number(l.geo_score).toFixed(0) : "-"}
              </span>
              <span className="w-32 shrink-0 truncate text-jarvis-soft">{l.company}</span>
              <span className="truncate text-jarvis/40">{l.contact_email}</span>
            </div>
          ))}
        </div>
      </div>

      {d.sample && (
        <div className="border border-jarvis/15 bg-black/25 px-3 py-2">
          <div className="label">Latest draft · {d.sample.company}</div>
          <div className="mt-1 font-mono text-[10px] text-jarvis">{d.sample.subject}</div>
          <div className="mt-1 whitespace-pre-wrap font-mono text-[9px] leading-relaxed text-jarvis/55">
            {d.sample.body.slice(0, 320)}
          </div>
        </div>
      )}
    </div>
  );
}
