"use client";

export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "offline";

const COPY: Record<CoreState, string> = {
  idle: "STANDING BY",
  listening: "LISTENING",
  thinking: "WORKING",
  speaking: "RESPONDING",
  offline: "LINK DOWN",
};

const RING: Record<CoreState, string> = {
  idle: "#38e0d0",
  listening: "#ffb454",
  thinking: "#38e0d0",
  speaking: "#7cf5ea",
  offline: "#ff5c72",
};

export function JarvisCore({ state }: { state: CoreState }) {
  const color = RING[state];
  const coreAnim =
    state === "thinking"
      ? "anim-core-think"
      : state === "speaking"
        ? "anim-core-speak"
        : "anim-core-idle";

  return (
    <div className="relative flex h-72 w-72 items-center justify-center">
      <svg viewBox="0 0 200 200" className="absolute inset-0 h-full w-full">
        <circle
          cx="100"
          cy="100"
          r="92"
          fill="none"
          stroke={color}
          strokeOpacity="0.18"
          strokeWidth="1"
        />
        <g className="anim-spin-slow" style={{ transformOrigin: "100px 100px" }}>
          <circle
            cx="100"
            cy="100"
            r="78"
            fill="none"
            stroke={color}
            strokeOpacity="0.5"
            strokeWidth="1.5"
            strokeDasharray="4 10 40 8"
          />
        </g>
        <g className="anim-spin-rev" style={{ transformOrigin: "100px 100px" }}>
          <circle
            cx="100"
            cy="100"
            r="64"
            fill="none"
            stroke={color}
            strokeOpacity="0.35"
            strokeWidth="1"
            strokeDasharray="2 6"
          />
        </g>
      </svg>

      <div
        className={`relative h-28 w-28 rounded-full ${coreAnim}`}
        style={{
          background: `radial-gradient(circle at 50% 40%, ${color}, ${color}22 60%, transparent 72%)`,
          boxShadow: `0 0 60px -6px ${color}aa`,
        }}
      />
      <div className="absolute bottom-2 label" style={{ color }}>
        {state === "offline" ? COPY.offline : COPY[state]}
      </div>
    </div>
  );
}
