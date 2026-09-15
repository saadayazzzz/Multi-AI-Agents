"use client";

import { useEffect, useState } from "react";
import { getAdsRecent, mediaUrl, type AdVideo } from "@/lib/api";
import type { PlayingVideo } from "./VideoViewer";

const PLAYABLE = new Set(["rendered", "uploaded"]);

const ST: Record<string, string> = {
  queued: "text-jarvis/45",
  scripted: "text-jarvis/45",
  rendered: "text-jarvis",
  uploaded: "text-jarvis-ok",
  failed: "text-jarvis-red",
};

export function AdsPanel({ onPlay }: { onPlay: (v: PlayingVideo) => void }) {
  const [rows, setRows] = useState<AdVideo[]>([]);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getAdsRecent()
        .then((r) => alive && setRows(r))
        .catch(() => {});
    load();
    const iv = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  return (
    <div className="p-3">
      <div className="label">Ad Studio</div>
      {rows.length === 0 ? (
        <div className="mt-2 font-mono text-[10px] text-jarvis/35">
          no ads yet — ask JARVIS to “make a UGC ad for skincare”
        </div>
      ) : (
        <div className="mt-2 space-y-1.5 font-mono text-[9px]">
          {rows.map((a) => {
            const playable = PLAYABLE.has(a.status);
            return (
            <div
              key={a.id}
              onClick={() =>
                playable &&
                onPlay({
                  url: mediaUrl("ads", a.id),
                  title: a.hook ?? a.niche,
                  subtitle: [a.niche, a.product].filter(Boolean).join(" · "),
                })
              }
              className={`border border-jarvis/15 bg-black/25 px-2 py-1.5 ${
                playable ? "cursor-pointer hover:border-jarvis/40 hover:bg-jarvis/[0.06]" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className={`uppercase ${ST[a.status]}`}>{a.status}</span>
                <span className="text-jarvis/35">
                  {a.privacy} · {a.seconds ?? "?"}s
                </span>
              </div>
              <div className="mt-0.5 truncate text-jarvis-soft">
                {a.hook ?? [a.niche, a.product].filter(Boolean).join(" · ")}
              </div>
              {a.youtube_url && (
                <a
                  href={a.youtube_url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="pointer-events-auto text-jarvis-ok underline"
                >
                  {a.youtube_url}
                </a>
              )}
            </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
