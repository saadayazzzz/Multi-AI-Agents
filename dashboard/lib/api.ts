export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";

export const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws";

/** URL for a rendered video row's file, served by the API's /media mounts. */
export function mediaUrl(kind: "ads" | "videos", id: number): string {
  return `${API_BASE}/media/${kind}/${id}/final.mp4`;
}

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

export type GeoQuery = {
  text: string;
  intent: string | null;
  brand_mentioned: boolean;
  brand_position: number | null;
  brand_recommended: boolean;
  sentiment: string | null;
  competitor_mentions: string[];
};

export type GeoLatest = {
  score: {
    brand: string;
    domain: string | null;
    competitors: string[];
    engine: string;
    score: number;
    presence_rate: number;
    citation_rate: number;
    reco_rate: number;
    share_of_voice: number;
    avg_position: number | null;
    detail: { per_competitor_hits: Record<string, number> };
    computed_at: string;
  };
  queries: GeoQuery[];
};

export async function getGeoLatest(): Promise<GeoLatest | null> {
  try {
    const res = await fetch(`${API_BASE}/api/geo/latest`, { cache: "no-store" });
    return res.ok ? res.json() : null;
  } catch {
    return null; // API briefly unreachable (restart etc.) — recover on next poll
  }
}

export type OutreachLead = {
  id: number;
  company: string;
  domain: string | null;
  contact_role: string | null;
  contact_email: string | null;
  email_status: string;
  icp_fit: number | null;
  geo_score: number | null;
  geo_finding: string | null;
  status: string;
};

export type OutreachLatest = {
  campaign: { id: number; name: string; icp: string; offer: string };
  counts: Record<string, number>;
  total: number;
  leads: OutreachLead[];
  sample: { company: string; subject: string; body: string } | null;
};

export async function getOutreachLatest(): Promise<OutreachLatest | null> {
  try {
    const res = await fetch(`${API_BASE}/api/outreach/latest`, { cache: "no-store" });
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}

export type StudioVideo = {
  id: number;
  theme: string;
  title: string | null;
  clip_count: number | null;
  seconds: number | null;
  privacy: string;
  status: "draft" | "rendered" | "uploaded" | "failed";
  youtube_url: string | null;
  created_at: string;
};

export async function getStudioRecent(): Promise<StudioVideo[]> {
  try {
    const res = await fetch(`${API_BASE}/api/studio/recent`, { cache: "no-store" });
    return res.ok ? res.json() : [];
  } catch {
    return [];
  }
}

export type AdVideo = {
  id: number;
  niche: string;
  product: string | null;
  hook: string | null;
  seconds: number | null;
  privacy: string;
  status: "queued" | "scripted" | "rendered" | "uploaded" | "failed";
  youtube_url: string | null;
  created_at: string;
};

export async function getAdsRecent(): Promise<AdVideo[]> {
  try {
    const res = await fetch(`${API_BASE}/api/ads/recent`, { cache: "no-store" });
    return res.ok ? res.json() : [];
  } catch {
    return [];
  }
}

export async function approveContent(id: number): Promise<ContentPiece> {
  const res = await fetch(`${API_BASE}/api/content/${id}/approve`, { method: "POST" });
  if (!res.ok) throw new Error(`approveContent failed: ${res.status}`);
  return res.json();
}
