"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL, type AgentState, type Stats, type Task, type TaskEvent } from "./api";

const MAX_EVENTS = 400;

export type JarvisFeed = {
  connected: boolean;
  stats: Stats | null;
  agents: AgentState[];
  tasks: Task[];
  events: TaskEvent[];
  /** newest orchestrator/system line meant to be spoken, or null */
  latestSpoken: { id: number; text: string } | null;
};

export function useJarvis(): JarvisFeed {
  const [connected, setConnected] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [agents, setAgents] = useState<AgentState[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [latestSpoken, setLatestSpoken] = useState<{ id: number; text: string } | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const deadRef = useRef(false); // set on unmount so a pending reconnect is cancelled
  const seenRef = useRef<Set<number>>(new Set());

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
        if (
          (e.kind === "message" || e.kind === "spoken") &&
          (e.actor === "orchestrator" || e.actor === "system") &&
          e.message
        ) {
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

  return { connected, stats, agents, tasks, events, latestSpoken };
}
