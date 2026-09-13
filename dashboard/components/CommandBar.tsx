"use client";

import { useState } from "react";

export function CommandBar({
  supported,
  listening,
  interim,
  onMic,
  onSubmitText,
  disabled = false,
}: {
  supported: boolean;
  listening: boolean;
  interim: string;
  onMic: () => void;
  onSubmitText: (text: string) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");

  const send = () => {
    if (disabled) return;
    const t = text.trim();
    if (!t) return;
    onSubmitText(t);
    setText("");
  };

  return (
    <div
      className="hud-panel pointer-events-auto flex w-[min(92vw,640px)] items-center gap-3 px-3 py-2.5"
      style={{ boxShadow: "0 0 60px -18px rgba(56,224,208,0.55)" }}
    >
      <span className="hud-corner tl" />
      <span className="hud-corner tr" />
      <span className="hud-corner bl" />
      <span className="hud-corner br" />

      <button
        onClick={onMic}
        disabled={!supported || disabled}
        title={supported ? "Click, then speak" : "Voice unsupported in this browser"}
        className={`grid h-11 w-11 shrink-0 place-items-center rounded-full border transition ${
          listening
            ? "border-jarvis-amber bg-jarvis-amber/15 text-jarvis-amber anim-blip"
            : "border-jarvis/60 bg-jarvis/10 text-jarvis hover:bg-jarvis/20"
        } disabled:cursor-not-allowed disabled:opacity-30`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v4" />
        </svg>
      </button>

      <input
        value={listening ? interim || "listening…" : text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
        readOnly={listening || disabled}
        placeholder={
          disabled
            ? "JARVIS is powered down — press ⏻ to bring it back online"
            : "Ask JARVIS…  “find a trending LinkedIn topic and post about it”"
        }
        className="min-w-0 flex-1 bg-transparent font-mono text-[13px] text-jarvis outline-none placeholder:text-jarvis/30 disabled:opacity-40"
        disabled={disabled}
      />

      <button
        onClick={send}
        disabled={disabled}
        className="shrink-0 rounded border border-jarvis/40 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.2em] text-jarvis/80 transition hover:bg-jarvis/10 hover:text-jarvis disabled:cursor-not-allowed disabled:opacity-30"
      >
        Send
      </button>
    </div>
  );
}
