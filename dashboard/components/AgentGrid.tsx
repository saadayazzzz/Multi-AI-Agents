"use client";

import type { AgentState } from "@/lib/api";

const NAMES: Record<string, string> = {
  orchestrator: "JARVIS · Orchestrator",
  agent1: "Agent 1 · Discovery",
  agent2: "Agent 2 · Scrape & Store",
  agent3: "Agent 3 · Brand Builder",
  agent4: "Agent 4 · Product Imagery",
};

export function AgentGrid({ agents, busy }: { agents: AgentState[]; busy: boolean }) {
  const ordered = ["orchestrator", "agent1", "agent2", "agent3", "agent4"].map(
    (a) => agents.find((x) => x.actor === a) ?? { actor: a, state: "idle" as const, last_message: null, last_kind: null, last_ts: null },
  );
  return (
    <div className="space-y-2">
      <div className="label">Agents</div>
      {ordered.map((a) => {
        const active = busy && a.state === "working";
        return (
          <div key={a.actor} className="panel flex items-start gap-3 px-3 py-2.5">
            <span
              className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                active ? "bg-jarvis shadow-glow" : "bg-edge"
              }`}
              style={active ? { animation: "flicker 1s infinite" } : undefined}
            />
            <div className="min-w-0">
              <div className="text-sm text-slate-200">{NAMES[a.actor] ?? a.actor}</div>
              <div className="truncate font-mono text-xs text-slate-500">
                {a.last_message ?? "no activity yet"}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
