"use client";

import { useEffect, useState } from "react";
import type { AgentState, Task, TaskEvent } from "@/lib/api";

function hms(ms: number) {
  const s = Math.floor(ms / 1000);
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((n) => String(n).padStart(2, "0")).join(":");
}

/** Helmet-style telemetry around the screen edge — every number here is live. */
export function EdgeFrame({
  events,
  tasks,
  agents,
  connected,
  off,
}: {
  events: TaskEvent[];
  tasks: Task[];
  agents: AgentState[];
  connected: boolean;
  off: boolean;
}) {
  // clock values only exist after mount, so server and client HTML always match
  const [clock, setClock] = useState<{ start: number; now: number } | null>(null);
  useEffect(() => {
    const start = Date.now();
    setClock({ start, now: start });
    const iv = setInterval(() => setClock({ start, now: Date.now() }), 1000);
    return () => clearInterval(iv);
  }, []);

  const now = clock?.now ?? 0;
  const perMin = clock ? events.filter((e) => now - new Date(e.ts).getTime() < 60000).length : 0;
  const running = tasks.filter((t) => t.status === "running").length;
  const queued = tasks.filter((t) => t.status === "queued").length;
  const working = agents.filter((a) => a.state === "working").length;
  const utc = clock ? new Date(now).toISOString().slice(11, 19) : "--:--:--";
  const uptime = clock ? hms(now - clock.start) : "--:--:--";
  const status = off ? "POWERED DOWN" : connected ? "ONLINE" : "LINK LOST";
  const statusColor = off || !connected ? "text-jarvis-red" : "text-jarvis";

  const bracket = "absolute h-7 w-7 border-jarvis/60";

  return (
    <div className="pointer-events-none fixed inset-0 z-[3] font-mono text-[9px] uppercase tracking-[0.22em] text-jarvis/45">
      <span className={`${bracket} left-2 top-2 border-l border-t`} />
      <span className={`${bracket} right-2 top-2 border-r border-t`} />
      <span className={`${bracket} bottom-8 left-2 border-b border-l`} />
      <span className={`${bracket} bottom-8 right-2 border-b border-r`} />

      <div className="ruler absolute bottom-[22%] left-[7px] top-[22%] w-[6px]" />
      <div className="ruler ruler-rev absolute bottom-[22%] right-[7px] top-[22%] w-[6px]" />

      <div
        className="absolute left-[14px] top-1/2 -translate-y-1/2 whitespace-nowrap"
        style={{ writingMode: "vertical-rl", transform: "translateY(-50%) rotate(180deg)" }}
      >
        SYS // <span className={statusColor}>{status}</span> — UPTIME {uptime}
      </div>
      <div
        className="absolute right-[14px] top-1/2 -translate-y-1/2 whitespace-nowrap"
        style={{ writingMode: "vertical-rl" }}
      >
        EVT/MIN <span className="text-jarvis">{perMin}</span> · TASKS{" "}
        <span className="text-jarvis">
          {running}/{queued}
        </span>{" "}
        · AGENTS <span className="text-jarvis">{working}</span>/{agents.length || 9} · {utc}Z
      </div>
    </div>
  );
}
