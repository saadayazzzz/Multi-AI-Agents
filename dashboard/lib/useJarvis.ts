"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  WS_URL,
  type AgentState,
  type TrendItem,
  type Stats,
  type Task,
  type TaskEvent,
} from "./api";

const MAX_EVENTS = 400;
const MAX_TRENDS = 60;

export type JarvisFeed = {
  connected: boolean;
  stats: Stats | null;
  agents: AgentState[];
  tasks: Task[];
  events: TaskEvent[];
  trends: TrendItem[];
  /** newest orchestrator/system line meant to be spoken, or null */
  latestSpoken: { id: number; text: string } | null;
};

export function useJarvis(): JarvisFeed {
  const [connected, setConnected] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [agents, setAgents] = useState<AgentState[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [trends, setTrends] = useState<TrendItem[]>([]);
  const [latestSpoken, setLatestSpoken] = useState<{ id: number; text: string } | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const deadRef = useRef(false); // set on unmount so a pending reconnect is cancelled
  const seenRef = useRef<Set<number>>(new Set());
  const trendSeenRef = useRef<Set<number>>(new Set());

  const connect = useCallback(() => {
    if (deadRef.current) return;
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      retryRef.current = 0;
    };
    ws.onclose = () => {
      setConnected(false);
      if (deadRef.current) return;
      const delay = Math.min(1000 * 2 ** retryRef.current, 15000);
      retryRef.current += 1;
      setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "snapshot") {
        if (msg.stats) setStats(msg.stats);
        if (msg.agents) setAgents(msg.agents);
        if (msg.tasks) setTasks(msg.tasks);
        if (msg.trends) {
          const m: TrendItem[] = msg.trends;
          m.forEach((x) => trendSeenRef.current.add(x.id));
          setTrends(m.slice(-MAX_TRENDS));
        }
        return;
      }
      if (msg.type === "trends") {
        const fresh: TrendItem[] = (msg.items as TrendItem[]).filter(
          (x) => !trendSeenRef.current.has(x.id),
        );
        if (!fresh.length) return;
        fresh.forEach((x) => trendSeenRef.current.add(x.id));
        setTrends((prev) => [...prev, ...fresh].slice(-MAX_TRENDS));
        return;
      }
      if (msg.type !== "events") return;

      const fresh: TaskEvent[] = (msg.events as TaskEvent[]).filter(
        (e) => !seenRef.current.has(e.id),
      );
      if (!fresh.length) return;
      fresh.forEach((e) => seenRef.current.add(e.id));

      setEvents((prev) => {
        const next = [...prev, ...fresh].slice(-MAX_EVENTS);
        seenRef.current = new Set(next.map((e) => e.id));
        return next;
      });

      for (const e of fresh) {
        // Only the final "spoken" event (emitted once per task, on completion)
        // should be read aloud - "message" events fire on every tool-loop step
        // and would otherwise cause the same reply to be spoken 2-3x.
        if (e.kind === "spoken" && e.actor === "system" && e.message) {
          setLatestSpoken({ id: e.id, text: e.message });
        }
      }
    };
  }, []);

  useEffect(() => {
    deadRef.current = false;
    connect();
    return () => {
      deadRef.current = true;
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, stats, agents, tasks, events, trends, latestSpoken };
}
