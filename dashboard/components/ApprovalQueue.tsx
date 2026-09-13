"use client";

import { useState } from "react";
import { approveContent, type ContentPiece } from "@/lib/api";

export function ApprovalQueue({
  items,
  onApproved,
  onOpen,
}: {
  items: ContentPiece[];
  onApproved: () => void;
  onOpen: (c: ContentPiece) => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState<Record<number, string>>({});

  const approve = async (id: number) => {
    setBusy(id);
    setErr((e) => ({ ...e, [id]: "" }));
    try {
      const r = await approveContent(id);
      if (r.status === "failed" && r.error) {
        setErr((e) => ({ ...e, [id]: r.error as string }));
      }
      onApproved();
    } catch {
      setErr((e) => ({ ...e, [id]: "could not reach the control plane" }));
    } finally {
      setBusy(null);
    }
  };

  if (items.length === 0) return null;

  return (
    <div className="space-y-2 border-b border-jarvis/15 p-2.5">
      <div className="label text-jarvis-amber">Awaiting your approval</div>
      {items.map((c) => (
        <div key={c.id} className="row-in border border-jarvis-amber/30 bg-black/30 p-2.5">
          <button
            onClick={() => onOpen(c)}
            className="block w-full text-left"
            title="Click to review the full post before approving"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="chip border-jarvis-amber/50 text-jarvis-amber uppercase">
                {c.platform}
              </span>
              <span className="font-mono text-[9px] text-jarvis/35">#{c.id}</span>
            </div>
            <div className="mt-1.5 text-[12px] font-medium leading-snug text-jarvis-soft">
              {c.title ?? "(untitled)"}
            </div>
            {(c.caption || c.script) && (
              <div className="mt-1 line-clamp-2 text-[10.5px] leading-snug text-jarvis/55">
                {c.caption || c.script}
              </div>
            )}
          </button>
          {err[c.id] && (
            <div className="mt-1 border-l-2 border-jarvis-red/40 pl-2 text-[10.5px] text-jarvis-red">
              {err[c.id]}
            </div>
          )}
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => onOpen(c)}
              className="rounded border border-jarvis/30 px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.2em] text-jarvis/60 hover:bg-jarvis/10"
            >
              review
            </button>
            <button
              onClick={() => approve(c.id)}
              disabled={busy === c.id}
              className="rounded border border-jarvis-amber/50 px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.2em] text-jarvis-amber transition hover:bg-jarvis-amber/10 disabled:opacity-40"
            >
              {busy === c.id ? "posting…" : "approve & post"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
