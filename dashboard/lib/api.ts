export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";

export const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws";

export type AgentState = {
  actor: string;
  state: "idle" | "working";
  last_message: string | null;
  last_kind: string | null;
  last_ts: string | null;
};

export type Stats = {
  trends: Record<string, number>;
  trends_total: number;
  content_by_status: Record<string, number>;
  content_total: number;
  posted_by_platform: Record<string, number>;
  tasks_pending: number;
  power?: "on" | "off";
};

export type Task = {
  id: number;
  prompt: string;
  source: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  recur_seconds: number | null;
  result_summary: string | null;
  spoken_response: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type TaskEvent = {
  id: number;
  task_id: number | null;
  actor: string;
  kind: string;
  message: string | null;
  data: Record<string, unknown>;
  ts: string;
};

export type ContentPiece = {
  id: number;
  platform: string;
  title: string | null;
  script: string | null;
  caption: string | null;
  cta: string | null;
  hashtags: string[] | null;
  status: "draft" | "ready" | "ready_manual_upload" | "posted" | "failed";
  external_url: string | null;
  error: string | null;
  created_at: string;
  posted_at: string | null;
  image_rel_path: string | null;
};

export type TrendItem = {
  id: number;
  ts: string;
  platform: string;
  topic: string;
  angle: string | null;
  format: string | null;
  score: number | null;
  source: string | null;
};

export async function createTask(prompt: string, source = "voice"): Promise<Task> {
  const res = await fetch(`${API_BASE}/api/tasks`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prompt, source }),
  });
  if (!res.ok) throw new Error(`createTask failed: ${res.status}`);
  return res.json();
}

export async function cancelTask(id: number): Promise<void> {
  await fetch(`${API_BASE}/api/tasks/${id}/cancel`, { method: "POST" });
}

export async function setPower(state: "on" | "off"): Promise<void> {
  await fetch(`${API_BASE}/api/power`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ state }),
  });
}

export async function getContent(): Promise<ContentPiece[]> {
  const res = await fetch(`${API_BASE}/api/content`, { cache: "no-store" });
  return res.ok ? res.json() : [];
}

export async function approveContent(id: number): Promise<ContentPiece> {
  const res = await fetch(`${API_BASE}/api/content/${id}/approve`, { method: "POST" });
  if (!res.ok) throw new Error(`approveContent failed: ${res.status}`);
  return res.json();
}
