"use client";

import { cancelTask, type Task } from "@/lib/api";

const BADGE: Record<Task["status"], string> = {
  queued: "border-slate-600 text-slate-400",
  running: "border-jarvis text-jarvis",
  done: "border-emerald-600 text-emerald-400",
  failed: "border-jarvis-red text-jarvis-red",
  cancelled: "border-slate-700 text-slate-600",
};

export function TaskQueue({ tasks }: { tasks: Task[] }) {
  return (
    <div className="panel flex h-full flex-col">
      <div className="border-b border-edge px-4 py-2 label">Tasks</div>
      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {tasks.length === 0 && <div className="px-1 text-xs text-slate-600">No tasks yet.</div>}
        {tasks.map((t) => (
          <div key={t.id} className="rounded-lg border border-edge bg-void/40 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase ${BADGE[t.status]}`}>
                {t.status}
                {t.recur_seconds ? " · loop" : ""}
              </span>
              <span className="font-mono text-[10px] text-slate-600">
                #{t.id} · {t.source}
              </span>
            </div>
            <div className="mt-1.5 text-sm text-slate-200">{t.prompt}</div>
            {t.spoken_response && t.status === "done" && (
              <div className="mt-1 text-xs text-jarvis-amber">↳ {t.spoken_response}</div>
            )}
            {t.error && <div className="mt-1 text-xs text-jarvis-red">↳ {t.error}</div>}
            {t.status === "queued" && (
              <button
                onClick={() => cancelTask(t.id)}
                className="mt-2 font-mono text-[10px] uppercase tracking-wider text-slate-500 hover:text-jarvis-red"
              >
                cancel
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
