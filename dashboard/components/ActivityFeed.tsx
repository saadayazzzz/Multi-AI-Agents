"use client";

import { useEffect, useRef } from "react";
import type { TaskEvent } from "@/lib/api";

const COLOR: Record<string, string> = {
  tool_call: "text-jarvis",
  tool_result: "text-jarvis-soft/80",
  message: "text-jarvis-amber",
  spoken: "text-jarvis-amber",
  error: "text-jarvis-red",
  status: "text-jarvis/55",
  log: "text-jarvis/40",
};

const ABBR: Record<string, string> = {
  orchestrator: "orch", agent1: "a1", agent2: "a2", agent3: "a3", agent4: "a4",
  system: "sys", user: "you",
};

export function ActivityFeed({ events }: { events: TaskEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  return (
    <div className="px-2.5 py-2 font-mono text-[10.5px] leading-5">
      {events.length === 0 && (
        <div className="px-1 py-2 text-jarvis/35">awaiting command…</div>
      )}
      {events.map((e) => (
        <div
          key={e.id}
          className="row-in grid grid-cols-[3.2rem_2.2rem_1fr] gap-2 rounded px-1 py-0.5 hover:bg-jarvis/[0.05]"
        >
          <span className="text-jarvis/35">
            {new Date(e.ts).toLocaleTimeString([], { hour12: false })}
          </span>
          <span className="truncate text-jarvis/45">{ABBR[e.actor] ?? e.actor}</span>
          <span className={`${COLOR[e.kind] ?? "text-jarvis/60"} break-words`}>
            {e.message}
          </span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
