"use client";

import { useEffect, useRef, useState } from "react";
import type { MarketItem, Task, TaskEvent } from "@/lib/api";
import { coreRadiusPx } from "./HoloCore";
import { PANEL_INNER_EDGE } from "./HudPanel";
import { sfx } from "@/lib/sfx";

type Tone = "info" | "ok" | "warn" | "error";

type Toast = {
  key: string;
  slot: number;
  title: string;
  body: string;
  meta: string;
  tone: Tone;
  ambient: boolean;
  born: number;
  leftAt: number | null;
};

type Pending = Omit<Toast, "slot" | "born" | "leftAt">;

// lower slots sit wider than the upper ones to stay clear of the status line under the core
const SLOT_ANGLES = [-128, -52, 42, 138];
const HOLD_MS = 6500;
const RECENT_MS = 60000;
const MAX_QUEUE = 6;
const AMBIENT_EVERY_MS = 5200;
const CARD_W = 214;

const TONE: Record<Tone, string> = {
  info: "#5ad8ff",
  ok: "#4dffa6",
  warn: "#ffab40",
  error: "#ff4d5e",
};

const ACTOR: Record<string, string> = {
  orchestrator: "AUREN",
  system: "SYSTEM",
  user: "YOU",
  agent1: "DISCOVERY",
  agent2: "SCRAPER",
  agent3: "BRAND BUILDER",
  agent4: "IMAGERY",
  agent5: "MARKET PULSE",
  geo: "AI VISIBILITY",
  sales: "OUTREACH",
  studio: "STUDIO",
};

const TOASTABLE = new Set(["message", "spoken", "error"]);

function clip(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

/** Holographic pop-ups that fly out of the core whenever the system does something. */
export function HoloToasts({
  events,
  market,
  tasks,
  enabled,
  sound,
}: {
  events: TaskEvent[];
  market: MarketItem[];
  tasks: Task[];
  enabled: boolean;
  sound: boolean;
}) {
  const [view, setView] = useState({ w: 0, h: 0 });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastsRef = useRef<Toast[]>([]);
  const queue = useRef<Pending[]>([]);
  const lastEventId = useRef(0);
  const taskStatus = useRef(new Map<number, string>());
  const lastReal = useRef(0);
  const lastAmbient = useRef(0);
  const ambientIdx = useRef(0);
  const soundRef = useRef(sound);
  soundRef.current = sound;

  useEffect(() => {
    const on = () => setView({ w: window.innerWidth, h: window.innerHeight });
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  // ---- real events → queue (history replayed on connect stays in the Activity panel) ----
  useEffect(() => {
    const fresh = events.filter((e) => e.id > lastEventId.current);
    if (!fresh.length) return;
    lastEventId.current = fresh[fresh.length - 1].id;
    const cutoff = Date.now() - RECENT_MS;
    for (const e of fresh) {
      if (!TOASTABLE.has(e.kind) || !e.message || new Date(e.ts).getTime() < cutoff) continue;
      queue.current.push({
        key: `e${e.id}`,
        title: ACTOR[e.actor] ?? e.actor.toUpperCase(),
        body: clip(e.message, 150),
        meta: new Date(e.ts).toLocaleTimeString([], { hour12: false }),
        tone: e.kind === "error" ? "error" : e.kind === "spoken" ? "warn" : "info",
        ambient: false,
      });
    }
    queue.current = queue.current.slice(-MAX_QUEUE);
  }, [events]);

  // ---- task lifecycle → queue ----
  useEffect(() => {
    const prev = taskStatus.current;
    const cutoff = Date.now() - RECENT_MS;
    for (const t of tasks) {
      const was = prev.get(t.id);
      if (was === t.status) continue;
      // a task we've never seen is only news if it was just created
      if (was === undefined && new Date(t.created_at).getTime() < cutoff) continue;
      const label =
        t.status === "running"
          ? "TASK ENGAGED"
          : t.status === "done"
            ? "TASK COMPLETE"
            : t.status === "failed"
              ? "TASK FAILED"
              : t.status === "queued"
                ? "TASK QUEUED"
                : null;
      if (!label) continue;
      queue.current.push({
        key: `t${t.id}-${t.status}`,
        title: `${label} · #${t.id}`,
        body: clip(t.result_summary || t.error || t.prompt, 150),
        meta: t.source,
        tone: t.status === "done" ? "ok" : t.status === "failed" ? "error" : "info",
        ambient: false,
      });
    }
    taskStatus.current = new Map(tasks.map((t) => [t.id, t.status]));
    queue.current = queue.current.slice(-MAX_QUEUE);
  }, [tasks]);

  // ---- one clock: expire, place queued events in free slots, fill quiet time with market intel ----
  const marketRef = useRef(market);
  marketRef.current = market;
  useEffect(() => {
    const commit = (next: Toast[]) => {
      toastsRef.current = next;
      setToasts(next);
    };
    if (!enabled) {
      queue.current = [];
      commit([]);
      return;
    }
    const iv = setInterval(() => {
      const now = Date.now();
      let changed = false;

      let out = toastsRef.current
        .filter((t) => {
          const keep = !(t.leftAt && now - t.leftAt > 420);
          if (!keep) changed = true;
          return keep;
        })
        .map((t) => {
          if (!t.leftAt && now - t.born > (t.ambient ? HOLD_MS - 1500 : HOLD_MS)) {
            changed = true;
            return { ...t, leftAt: now };
          }
          return t;
        });

      const used = new Set(out.filter((t) => !t.leftAt).map((t) => t.slot));
      const free = [0, 1, 2, 3].filter((s) => !used.has(s));

      while (queue.current.length && free.length) {
        const next = queue.current.shift()!;
        out.push({ ...next, slot: free.shift()!, born: now, leftAt: null });
        lastReal.current = now;
        changed = true;
        sfx(next.tone === "error" ? "alert" : "blip", soundRef.current);
      }
      // a waiting real event bumps an ambient card out of its slot
      if (queue.current.length) {
        const amb = out.find((t) => t.ambient && !t.leftAt);
        if (amb) {
          out = out.map((t) => (t === amb ? { ...t, leftAt: now } : t));
          changed = true;
        }
      }

      const mk = marketRef.current;
      const quiet = now - lastReal.current > 4000;
      const ambientOn = out.filter((t) => t.ambient && !t.leftAt).length;
      if (quiet && free.length && ambientOn < 2 && mk.length && now - lastAmbient.current > AMBIENT_EVERY_MS) {
        const it = mk[mk.length - 1 - (ambientIdx.current++ % mk.length)];
        if (!out.some((t) => t.key === `m${it.id}`)) {
          lastAmbient.current = now;
          out.push({
            key: `m${it.id}`,
            slot: free[Math.floor(Math.random() * free.length)],
            title: `${(it.tag ?? "market").toUpperCase()} · ${(it.region ?? "global").toUpperCase()}`,
            body: clip(it.headline, 110),
            meta: it.source ?? "",
            tone: it.sentiment === "negative" ? "error" : it.sentiment === "positive" ? "ok" : "info",
            ambient: true,
            born: now,
            leftAt: null,
          });
          changed = true;
        }
      }

      if (changed) commit(out);
    }, 250);
    return () => clearInterval(iv);
  }, [enabled]);

  const { w, h } = view;
  if (!w || !toasts.length) return null;

  const cx = w / 2;
  const cy = h / 2;
  const r = coreRadiusPx(w, h);
  const panelEdge = PANEL_INNER_EDGE + 10;

  const geo = (slot: number) => {
    const a = (SLOT_ANGLES[slot] * Math.PI) / 180;
    const left = Math.cos(a) < 0;
    const sx = cx + Math.cos(a) * r * 1.02;
    const sy = cy + Math.sin(a) * r * 1.02;
    let kx = cx + Math.cos(a) * r * 1.3;
    const ky = cy + Math.sin(a) * r * 1.22;
    // keep cards clear of the side panels
    if (left) kx = Math.max(kx, panelEdge + CARD_W);
    else kx = Math.min(kx, w - panelEdge - CARD_W);
    return { sx, sy, kx, ky, left };
  };

  return (
    <div className="pointer-events-none absolute inset-0 z-[12]">
      <svg width={w} height={h} className="absolute inset-0" style={{ filter: "drop-shadow(0 0 2.5px rgba(90,216,255,0.85))" }}>
        {toasts.map((t) => {
          const g = geo(t.slot);
          const c = TONE[t.tone];
          const len = Math.hypot(g.kx - g.sx, g.ky - g.sy);
          return (
            <g key={t.key} style={{ opacity: t.leftAt ? 0 : 1, transition: "opacity 0.35s" }}>
              <line
                x1={g.sx}
                y1={g.sy}
                x2={g.kx}
                y2={g.ky}
                stroke={c}
                strokeOpacity="0.75"
                strokeWidth="1.2"
                style={{ strokeDasharray: len, strokeDashoffset: len, animation: "draw 0.35s ease forwards" }}
              />
              <circle cx={g.sx} cy={g.sy} r="2.6" fill={c} />
              <circle cx={g.kx} cy={g.ky} r="3" fill="#e8fbff" />
            </g>
          );
        })}
      </svg>

      {toasts.map((t) => {
        const g = geo(t.slot);
        const c = TONE[t.tone];
        const x = g.left ? g.kx - CARD_W : g.kx;
        return (
          <div
            key={t.key}
            className={`absolute ${t.leftAt ? "toast-out" : "toast-in"}`}
            style={
              {
                left: x,
                top: g.ky,
                width: CARD_W,
                translate: "0 -50%",
                "--tx": `${cx - (x + CARD_W / 2)}px`,
                "--ty": `${cy - g.ky}px`,
              } as React.CSSProperties
            }
          >
            <div
              className="relative overflow-hidden px-3 py-2 backdrop-blur-md"
              style={{
                background: `linear-gradient(135deg, ${c}22, rgba(3,10,20,0.78) 55%)`,
                boxShadow: `inset 0 0 0 1px ${c}55, 0 0 34px -12px ${c}`,
                clipPath: "polygon(0 8px, 8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%)",
              }}
            >
              <span
                className="absolute inset-y-0 w-[2px]"
                style={{ [g.left ? "right" : "left"]: 0, background: c, boxShadow: `0 0 8px ${c}` } as React.CSSProperties}
              />
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-[7.5px] uppercase tracking-[0.22em]" style={{ color: c }}>
                  {t.title}
                </span>
                <span className="shrink-0 font-mono text-[9px] text-jarvis/40">{t.meta}</span>
              </div>
              <div className="mt-1 text-[13px] font-medium leading-[1.2] text-jarvis-soft">{t.body}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
