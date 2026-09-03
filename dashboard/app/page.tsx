"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createTask } from "@/lib/api";
import { useJarvis } from "@/lib/useJarvis";
import { useVoice } from "@/lib/useVoice";
import { JarvisCore, type CoreState } from "@/components/JarvisCore";
import { StatsBar } from "@/components/StatsBar";
import { AgentGrid } from "@/components/AgentGrid";
import { ActivityFeed } from "@/components/ActivityFeed";
import { TaskQueue } from "@/components/TaskQueue";
import { CommandBar } from "@/components/CommandBar";

export default function Console() {
  const { connected, stats, agents, tasks, events, latestSpoken } = useJarvis();
  const voice = useVoice();
  const [muted, setMuted] = useState(false);
  const spokenId = useRef(0);

  const busy = useMemo(
    () => tasks.some((t) => t.status === "running" || t.status === "queued"),
    [tasks],
  );

  // Speak new orchestrator lines aloud (once each).
  useEffect(() => {
    if (!latestSpoken || latestSpoken.id <= spokenId.current) return;
    spokenId.current = latestSpoken.id;
    if (!muted) voice.speak(latestSpoken.text);
  }, [latestSpoken, muted, voice]);

  // Voice transcript -> task.
  useEffect(() => {
    voice.onResult(async (text) => {
      try {
        await createTask(text, "voice");
        if (!muted) voice.speak("On it.");
      } catch {
        if (!muted) voice.speak("I could not reach the control plane.");
      }
    });
  }, [voice, muted]);

  const submitText = async (text: string) => {
    await createTask(text, "text");
  };

  const coreState: CoreState = !connected
    ? "offline"
    : voice.listening
      ? "listening"
      : voice.speaking
        ? "speaking"
        : busy
          ? "thinking"
          : "idle";

  return (
    <main className="mx-auto max-w-[1400px] px-5 py-6">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl tracking-[0.35em] text-jarvis">J A R V I S</h1>
          <p className="mt-1 font-mono text-[11px] text-slate-500">
            multi-agent skincare &amp; cosmetics control plane
          </p>
        </div>
        <div className="flex items-center gap-4 font-mono text-[11px]">
          <button
            onClick={() => setMuted((m) => !m)}
            className={`rounded border px-2 py-1 uppercase tracking-wider ${
              muted ? "border-edge text-slate-500" : "border-jarvis/50 text-jarvis"
            }`}
          >
            {muted ? "voice off" : "voice on"}
          </button>
          <span className={connected ? "text-jarvis" : "text-jarvis-red"}>
            {connected ? "● link active" : "● link down"}
          </span>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)_360px]">
        {/* left: agents + stats */}
        <div className="space-y-4">
          <StatsBar stats={stats} />
          <AgentGrid agents={agents} busy={busy} />
        </div>

        {/* center: core + command + feed */}
        <div className="flex flex-col gap-4">
          <div className="panel flex flex-col items-center py-6">
            <JarvisCore state={coreState} />
            {voice.listening && voice.interim && (
              <p className="mt-2 max-w-md text-center font-mono text-xs text-jarvis-amber">
                “{voice.interim}”
              </p>
            )}
          </div>
          <CommandBar
            supported={voice.supported}
            listening={voice.listening}
            interim={voice.interim}
            onMic={() => (voice.listening ? voice.stop() : voice.listenOnce())}
            onSubmitText={submitText}
          />
          <div className="h-[360px]">
            <ActivityFeed events={events} />
          </div>
        </div>

        {/* right: tasks */}
        <div className="h-[720px]">
          <TaskQueue tasks={tasks} />
        </div>
      </div>

      <footer className="mt-6 font-mono text-[10px] text-slate-600">
        Tasks run in the worker process — they keep going after you close this tab.
        {!voice.supported && " · This browser has no Web Speech API; use Chrome or Edge for voice."}
      </footer>
    </main>
  );
}
