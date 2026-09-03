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

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      retryRef.current = 0;
    };
    ws.onclose = () => {
      setConnected(false);
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
      } else if (msg.type === "events") {
        const incoming: TaskEvent[] = msg.events;
        setEvents((prev) => [...prev, ...incoming].slice(-MAX_EVENTS));
        for (const e of incoming) {
          if (
            (e.kind === "message" || e.kind === "spoken") &&
            (e.actor === "orchestrator" || e.actor === "system") &&
            e.message
          ) {
            setLatestSpoken({ id: e.id, text: e.message });
          }
        }
      }
    };
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  return { connected, stats, agents, tasks, events, latestSpoken };
}
