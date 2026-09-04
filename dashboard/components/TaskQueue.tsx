"use client";

import { cancelTask, type Task } from "@/lib/api";

const BADGE: Record<Task["status"], string> = {
  queued: "border-jarvis/25 text-jarvis/60",
  running: "border-jarvis text-jarvis bg-jarvis/10",
  done: "border-jarvis-ok/50 text-jarvis-ok",
  failed: "border-jarvis-red/60 text-jarvis-red",
  cancelled: "border-jarvis/15 text-jarvis/35",
};

export function TaskQueue({ tasks }: { tasks: Task[] }) {
  return (
    <div className="space-y-2 p-2.5">
      {tasks.length === 0 && (
        <div className="px-1 py-2 text-[11px] text-jarvis/35">no tasks yet</div>
      )}
      {tasks.map((t) => (
        <div key={t.id} className="row-in border border-jarvis/15 bg-black/30 p-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className={`chip ${BADGE[t.status]}`}>
              {t.status}
              {t.recur_seconds ? " · loop" : ""}
            </span>
            <span className="font-mono text-[9px] text-jarvis/35">
              #{t.id} · {t.source}
            </span>
          </div>
          <div className="mt-1.5 text-[12px] leading-snug text-jarvis-soft">{t.prompt}</div>
          {t.spoken_response && t.status === "done" && (
            <div className="mt-1 border-l-2 border-jarvis-amber/40 pl-2 text-[10.5px] text-jarvis-amber">
              {t.spoken_response}
            </div>
          )}
          {t.error && (
            <div className="mt-1 border-l-2 border-jarvis-red/40 pl-2 text-[10.5px] text-jarvis-red">
              {t.error}
            </div>
          )}
          {t.status === "queued" && (
            <button
              onClick={() => cancelTask(t.id)}
              className="mt-2 font-mono text-[9px] uppercase tracking-[0.2em] text-jarvis/40 hover:text-jarvis-red"
            >
              cancel
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
