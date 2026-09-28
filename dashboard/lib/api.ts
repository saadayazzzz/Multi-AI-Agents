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
  market_total: number;
  leads_by_status: Record<string, number>;
  leads_total: number;
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

/** One row from Agent 1's (Market Pulse) AI-search/GEO industry feed. */
export type MarketItem = {
  id: number;
  ts: string;
  headline: string;
  detail: string | null;
  tag: string | null;
  sentiment: "positive" | "neutral" | "negative" | null;
  region: string | null;
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
  contact_name: string | null;
  contact_role: string | null;
  contact_email: string | null;
  email_status: string;
  /** the real linkedin.com URL behind this lead's why-now signal, if any */
  linkedin_url: string | null;
  /** when they were active, as the search result showed it (e.g. "3 days ago") */
  linkedin_activity: string | null;
  trigger: string | null;
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

export type LinkedInStatus =
  | { connected: false; configured: boolean }
  | {
      connected: true;
      configured: true;
      name: string | null;
      email: string | null;
      expires_at: string | null;
      connected_at: string;
    };

export async function getLinkedInStatus(): Promise<LinkedInStatus> {
  try {
    const res = await fetch(`${API_BASE}/api/linkedin/status`, { cache: "no-store" });
    return res.ok ? res.json() : { connected: false, configured: false };
  } catch {
    return { connected: false, configured: false };
  }
}

/** Full-page redirect into LinkedIn's own consent screen — never a fetch. */
export function linkedinLoginUrl(): string {
  return `${API_BASE}/api/linkedin/login`;
}

export async function disconnectLinkedIn(): Promise<void> {
  await fetch(`${API_BASE}/api/linkedin/disconnect`, { method: "POST" });
}
