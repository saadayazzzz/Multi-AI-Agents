"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createTask } from "@/lib/api";
import { useJarvis } from "@/lib/useJarvis";
import { useVoice } from "@/lib/useVoice";
import { JarvisCore, type CoreState } from "@/components/JarvisCore";
import { HudPanel, type Corner } from "@/components/HudPanel";
import { TetherLines } from "@/components/TetherLines";
import { AgentGrid } from "@/components/AgentGrid";
import { ActivityFeed } from "@/components/ActivityFeed";
import { TaskQueue } from "@/components/TaskQueue";
import { Analytics } from "@/components/Analytics";
import { CommandBar } from "@/components/CommandBar";

const CORE_COPY: Record<CoreState, string> = {
  idle: "Standing by",
  listening: "Listening",
  thinking: "Working",
  speaking: "Responding",
  offline: "Link down",
};

export default function Console() {
  const { connected, stats, agents, tasks, events, latestSpoken } = useJarvis();
  const voice = useVoice();
  const [muted, setMuted] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [pulse, setPulse] = useState(false);
  const [flash, setFlash] = useState(0);
  const spokenId = useRef(0);
  const pulseTimer = useRef<ReturnType<typeof setTimeout>>();

  const busy = useMemo(
    () => tasks.some((t) => t.status === "running" || t.status === "queued"),
    [tasks],
  );
  const hudActive = pinned || busy || events.length > 0 || pulse;

  // Panels unfold one at a time in this order, each ~0.5s after the previous.
  const ORDER: Corner[] = ["tr", "tl", "br", "bl"];
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!hudActive) {
      setStep(0);
      return;
    }
    let s = step;
    const tick = () => {
      s += 1;
      setStep(s);
    };
    const first = setTimeout(tick, 140);
    const iv = setInterval(() => {
      if (s >= ORDER.length) {
        clearInterval(iv);
        return;
      }
      tick();
    }, 480);
    return () => {
      clearTimeout(first);
      clearInterval(iv);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hudActive]);

  const shown = ORDER.slice(0, step);
  const isOpen = (c: Corner) => shown.includes(c);

  useEffect(() => {
    if (!latestSpoken || latestSpoken.id <= spokenId.current) return;
    spokenId.current = latestSpoken.id;
    if (!muted) voice.speak(latestSpoken.text);
  }, [latestSpoken, muted, voice]);

  const reveal = useCallback(() => {
    setPulse(true);
    setFlash((f) => f + 1);
    clearTimeout(pulseTimer.current);
    pulseTimer.current = setTimeout(() => setPulse(false), 18000);
  }, []);

  useEffect(() => {
    voice.onResult(async (text) => {
      reveal();
      try {
        await createTask(text, "voice");
        if (!muted) voice.speak("On it.");
      } catch {
        if (!muted) voice.speak("I could not reach the control plane.");
      }
    });
  }, [voice, muted, reveal]);

  const submitText = async (text: string) => {
    reveal();
    try {
      await createTask(text, "text");
    } catch {
      /* surfaced via link status */
    }
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
    <div className="hud-stage relative h-screen w-screen overflow-hidden">
      {/* backdrop */}
      <div className="hud-grid pointer-events-none absolute inset-0" />
      <div className="anim-spin-cw pointer-events-none absolute left-1/2 top-1/2 h-[170vh] w-[170vh] -translate-x-1/2 -translate-y-1/2 rounded-full border border-jarvis/[0.06]" />
      <div className="hud-vignette pointer-events-none absolute inset-0" />
      {flash > 0 && <span key={flash} className="stage-flash" />}

      {/* beams from core -> panels (drawn one at a time) */}
      <TetherLines shown={shown} />

      {/* top bar */}
      <header className="pointer-events-auto absolute inset-x-0 top-0 z-20 flex items-center justify-between px-5 py-3">
        <div className="flex items-baseline gap-3">
          <span className="holo font-mono text-sm font-semibold tracking-[0.5em] text-jarvis">
            JARVIS
          </span>
          <span className="hidden font-mono text-[10px] text-jarvis/35 md:inline">
            multi-agent control plane
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setMuted((m) => !m)}
            className={`chip ${muted ? "opacity-50" : ""}`}
          >
            {muted ? "voice off" : "voice on"}
          </button>
          <button
            onClick={() => setPinned((p) => !p)}
            className={`chip ${pinned ? "bg-jarvis/20 text-jarvis" : "opacity-60"}`}
          >
            {pinned ? "panels pinned" : "pin panels"}
          </button>
          <span className={`chip ${connected ? "" : "border-jarvis-red/40 text-jarvis-red"}`}>
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                connected ? "bg-jarvis anim-blip" : "bg-jarvis-red"
              }`}
            />
            {connected ? "online" : "offline"}
          </span>
        </div>
      </header>

      {/* four corner windows — burst out of the core, one after another */}
      <HudPanel corner="tr" open={isOpen("tr")} title="Activity" count={events.length}>
        <ActivityFeed events={events} />
      </HudPanel>

      <HudPanel corner="tl" open={isOpen("tl")} title="Agents" count={agents.length || 5}>
        <AgentGrid agents={agents} busy={busy} />
      </HudPanel>

      <HudPanel corner="br" open={isOpen("br")} title="Analytics">
        <Analytics stats={stats} tasks={tasks} />
      </HudPanel>

      <HudPanel corner="bl" open={isOpen("bl")} title="Tasks" count={tasks.length}>
        <TaskQueue tasks={tasks} />
      </HudPanel>

      {/* center — core + command */}
      <div
        className={`pointer-events-none absolute inset-0 z-0 flex flex-col items-center justify-center gap-5 transition-transform duration-500 ${
          step > 0 ? "scale-[0.9]" : ""
        }`}
      >
        <JarvisCore state={coreState} />
        <div className="flex h-5 items-center gap-2">
          <span className="label holo">{CORE_COPY[coreState]}</span>
          {voice.listening && voice.interim && (
            <span className="row-in max-w-sm truncate font-mono text-xs text-jarvis-amber">
              “{voice.interim}”
            </span>
          )}
        </div>
        <CommandBar
          supported={voice.supported}
          listening={voice.listening}
          interim={voice.interim}
          onMic={() => (voice.listening ? voice.stop() : voice.listenOnce())}
          onSubmitText={submitText}
        />
        {!voice.supported && (
          <span className="font-mono text-[10px] text-jarvis/30">
            voice needs Chrome or Edge — typing works everywhere
          </span>
        )}
      </div>
    </div>
  );
}
