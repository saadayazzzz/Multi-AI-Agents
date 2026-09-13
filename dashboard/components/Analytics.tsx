"use client";

import type { Stats, Task } from "@/lib/api";

function Tile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-jarvis/15 bg-black/25 px-2.5 py-2">
      <div className="label">{label}</div>
      <div className="mt-1 font-mono text-lg leading-none text-jarvis holo">{value}</div>
    </div>
  );
}

export function Analytics({ stats, tasks }: { stats: Stats | null; tasks: Task[] }) {
  const dash = (n: number | undefined) => (n == null ? "–" : n);

  const tally = tasks.reduce<Record<string, number>>((m, t) => {
    m[t.status] = (m[t.status] ?? 0) + 1;
    return m;
  }, {});
  const done = tally.done ?? 0;
  const failed = tally.failed ?? 0;
  const active = (tally.running ?? 0) + (tally.queued ?? 0);
  const total = done + failed + active || 1;

  const contentByStatus = stats?.content_by_status ?? {};
  const maxStatus = Math.max(1, ...Object.values(contentByStatus));
  const posted = Object.values(stats?.posted_by_platform ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-3 p-3">
      <div className="grid grid-cols-2 gap-2">
        <Tile label="Trends" value={dash(stats?.trends_total)} />
        <Tile label="Content Drafted" value={dash(stats?.content_total)} />
        <Tile label="Posts Published" value={dash(posted)} />
        <Tile label="Tasks" value={tasks.length} />
      </div>

      <div className="border border-jarvis/15 bg-black/25 px-2.5 py-2">
        <div className="label">Task health</div>
        <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-jarvis/10">
          <div className="bg-jarvis-ok" style={{ width: `${(done / total) * 100}%` }} />
          <div className="bg-jarvis-red" style={{ width: `${(failed / total) * 100}%` }} />
          <div className="bg-jarvis-amber" style={{ width: `${(active / total) * 100}%` }} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[9px] text-jarvis/55">
          <span className="text-jarvis-ok">■ {done} done</span>
          <span className="text-jarvis-red">■ {failed} failed</span>
          <span className="text-jarvis-amber">■ {active} active</span>
        </div>
      </div>

      <div className="border border-jarvis/15 bg-black/25 px-2.5 py-2">
        <div className="label">Content by status</div>
        <div className="mt-2 space-y-1.5">
          {Object.entries(contentByStatus).length === 0 && (
            <div className="font-mono text-[9px] text-jarvis/35">no content yet</div>
          )}
          {Object.entries(contentByStatus).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 font-mono text-[9px] text-jarvis/55">
              <span className="w-24 shrink-0 uppercase tracking-wider">{k}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-jarvis/10">
                <span
                  className="block h-full bg-jarvis/60"
                  style={{ width: `${(v / maxStatus) * 100}%` }}
                />
              </span>
              <span className="w-5 text-right">{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
