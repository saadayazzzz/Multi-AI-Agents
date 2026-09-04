"use client";

export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "offline";

const COL: Record<CoreState, string> = {
  idle: "#38e0d0",
  listening: "#ffb454",
  thinking: "#38e0d0",
  speaking: "#7cf5ea",
  offline: "#ff5c72",
};

const OUTER_TICKS = Array.from({ length: 72 }, (_, i) => i);
const BARS = Array.from({ length: 40 }, (_, i) => i);

export function JarvisCore({ state }: { state: CoreState }) {
  const c = COL[state];
  const coreAnim =
    state === "thinking"
      ? "anim-core-think"
      : state === "speaking"
        ? "anim-core-speak"
        : "anim-core-idle";
  const midSpin = state === "thinking" ? "anim-spin-cw-fast" : "anim-spin-cw";
  const emitting = state === "speaking" || state === "listening";

  return (
    <div
      className="relative aspect-square w-[min(78vw,60vh,560px)] select-none"
      style={{ color: c }}
    >
      {/* emitted pulse waves */}
      {emitting && (
        <>
          <span
            className="anim-emit absolute inset-[18%] rounded-full border"
            style={{ borderColor: c }}
          />
          <span
            className="anim-emit-2 absolute inset-[18%] rounded-full border"
            style={{ borderColor: c }}
          />
        </>
      )}

      <svg viewBox="0 0 400 400" className="absolute inset-0 h-full w-full anim-reactor-glow">
        {/* outer tick ring */}
        <g stroke={c} strokeOpacity="0.4">
          {OUTER_TICKS.map((i) => {
            const a = (i / OUTER_TICKS.length) * Math.PI * 2;
            const major = i % 6 === 0;
            const r1 = major ? 178 : 184;
            return (
              <line
                key={i}
                x1={200 + Math.cos(a) * r1}
                y1={200 + Math.sin(a) * r1}
                x2={200 + Math.cos(a) * 190}
                y2={200 + Math.sin(a) * 190}
                strokeWidth={major ? 1.6 : 0.7}
              />
            );
          })}
        </g>
        <circle cx="200" cy="200" r="168" fill="none" stroke={c} strokeOpacity="0.12" />

        {/* rotating segmented ring */}
        <g className="anim-spin-cw" style={{ transformOrigin: "200px 200px" }}>
          <circle
            cx="200" cy="200" r="150" fill="none" stroke={c} strokeOpacity="0.6"
            strokeWidth="2" strokeLinecap="round"
            strokeDasharray="2 20 90 20 2 20 60 20"
          />
        </g>

        {/* counter-rotating thin ring */}
        <g className="anim-spin-ccw" style={{ transformOrigin: "200px 200px" }}>
          <circle
            cx="200" cy="200" r="126" fill="none" stroke={c} strokeOpacity="0.35"
            strokeWidth="1" strokeDasharray="1.5 9"
          />
        </g>

        {/* fast reticle when thinking */}
        <g className={midSpin} style={{ transformOrigin: "200px 200px" }} opacity={state === "thinking" ? 1 : 0.4}>
          <path
            d="M200 92 A108 108 0 0 1 293 146"
            fill="none" stroke={c} strokeOpacity="0.8" strokeWidth="2.5" strokeLinecap="round"
          />
          <path
            d="M200 308 A108 108 0 0 1 107 254"
            fill="none" stroke={c} strokeOpacity="0.8" strokeWidth="2.5" strokeLinecap="round"
          />
        </g>

        {/* hex reticle */}
        <polygon
          points="200,120 269,160 269,240 200,280 131,240 131,160"
          fill="none" stroke={c} strokeOpacity="0.22" strokeWidth="1"
        />

        {/* amplitude bars (listening / speaking) */}
        {emitting && (
          <g className="anim-spin-cw" style={{ transformOrigin: "200px 200px" }}>
            {BARS.map((i) => {
              const a = (i / BARS.length) * Math.PI * 2;
              const h = 6 + ((i * 37) % 22);
              return (
                <line
                  key={i}
                  x1={200 + Math.cos(a) * 100}
                  y1={200 + Math.sin(a) * 100}
                  x2={200 + Math.cos(a) * (100 + h)}
                  y2={200 + Math.sin(a) * (100 + h)}
                  stroke={c}
                  strokeOpacity="0.5"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                />
              );
            })}
          </g>
        )}

        {/* crosshair */}
        <g stroke={c} strokeOpacity="0.16" strokeWidth="1">
          <line x1="200" y1="20" x2="200" y2="60" />
          <line x1="200" y1="340" x2="200" y2="380" />
          <line x1="20" y1="200" x2="60" y2="200" />
          <line x1="340" y1="200" x2="380" y2="200" />
        </g>
      </svg>

      {/* core orb + wordmark */}
      <div className="absolute inset-0 grid place-items-center">
        <div
          className={`relative grid h-[34%] w-[34%] place-items-center rounded-full ${coreAnim}`}
          style={{
            background: `radial-gradient(circle at 50% 38%, ${c}, ${c}26 56%, transparent 72%)`,
            boxShadow: `0 0 90px -10px ${c}, inset 0 0 40px -12px ${c}`,
          }}
        >
          <span className="holo font-mono text-[clamp(14px,3.2vw,26px)] font-semibold tracking-[0.34em] text-white/90">
            JARVIS
          </span>
        </div>
      </div>
    </div>
  );
}
