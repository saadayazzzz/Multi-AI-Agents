"use client";

import type { AgentState } from "@/lib/api";

const NAMES: Record<string, [string, string]> = {
  orchestrator: ["JARVIS", "Orchestrator"],
  agent1: ["Agent 1", "Trend Scout"],
  agent2: ["Agent 2", "Content Studio"],
  agent3: ["Agent 3", "Visual Studio"],
  agent4: ["Agent 4", "Publisher"],
  agent5: ["Agent 5", "AI Search Pulse"],
  geo: ["Agent 6", "AI Visibility"],
  sales: ["Agent 7", "Outbound Sales"],
  studio: ["Agent 8", "Video Studio"],
  ads: ["Agent 9", "Ad Studio"],
};
const ORDER = [
  "orchestrator", "agent1", "agent2", "agent3", "agent4", "agent5",
  "geo", "sales", "studio", "ads",
];

export function AgentGrid({ agents, busy }: { agents: AgentState[]; busy: boolean }) {
  const rows = ORDER.map(
    (a) =>
      agents.find((x) => x.actor === a) ?? {
        actor: a, state: "idle" as const,
        last_message: null, last_kind: null, last_ts: null,
      },
  );

  return (
    <div className="divide-y divide-jarvis/10">
      {rows.map((a) => {
        const active = busy && a.state === "working";
        const [name, role] = NAMES[a.actor] ?? [a.actor, ""];
        return (
          <div key={a.actor} className="flex items-start gap-3 px-3 py-2.5">
            <span
              className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                active ? "bg-jarvis anim-blip" : "bg-jarvis/20"
              }`}
              style={active ? { boxShadow: "0 0 10px #38e0d0" } : undefined}
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12px] font-medium text-jarvis-soft">{name}</span>
                <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-jarvis/35">
                  {role}
                </span>
              </div>
              <div className="mt-0.5 truncate font-mono text-[10px] text-jarvis/45">
                {a.last_message ?? "idle"}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
