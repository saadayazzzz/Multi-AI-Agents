"use client";

import { useEffect, useState } from "react";

export type PlayingVideo = { url: string; title: string; subtitle?: string };

/**
 * Full-screen holographic viewer: a beam fires from the core to a bordered
 * frame that unfolds and plays the video. Visual language matches HudPanel/
 * TetherLines (scan-line sweep, corner brackets, holo glow).
 */
export function VideoViewer({
  video,
  onClose,
}: {
  video: PlayingVideo | null;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [dims, setDims] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const on = () => setDims({ w: window.innerWidth, h: window.innerHeight });
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  useEffect(() => {
    if (video) {
      setMounted(true);
      const t = setTimeout(() => setOpen(true), 20);
      return () => clearTimeout(t);
    }
    setOpen(false);
    const t = setTimeout(() => setMounted(false), 420);
    return () => clearTimeout(t);
  }, [video]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mounted, onClose]);

  if (!mounted || !video) return null;

  const { w, h } = dims;
  const cx = w / 2;
  const cy = h / 2;
  const frameH = Math.min(h * 0.82, 800);
  const frameW = frameH * (9 / 16);
  const targetY = cy - frameH / 2;

  return (
    <div className="pointer-events-auto fixed inset-0 z-40">
      <div
        className="absolute inset-0 bg-black transition-opacity duration-300"
        style={{ opacity: open ? 0.78 : 0 }}
        onClick={onClose}
      />

      {w > 0 && (
        <svg width={w} height={h} className="pointer-events-none absolute inset-0">
          <defs>
            <linearGradient id="beam-viewer" gradientUnits="userSpaceOnUse" x1={cx} y1={cy} x2={cx} y2={targetY}>
              <stop offset="0" stopColor="#7cf5ea" stopOpacity="0.9" />
              <stop offset="1" stopColor="#38e0d0" stopOpacity="0.15" />
            </linearGradient>
          </defs>
          <line
            x1={cx}
            y1={cy}
            x2={cx}
            y2={targetY}
            stroke="url(#beam-viewer)"
            strokeWidth={1.8}
            strokeLinecap="round"
            style={{
              filter: "drop-shadow(0 0 6px rgba(56,224,208,0.55))",
              strokeDasharray: Math.abs(cy - targetY),
              strokeDashoffset: open ? 0 : Math.abs(cy - targetY),
              transition: "stroke-dashoffset 0.3s ease",
              opacity: open ? 1 : 0,
            }}
          />
          <circle cx={cx} cy={cy} r={2.5} fill="#7cf5ea" style={{ opacity: open ? 0.9 : 0, transition: "opacity 0.2s" }} />
        </svg>
      )}

      <div
        className="absolute left-1/2 top-1/2"
        style={{
          width: frameW || 320,
          height: frameH || 560,
          transform: open
            ? "translate(-50%, -50%) scale(1)"
            : "translate(-50%, -50%) scale(0.08)",
          opacity: open ? 1 : 0,
          transition: "transform 0.42s cubic-bezier(0.16,1,0.3,1) 0.22s, opacity 0.25s ease 0.22s",
        }}
      >
        <div className="hud-panel pointer-events-auto flex h-full flex-col overflow-hidden">
          <span className="hud-corner tl" />
          <span className="hud-corner tr" />
          <span className="hud-corner bl" />
          <span className="hud-corner br" />
          {open && <span className="scan-line" />}

          <div className="flex h-9 shrink-0 items-center justify-between border-b border-jarvis/20 px-3">
            <div className="min-w-0">
              <div className="truncate label holo">{video.title}</div>
              {video.subtitle && (
                <div className="truncate font-mono text-[9px] text-jarvis/40">{video.subtitle}</div>
              )}
            </div>
            <button
              onClick={onClose}
              className="ml-2 shrink-0 rounded border border-jarvis/30 px-1.5 py-0.5 font-mono text-[10px] text-jarvis/70 hover:bg-jarvis/10"
            >
              ✕
            </button>
          </div>
          <div className="min-h-0 flex-1 bg-black">
            {/* key forces a fresh <video> per URL so switching clips doesn't show a stale frame */}
            <video
              key={video.url}
              src={video.url}
              controls
              autoPlay
              className="h-full w-full object-contain"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
