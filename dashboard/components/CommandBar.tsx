"use client";

import { useState } from "react";

export function CommandBar({
  supported,
  listening,
  interim,
  onMic,
  onSubmitText,
}: {
  supported: boolean;
  listening: boolean;
  interim: string;
  onMic: () => void;
  onSubmitText: (text: string) => void;
}) {
  const [text, setText] = useState("");

  const send = () => {
    const t = text.trim();
    if (!t) return;
    onSubmitText(t);
    setText("");
  };

  return (
    <div className="panel flex items-center gap-3 px-3 py-3">
      <button
        onClick={onMic}
        disabled={!supported}
        title={supported ? "Hold a thought and speak" : "Voice not supported in this browser"}
        className={`grid h-12 w-12 shrink-0 place-items-center rounded-full border transition ${
          listening
            ? "border-jarvis-amber bg-jarvis-amber/10 text-jarvis-amber"
            : "border-jarvis bg-jarvis/10 text-jarvis hover:bg-jarvis/20"
        } disabled:opacity-30`}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="2" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v4" />
        </svg>
      </button>

      <input
        value={listening ? interim || "listening…" : text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
        readOnly={listening}
        placeholder='Say or type a command — e.g. "find fresh sites, scrape them, then rebuild the store"'
        className="flex-1 bg-transparent font-mono text-sm text-slate-200 outline-none placeholder:text-slate-600"
      />

      <button
        onClick={send}
        className="shrink-0 rounded-lg border border-edge px-4 py-2 font-mono text-xs uppercase tracking-wider text-slate-300 hover:border-jarvis hover:text-jarvis"
      >
        Send
      </button>
    </div>
  );
}
