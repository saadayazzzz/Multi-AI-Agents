"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createTask,
  getGeoLatest,
  getOutreachLatest,
  setPower,
  type GeoLatest,
  type OutreachLatest,
} from "@/lib/api";
import { useJarvis } from "@/lib/useJarvis";
import { BRITISH_VOICES, useVoice } from "@/lib/useVoice";
import { sfx } from "@/lib/sfx";
import { HoloCore, type CoreState } from "@/components/HoloCore";
import { HudPanel, type Corner } from "@/components/HudPanel";
import { TetherLines } from "@/components/TetherLines";
import { HoloToasts } from "@/components/HoloToasts";
import { EdgeFrame } from "@/components/EdgeFrame";
import { MarketFeed } from "@/components/MarketFeed";
import { AgentGrid } from "@/components/AgentGrid";
import { ActivityFeed } from "@/components/ActivityFeed";
import { TaskQueue } from "@/components/TaskQueue";
import { Analytics } from "@/components/Analytics";
import { GeoScore } from "@/components/GeoScore";
import { OutreachPanel } from "@/components/OutreachPanel";
import { StudioPanel } from "@/components/StudioPanel";
import { CommandBar } from "@/components/CommandBar";

const CORE_COPY: Record<CoreState, string> = {
  idle: "Standing by",
  listening: "Listening",
  thinking: "Processing",
  speaking: "Responding",
  offline: "Link down",
};

const ORDER: Corner[] = ["tr", "tl", "br", "bl"];
const BOOT_MS = 1900;
const HOLD_OPEN_MS = 30000;
const STALL_MS = 20000;
// label sits just under the reactor — same formula as coreRadiusPx, in CSS
const UNDER_CORE = "calc(50% + min(28vh, 19vw, 285px) + 16px)";

export default function Console() {
  const { connected, stats, agents, tasks, events, market, latestSpoken } = useJarvis();
  const voice = useVoice();
  const [muted, setMuted] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [flash, setFlash] = useState(0);
  const [localPower, setLocalPower] = useState<"on" | "off" | null>(null);
  const [geo, setGeo] = useState<GeoLatest | null>(null);
  const [outreach, setOutreach] = useState<OutreachLatest | null>(null);
  const [bootPhase, setBootPhase] = useState<0 | 1 | 2>(0);
  const [openUntil, setOpenUntil] = useState<Record<Corner, number>>({ tl: 0, tr: 0, bl: 0, br: 0 });
  const [pulses, setPulses] = useState<Record<Corner, number>>({ tl: 0, tr: 0, bl: 0, br: 0 });
  const [now, setNow] = useState(() => Date.now());
  const spokenId = useRef(0);
  const bootedRef = useRef(false);

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

  // ---- boot: reactor draws in, then the panels unfold one after another ----
  useEffect(() => {
    sfx("boot", true);
    const timers = [
      setTimeout(() => {
        bootedRef.current = true;
        setBootPhase(1);
      }, BOOT_MS),
      setTimeout(() => setBootPhase(2), BOOT_MS + 2200),
      ...ORDER.map((c, i) =>
        setTimeout(
          () => setOpenUntil((o) => ({ ...o, [c]: Date.now() + HOLD_OPEN_MS })),
          BOOT_MS + 200 + i * 420,
        ),
      ),
    ];
    return () => timers.forEach(clearTimeout);
  }, []);

  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);

  // ---- panels pop open on their own when their data changes ----
  const bump = useCallback((c: Corner) => {
    if (!bootedRef.current) return;
    setOpenUntil((o) => ({ ...o, [c]: Math.max(o[c], Date.now() + HOLD_OPEN_MS) }));
    setPulses((p) => ({ ...p, [c]: p[c] + 1 }));
  }, []);

  const agentSig = agents.map((a) => `${a.actor}:${a.state}:${a.last_ts}`).join("|");
  const taskSig = tasks.map((t) => `${t.id}:${t.status}`).join("|");
  const intelSig = `${geo?.score.computed_at ?? ""}|${outreach?.total ?? ""}|${JSON.stringify(
    outreach?.counts ?? {},
  )}|${stats?.sites_total ?? ""}`;

  useEffect(() => {
    if (events.length) bump("tr");
  }, [events.length, bump]);
  useEffect(() => {
    if (agentSig) bump("tl");
  }, [agentSig, bump]);
  useEffect(() => {
    if (taskSig) bump("bl");
  }, [taskSig, bump]);
  useEffect(() => {
    bump("br");
  }, [intelSig, bump]);

  const isOpen = (c: Corner) => !off && (pinned || openUntil[c] > now);
  const shown = ORDER.filter(isOpen);
  const shownKey = shown.join(",");

  const prevShown = useRef("");
  useEffect(() => {
    const before = new Set(prevShown.current.split(","));
    if (shown.some((c) => !before.has(c))) sfx("open", !muted);
    prevShown.current = shownKey;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownKey]);

  // a request nobody has picked up for a while means the worker process is down
  const running = tasks.some((t) => t.status === "running");
  const waiting = tasks.filter((t) => t.status === "queued" && !t.recur_seconds);
  const stalled = !running && waiting.some((t) => now - new Date(t.created_at).getTime() > STALL_MS);
  const busy = running || (waiting.length > 0 && !stalled);

  useEffect(() => {
    if (stalled && !muted) voice.speak("My task worker is offline, so your request is waiting in the queue.");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stalled]);

  useEffect(() => {
    if (!latestSpoken || latestSpoken.id <= spokenId.current) return;
    spokenId.current = latestSpoken.id;
    if (!muted) voice.speak(latestSpoken.text);
  }, [latestSpoken, muted, voice]);

  const reveal = useCallback(() => {
    setFlash((f) => f + 1);
    bump("tr");
    bump("bl");
  }, [bump]);

  useEffect(() => {
    voice.onResult(async (text) => {
      if (off) return;
      reveal();
      try {
        await createTask(text, "voice");
        if (!muted) voice.speak("On it.");
      } catch {
        if (!muted) voice.speak("I could not reach the control plane.");
      }
    });
  }, [voice, muted, reveal, off]);

  const cycleVoice = () => {
    const i = BRITISH_VOICES.findIndex((v) => v.id === voice.voice);
    const next = BRITISH_VOICES[(i + 1) % BRITISH_VOICES.length];
    voice.setVoice(next.id);
    if (!muted) voice.speak("Good evening, sir. AUREN at your service.");
  };
  const voiceName = BRITISH_VOICES.find((v) => v.id === voice.voice)?.name ?? "George";
  const voiceTag =
    voice.engine === "loading"
      ? ` · ${Math.round(voice.progress * 100)}%`
      : voice.engine === "browser"
        ? " · basic"
        : " · hd";

  const submitText = async (text: string) => {
    if (off) return;
    reveal();
    try {
      await createTask(text, "text");
    } catch {
      /* surfaced via link status */
    }
  };

  const coreState: CoreState =
    off || !connected
      ? "offline"
      : voice.listening
        ? "listening"
        : voice.speaking
          ? "speaking"
          : busy
            ? "thinking"
            : "idle";

  const statusLine =
    bootPhase === 0
      ? "Initializing A.U.R.E.N."
      : bootPhase === 1 && !off
        ? "All systems online"
        : off
          ? "Powered down"
          : stalled
            ? "Worker offline — request waiting"
            : coreState === "speaking"
            ? "◂ Responding ▸"
            : CORE_COPY[coreState];

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-void">
      <HoloCore
        state={coreState}
        level={voice.level}
        readouts={[
          { label: "AI Visibility", value: geo ? Number(geo.score.score).toFixed(0) : "–" },
          { label: "Leads", value: outreach?.total ?? "–" },
          { label: "Sent", value: outreach?.counts?.sent ?? 0 },
          { label: "Intel", value: market.length },
        ]}
      />
      <div className="hud-vignette pointer-events-none fixed inset-0 z-[1]" />
      {flash > 0 && <span key={flash} className="stage-flash z-[2]" />}

      <EdgeFrame events={events} tasks={tasks} agents={agents} connected={connected} off={off} />
      <TetherLines shown={shown} />
      <HoloToasts events={events} market={market} tasks={tasks} enabled={bootPhase > 0 && !off} sound={!muted} />
      <MarketFeed items={off ? [] : market} />

      {/* top bar */}
      <header className="pointer-events-auto absolute inset-x-0 top-0 z-20 flex items-center justify-between px-12 py-4">
        <div className="flex items-center gap-3">
          <svg width="30" height="30" viewBox="0 0 30 30" className="anim-spin-cw" style={{ animationDuration: "8s" }}>
            <circle cx="15" cy="15" r="13" fill="none" stroke="#5ad8ff" strokeOpacity="0.5" strokeDasharray="3 4" />
            <circle cx="15" cy="15" r="8" fill="none" stroke="#e8fbff" strokeWidth="1.5" strokeDasharray="30 20" />
            <circle cx="15" cy="15" r="2.5" fill="#e8fbff" />
          </svg>
          <div>
            <div className="holo-hot font-display text-[15px] tracking-[0.42em]">A.U.R.E.N.</div>
            <div className="font-display text-[6.5px] uppercase tracking-[0.34em] text-jarvis/40">
              Autonomous UGC, Revenue &amp; Engagement Nexus
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setMuted((m) => !m)} disabled={off} className={`chip ${muted ? "opacity-50" : ""} disabled:opacity-30`}>
            {muted ? "voice off" : "voice on"}
          </button>
          <button
            onClick={cycleVoice}
            disabled={off}
            title="Change AUREN's voice"
            className={`chip ${voice.engine === "neural" ? "" : "opacity-70"} disabled:opacity-30`}
          >
            {voiceName}
            {voiceTag}
          </button>
          <button
            onClick={() => setPinned((p) => !p)}
            disabled={off}
            className={`chip ${pinned ? "bg-jarvis/20 text-jarvis" : "opacity-60"} disabled:opacity-30`}
          >
            {pinned ? "panels pinned" : "pin panels"}
          </button>
          <a href="/gods-eye" className="chip opacity-60 hover:opacity-100">
            god&apos;s eye
          </a>
          <span className={`chip ${off || !connected ? "border-jarvis-red/50 text-jarvis-red" : ""}`}>
            <span
              className={`h-1.5 w-1.5 rounded-full ${off || !connected ? "bg-jarvis-red" : "bg-jarvis anim-blip"}`}
            />
            {off ? "powered down" : connected ? "online" : "offline"}
          </span>
          <button
            onClick={togglePower}
            title={off ? "Power on AUREN" : "Shut AUREN down"}
            className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border transition ${
              off
                ? "border-jarvis-red bg-jarvis-red/10 text-jarvis-red anim-blip"
                : "border-jarvis/50 text-jarvis shadow-[0_0_14px_-4px_rgba(90,216,255,0.8)] hover:bg-jarvis/15"
            }`}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round">
              <path d="M12 3v9" />
              <path d="M6.6 6.6a9 9 0 1 0 10.8 0" />
            </svg>
          </button>
        </div>
      </header>

      {/* holographic panels — each one surfaces on its own when its data moves */}
      <HudPanel corner="tr" open={isOpen("tr")} pulseKey={pulses.tr} title="Activity" count={events.length}>
        <ActivityFeed events={events} />
      </HudPanel>

      <HudPanel corner="tl" open={isOpen("tl")} pulseKey={pulses.tl} title="Agents" count={agents.length || 9}>
        <AgentGrid agents={agents} busy={busy} />
      </HudPanel>

      <HudPanel corner="br" open={isOpen("br")} pulseKey={pulses.br} title="Visibility · Analytics">
        <GeoScore />
        <div className="border-t border-jarvis/15" />
        <Analytics stats={stats} tasks={tasks} />
      </HudPanel>

      <HudPanel corner="bl" open={isOpen("bl")} pulseKey={pulses.bl} title="Studio · Outreach · Tasks" count={tasks.length}>
        <StudioPanel />
        <div className="border-t border-jarvis/15" />
        <OutreachPanel />
        <div className="border-t border-jarvis/15" />
        <TaskQueue tasks={tasks} />
      </HudPanel>

      {/* status line under the reactor */}
      <div
        className="pointer-events-none absolute left-1/2 z-[6] flex -translate-x-1/2 flex-col items-center gap-2"
        style={{ top: UNDER_CORE }}
      >
        <span
          key={statusLine}
          className={`holo-flicker font-display text-[10px] uppercase tracking-[0.5em] ${
            off || coreState === "offline" ? "text-jarvis-red" : stalled ? "text-jarvis-amber" : "holo text-jarvis-soft"
          }`}
        >
          {statusLine}
        </span>
        {bootPhase === 0 && <span className="boot-line h-px w-44 bg-jarvis shadow-[0_0_8px_rgba(90,216,255,0.9)]" />}
        {voice.listening && voice.interim && (
          <span className="row-in max-w-sm truncate font-mono text-xs text-jarvis-amber">“{voice.interim}”</span>
        )}
      </div>

      {/* command line */}
      <div className="absolute bottom-[3.1rem] left-1/2 z-20 flex -translate-x-1/2 flex-col items-center gap-1.5">
        <CommandBar
          supported={voice.supported}
          listening={voice.listening}
          interim={voice.interim}
          onMic={() => (voice.listening ? voice.stop() : voice.listenOnce())}
          onSubmitText={submitText}
          disabled={off}
        />
        {!voice.supported && (
          <span className="font-mono text-[10px] text-jarvis/30">voice needs Chrome or Edge — typing works everywhere</span>
        )}
      </div>
    </div>
  );
}
