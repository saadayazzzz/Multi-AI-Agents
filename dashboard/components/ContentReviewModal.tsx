"use client";

import { useState } from "react";
import { API_BASE, approveContent, type ContentPiece } from "@/lib/api";

const STATUS_LABEL: Record<ContentPiece["status"], string> = {
  draft: "draft",
  ready: "ready to post",
  ready_manual_upload: "ready — needs manual video upload",
  posted: "posted",
  failed: "failed",
};

export function ContentReviewModal({
  content,
  onClose,
  onApproved,
}: {
  content: ContentPiece | null;
  onClose: () => void;
  onApproved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (!content) return null;
  const body = content.script || content.caption || "(no text)";
  const imgUrl = content.image_rel_path ? `${API_BASE}${content.image_rel_path}` : null;

  const approve = async () => {
    setBusy(true);
    setErr("");
    try {
      const r = await approveContent(content.id);
      if (r.status === "failed" && r.error) setErr(r.error);
      else onClose();
      onApproved();
    } catch {
      setErr("could not reach the control plane");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="pointer-events-auto fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="hud-panel relative max-h-[85vh] w-[min(92vw,640px)] overflow-y-auto p-5"
        style={{ boxShadow: "0 0 80px -18px rgba(56,224,208,0.55)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <span className="hud-corner tl" />
        <span className="hud-corner tr" />
        <span className="hud-corner bl" />
        <span className="hud-corner br" />

        <button
          onClick={onClose}
          className="absolute right-4 top-4 font-mono text-[11px] uppercase tracking-[0.2em] text-jarvis/50 hover:text-jarvis"
        >
          close ✕
        </button>

        <div className="flex items-center gap-2">
          <span className="chip border-jarvis-amber/50 text-jarvis-amber uppercase">
            {content.platform}
          </span>
          <span className="font-mono text-[10px] text-jarvis/40">
            #{content.id} · {STATUS_LABEL[content.status]}
          </span>
        </div>

        <div className="mt-3 text-[16px] font-semibold leading-snug text-jarvis-soft">
          {content.title ?? "(untitled)"}
        </div>

        {imgUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imgUrl}
            alt="generated thumbnail"
            className="mt-3 max-h-72 w-full rounded border border-jarvis/15 object-cover"
          />
        )}

        <div className="mt-3 whitespace-pre-wrap text-[13px] leading-relaxed text-jarvis/80">
          {body}
        </div>

        {content.cta && (
          <div className="mt-3 border-l-2 border-jarvis-amber/40 pl-2 text-[12px] text-jarvis-amber">
            CTA: {content.cta}
          </div>
        )}

        {content.hashtags && content.hashtags.length > 0 && (
          <div className="mt-2 font-mono text-[11px] text-jarvis/45">
            {content.hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`)).join("  ")}
          </div>
        )}

        {content.external_url && (
          <a
            href={content.external_url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 block break-all font-mono text-[11px] text-jarvis underline"
          >
            {content.external_url}
          </a>
        )}

        {(content.error || err) && (
          <div className="mt-3 border-l-2 border-jarvis-red/40 pl-2 text-[11px] text-jarvis-red">
            {err || content.error}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded border border-jarvis/30 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-jarvis/60 hover:bg-jarvis/10"
          >
            close
          </button>
          {content.status === "ready" && (
            <button
              onClick={approve}
              disabled={busy}
              className="rounded border border-jarvis-amber/50 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-jarvis-amber transition hover:bg-jarvis-amber/10 disabled:opacity-40"
            >
              {busy ? "posting…" : "approve & post"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
