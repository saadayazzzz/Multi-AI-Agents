"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createTask,
  getContent,
  getGeoLatest,
  getOutreachLatest,
  setPower,
  type ContentPiece,
  type GeoLatest,
  type OutreachLatest,
} from "@/lib/api";
import { useJarvis } from "@/lib/useJarvis";
import { useVoice } from "@/lib/useVoice";
import { useClapDetector } from "@/lib/useClapDetector";
import { JarvisCore, type CoreState } from "@/components/JarvisCore";
import { StarField } from "@/components/StarField";
import { HudPanel, type Corner } from "@/components/HudPanel";
import { TetherLines } from "@/components/TetherLines";
import { MarketFeed } from "@/components/MarketFeed";
import { CoreCallouts } from "@/components/CoreCallouts";
import { AgentGrid } from "@/components/AgentGrid";
import { ActivityFeed } from "@/components/ActivityFeed";
import { TaskQueue } from "@/components/TaskQueue";
import { ApprovalQueue } from "@/components/ApprovalQueue";
import { ContentReviewModal } from "@/components/ContentReviewModal";
import { Analytics } from "@/components/Analytics";
import { GeoScore } from "@/components/GeoScore";
import { OutreachPanel } from "@/components/OutreachPanel";
import { StudioPanel } from "@/components/StudioPanel";
import { AdsPanel } from "@/components/AdsPanel";
import { CommandBar } from "@/components/CommandBar";

const CORE_COPY: Record<CoreState, string> = {
  idle: "Standing by",
  listening: "Listening",
  thinking: "Working",
  speaking: "Responding",
  offline: "Link down",
};

export default function Console() {
  const { connected, stats, agents, tasks, events, trends, latestSpoken } = useJarvis();
  const voice = useVoice();
  const [muted, setMuted] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [pulse, setPulse] = useState(false);
  const [flash, setFlash] = useState(0);
  const [localPower, setLocalPower] = useState<"on" | "off" | null>(null);
  const [geo, setGeo] = useState<GeoLatest | null>(null);
  const [outreach, setOutreach] = useState<OutreachLatest | null>(null);
  const spokenId = useRef(0);

  useEffect(() => {
    let alive = true;
    const load = () => {
      getGeoLatest().then((d) => alive && d && setGeo(d)).catch(() => {});
      getOutreachLatest().then((d) => alive && d && setOutreach(d)).catch(() => {});
    };
    load();
    const iv = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);
  const pulseTimer = useRef<ReturnType<typeof setTimeout>>();
  const [content, setContent] = useState<ContentPiece[]>([]);
  const refreshContent = useCallback(() => {
    getContent().then(setContent).catch(() => {});
  }, []);
  useEffect(() => {
    refreshContent();
    const iv = setInterval(refreshContent, 5000);
    return () => clearInterval(iv);
  }, [refreshContent]);
  const awaitingApproval = useMemo(() => content.filter((c) => c.status === "ready"), [content]);
  const [reviewing, setReviewing] = useState<ContentPiece | null>(null);

  const power = localPower ?? stats?.power ?? "on";
  const off = power === "off";

  useEffect(() => {
    if (localPower && stats?.power === localPower) setLocalPower(null);
  }, [stats?.power, localPower]);

  const togglePower = async () => {
    const next = off ? "on" : "off";
    setLocalPower(next);
    try {
      await setPower(next);
    } catch {
      /* snapshot will correct on reconnect */
    }
  };

  const busy = useMemo(
    () => tasks.some((t) => t.status === "running" || t.status === "queued"),
    [tasks],
  );
  const hudActive = !off && (pinned || busy || events.length > 0 || pulse);

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

  useClapDetector(off, () => {
    setLocalPower("on");
    reveal();
    if (!muted) voice.speak("Back online, Sir Saad.");
    setPower("on").catch(() => {
      /* snapshot will correct on reconnect */
    });
  });

  useEffect(() => {
    voice.onResult(async (text) => {
      if (off) return;
      if (/\bshut\s*down\b/i.test(text)) {
        reveal();
        setLocalPower("off");
        if (!muted) voice.speak("Shutting down, Sir Saad.");
        try {
          await setPower("off");
        } catch {
          /* snapshot will correct on reconnect */
        }
        return;
      }
      reveal();
      try {
        await createTask(text, "voice");
        if (!muted) voice.speak("On it.");
      } catch {
        if (!muted) voice.speak("I could not reach the control plane.");
      }
    });
  }, [voice, muted, reveal, off]);

  const submitText = async (text: string) => {
    if (off) return;
    reveal();
    try {
      await createTask(text, "text");
    } catch {
      /* surfaced via link status */
    }
  };

  const coreState: CoreState = off || !connected
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
      <StarField />
      <div className="hud-grid pointer-events-none absolute inset-0" />
      <div className="anim-spin-cw pointer-events-none absolute left-1/2 top-1/2 h-[170vh] w-[170vh] -translate-x-1/2 -translate-y-1/2 rounded-full border border-jarvis/[0.06]" />
      <div className="hud-vignette pointer-events-none absolute inset-0" />
      {flash > 0 && <span key={flash} className="stage-flash" />}

      {/* beams from core -> panels (drawn one at a time) */}
      <TetherLines shown={shown} />

      {/* trend radar — mini headlines on the core's radial lines + bottom ticker */}
      <CoreCallouts items={off ? [] : trends} />
      <MarketFeed items={off ? [] : trends} />

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
            disabled={off}
            className={`chip ${muted ? "opacity-50" : ""} disabled:opacity-30`}
          >
            {muted ? "voice off" : "voice on"}
          </button>
          <button
            onClick={() => setPinned((p) => !p)}
            disabled={off}
            className={`chip ${pinned ? "bg-jarvis/20 text-jarvis" : "opacity-60"} disabled:opacity-30`}
          >
            {pinned ? "panels pinned" : "pin panels"}
          </button>
          <span
            className={`chip ${
              off
                ? "border-jarvis-red/50 text-jarvis-red"
                : connected
                  ? ""
                  : "border-jarvis-red/40 text-jarvis-red"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                off
                  ? "bg-jarvis-red"
                  : connected
                    ? "bg-jarvis anim-blip"
                    : "bg-jarvis-red"
              }`}
            />
            {off ? "powered down" : connected ? "online" : "offline"}
          </span>
          <button
            onClick={togglePower}
            title={off ? "Power on JARVIS" : "Shut JARVIS down"}
            className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border transition ${
              off
                ? "border-jarvis-red bg-jarvis-red/10 text-jarvis-red anim-blip"
                : "border-jarvis/50 text-jarvis hover:bg-jarvis/15"
            }`}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round">
              <path d="M12 3v9" />
              <path d="M6.6 6.6a9 9 0 1 0 10.8 0" />
            </svg>
          </button>
        </div>
      </header>

      {/* four corner windows — burst out of the core, one after another */}
      <HudPanel corner="tr" open={isOpen("tr")} title="Activity" count={events.length}>
        <ActivityFeed events={events} />
      </HudPanel>

      <HudPanel corner="tl" open={isOpen("tl")} title="Agents" count={agents.length || 9}>
        <AgentGrid agents={agents} busy={busy} />
      </HudPanel>

      <HudPanel corner="br" open={isOpen("br")} title="Visibility · Analytics">
        <GeoScore />
        <div className="border-t border-jarvis/15" />
        <Analytics stats={stats} tasks={tasks} />
      </HudPanel>

      <HudPanel corner="bl" open={isOpen("bl")} title="Studio · Pipeline · Tasks" count={tasks.length}>
        <StudioPanel />
        <div className="border-t border-jarvis/15" />
        <AdsPanel />
        <div className="border-t border-jarvis/15" />
        <OutreachPanel />
        <div className="border-t border-jarvis/15" />
        <ApprovalQueue items={awaitingApproval} onApproved={refreshContent} onOpen={setReviewing} />
        <div className="border-t border-jarvis/15" />
        <TaskQueue tasks={tasks} />
      </HudPanel>

      <ContentReviewModal
        content={reviewing}
        onClose={() => setReviewing(null)}
        onApproved={refreshContent}
      />

      {/* center — core + command */}
      <div
        className={`pointer-events-none absolute inset-0 z-0 flex flex-col items-center justify-center gap-5 transition-transform duration-500 ${
          step > 0 ? "scale-[0.9]" : ""
        }`}
      >
        <div
          className={`flex flex-col items-center gap-5 transition-all duration-500 ${
            off ? "opacity-25 grayscale" : ""
          }`}
        >
          <JarvisCore
            state={coreState}
            readouts={[
              {
                label: "Score",
                value: geo ? Number(geo.score.score).toFixed(0) : "–",
              },
              { label: "Leads", value: outreach?.total ?? "–" },
              { label: "Content", value: stats?.content_total ?? "–" },
              { label: "Feed", value: trends.length },
            ]}
          />
          <div className="flex h-5 items-center gap-2">
            <span
              className={`label holo ${coreState === "speaking" ? "anim-label-blink text-jarvis-soft" : ""}`}
            >
              {off ? "Powered down" : coreState === "speaking" ? "◂ Speaking ▸" : CORE_COPY[coreState]}
            </span>
            {voice.listening && voice.interim && (
              <span className="row-in max-w-sm truncate font-mono text-xs text-jarvis-amber">
                “{voice.interim}”
              </span>
            )}
          </div>
        </div>
        <CommandBar
          supported={voice.supported}
          listening={voice.listening}
          interim={voice.interim}
          onMic={() => (voice.listening ? voice.stop() : voice.listenOnce())}
          onSubmitText={submitText}
          disabled={off}
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
