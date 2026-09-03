"use client";

import { useEffect, useRef } from "react";
import type { TaskEvent } from "@/lib/api";

const COLOR: Record<string, string> = {
  tool_call: "text-jarvis",
  tool_result: "text-slate-300",
  message: "text-jarvis-amber",
  spoken: "text-jarvis-amber",
  error: "text-jarvis-red",
  status: "text-slate-400",
  log: "text-slate-500",
};

export function ActivityFeed({ events }: { events: TaskEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="panel flex h-full flex-col">
      <div className="border-b border-edge px-4 py-2 label">Activity</div>
      <div className="flex-1 space-y-1 overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed">
        {events.length === 0 && (
          <div className="text-slate-600">Waiting for the first command…</div>
        )}
        {events.map((e) => (
          <div key={e.id} className="flex gap-2">
            <span className="shrink-0 text-slate-600">
              {new Date(e.ts).toLocaleTimeString([], { hour12: false })}
            </span>
            <span className="shrink-0 text-slate-600">[{e.actor}]</span>
            <span className={COLOR[e.kind] ?? "text-slate-400"}>{e.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
