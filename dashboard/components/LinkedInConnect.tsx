"use client";

import { useEffect, useState } from "react";
import {
  disconnectLinkedIn,
  getLinkedInStatus,
  linkedinLoginUrl,
  type LinkedInStatus,
} from "@/lib/api";

/**
 * Official LinkedIn OAuth connect — no scraping, no automated connection
 * requests or DMs (see agents/platforms/linkedin.py). Just links the real
 * profile so posts go out as the operator and outreach drafts can be signed
 * with their real name.
 */
export function LinkedInConnect() {
  const [status, setStatus] = useState<LinkedInStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => getLinkedInStatus().then(setStatus).catch(() => {});

  useEffect(() => {
    refresh();

    // returning from LinkedIn's consent screen lands back here with a marker
    const params = new URLSearchParams(window.location.search);
    const result = params.get("linkedin");
    if (result) {
      params.delete("linkedin");
      const rest = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (rest ? `?${rest}` : ""));
      refresh();
    }
  }, []);

  if (!status) return null;

  if (!status.configured) {
    return (
      <div className="px-3 py-2 font-mono text-[9px] text-jarvis/35">
        LinkedIn app not configured — add LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET
        (see .env.example)
      </div>
    );
  }

  if (status.connected) {
    return (
      <div className="flex items-center justify-between gap-2 border border-jarvis/15 bg-black/25 px-3 py-2">
        <div className="min-w-0">
          <div className="label">LinkedIn connected</div>
          <div className="truncate font-mono text-[10px] text-jarvis-soft">
            {status.name ?? status.email ?? "connected"}
          </div>
        </div>
        <button
          onClick={async () => {
            setBusy(true);
            await disconnectLinkedIn().finally(() => setBusy(false));
            refresh();
          }}
          disabled={busy}
          className="shrink-0 rounded border border-jarvis-red/30 px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-jarvis-red/80 transition hover:bg-jarvis-red/10 disabled:opacity-40"
        >
          disconnect
        </button>
      </div>
    );
  }

  return (
    <a
      href={linkedinLoginUrl()}
      className="flex items-center justify-between gap-2 border border-jarvis/15 bg-black/25 px-3 py-2 transition hover:border-jarvis/40"
    >
      <div>
        <div className="label">LinkedIn</div>
        <div className="font-mono text-[10px] text-jarvis/50">not connected</div>
      </div>
      <span className="shrink-0 rounded border border-jarvis/40 px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-jarvis/80">
        connect
      </span>
    </a>
  );
}
