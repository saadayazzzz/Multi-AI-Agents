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
  sites: Record<string, number>;
  sites_total: number;
  products: number;
  brands: number;
  tasks_pending: number;
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

export type Brand = {
  slug: string;
  spec: Record<string, any>;
  output_path: string | null;
  created_at: string;
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

export async function getBrands(): Promise<Brand[]> {
  const res = await fetch(`${API_BASE}/api/brands`, { cache: "no-store" });
  return res.ok ? res.json() : [];
}
