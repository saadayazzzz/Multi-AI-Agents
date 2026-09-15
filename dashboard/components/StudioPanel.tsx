"use client";

import { useEffect, useState } from "react";
import { getStudioRecent, mediaUrl, type StudioVideo } from "@/lib/api";
import type { PlayingVideo } from "./VideoViewer";

const PLAYABLE = new Set(["rendered", "uploaded"]);

const ST: Record<string, string> = {
  draft: "text-jarvis/45",
  rendered: "text-jarvis",
  uploaded: "text-jarvis-ok",
  failed: "text-jarvis-red",
};

export function StudioPanel({ onPlay }: { onPlay: (v: PlayingVideo) => void }) {
  const [rows, setRows] = useState<StudioVideo[]>([]);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getStudioRecent()
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
      <div className="label">Video Studio</div>
      {rows.length === 0 ? (
        <div className="mt-2 font-mono text-[10px] text-jarvis/35">
          no videos yet — ask JARVIS to “make a soap-cutting ASMR video”
        </div>
      ) : (
        <div className="mt-2 space-y-1.5 font-mono text-[9px]">
          {rows.map((v) => {
            const playable = PLAYABLE.has(v.status);
            return (
              <div
                key={v.id}
                onClick={() =>
                  playable &&
                  onPlay({
                    url: mediaUrl("videos", v.id),
                    title: v.title ?? v.theme,
                    subtitle: v.theme,
                  })
                }
                className={`border border-jarvis/15 bg-black/25 px-2 py-1.5 ${
                  playable ? "cursor-pointer hover:border-jarvis/40 hover:bg-jarvis/[0.06]" : ""
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={`uppercase ${ST[v.status]}`}>{v.status}</span>
                  <span className="text-jarvis/35">
                    {v.privacy} · {v.clip_count ?? "?"}×{v.seconds ?? "?"}s
                  </span>
                </div>
                <div className="mt-0.5 truncate text-jarvis-soft">
                  {v.title ?? v.theme}
                </div>
                {v.youtube_url && (
                  <a
                    href={v.youtube_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="pointer-events-auto text-jarvis-ok underline"
                  >
                    {v.youtube_url}
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
