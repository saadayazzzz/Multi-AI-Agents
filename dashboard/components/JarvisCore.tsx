"use client";

export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "offline";

export type Readout = { label: string; value: string | number };

const PRIMARY: Record<CoreState, string> = {
  idle: "#38e0d0",
  listening: "#ffb454",
  thinking: "#38e0d0",
  speaking: "#7cf5ea",
  offline: "#ff5c72",
};
const ACCENT: Record<CoreState, string> = {
  idle: "#ff8a3c",
  listening: "#ffd27a",
  thinking: "#ff8a3c",
  speaking: "#38e0d0",
  offline: "#ff8a8a",
};

const C = 210;
const outerTicks = Array.from({ length: 90 }, (_, i) => i);
const innerTicks = Array.from({ length: 60 }, (_, i) => i);
const spokes = [18, 52, 128, 164, 212, 300, 336]; // degrees — radial callout lines
const bars = Array.from({ length: 44 }, (_, i) => i);

function pt(deg: number, r: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [C + Math.cos(a) * r, C + Math.sin(a) * r];
}

export function JarvisCore({
  state,
  readouts = [],
}: {
  state: CoreState;
  readouts?: Readout[];
}) {
  const p = PRIMARY[state];
  const a = ACCENT[state];
  const coreAnim =
    state === "thinking"
      ? "anim-core-think"
      : state === "speaking"
        ? "anim-core-speak"
        : "anim-core-idle";
  const speaking = state === "speaking";
  const emitting = speaking || state === "listening";

  return (
    <div
      className="relative aspect-square w-[min(82vw,64vh,600px)] select-none"
      style={{ color: p }}
    >
      {/* listening: slow ripples */}
      {state === "listening" && (
        <>
          <span className="anim-emit absolute inset-[20%] rounded-full border" style={{ borderColor: p }} />
          <span className="anim-emit-2 absolute inset-[20%] rounded-full border" style={{ borderColor: p }} />
        </>
      )}

      {/* speaking: soft rings drifting outward in a gentle wave */}
      {speaking && (
        <>
          <span
            className="anim-speak-ring absolute inset-[28%] rounded-full border"
            style={{ borderColor: p }}
          />
          <span
            className="anim-speak-ring absolute inset-[28%] rounded-full border"
            style={{ borderColor: p, animationDelay: "0.57s" }}
          />
          <span
            className="anim-speak-ring absolute inset-[28%] rounded-full border"
            style={{ borderColor: a, animationDelay: "1.13s" }}
          />
        </>
      )}

      <svg
        viewBox="0 0 420 420"
        className="absolute inset-0 h-full w-full"
        style={{ filter: `drop-shadow(0 0 18px ${p}) drop-shadow(0 0 40px ${p}55)` }}
      >
        {/* ---- outer detail ring ---- */}
        <circle cx={C} cy={C} r="200" fill="none" stroke={p} strokeOpacity="0.1" />
        <g stroke={p} strokeOpacity="0.45">
          {outerTicks.map((i) => {
            const deg = (i / outerTicks.length) * 360;
            const major = i % 5 === 0;
            const [x1, y1] = pt(deg, major ? 188 : 194);
            const [x2, y2] = pt(deg, 200);
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth={major ? 1.6 : 0.7} />;
          })}
        </g>

        {/* ---- bright accent arc (the warm sweep) ---- */}
        <g className="anim-spin-cw" style={{ transformOrigin: "210px 210px" }}>
          <path
            d={`M ${pt(-58, 176)[0]} ${pt(-58, 176)[1]} A 176 176 0 0 1 ${pt(46, 176)[0]} ${pt(46, 176)[1]}`}
            fill="none"
            stroke={a}
            strokeWidth="3.4"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 8px ${a})` }}
          />
          <circle cx={pt(-58, 176)[0]} cy={pt(-58, 176)[1]} r="3.4" fill={a} />
        </g>

        {/* ---- rotating segmented ring ---- */}
        <g className={state === "thinking" ? "anim-spin-cw-fast" : "anim-spin-cw"} style={{ transformOrigin: "210px 210px" }}>
          <circle
            cx={C} cy={C} r="164" fill="none" stroke={p} strokeOpacity="0.65"
            strokeWidth="2.2" strokeLinecap="round"
            strokeDasharray="2 16 84 16 2 16 54 16"
          />
        </g>

        {/* ---- counter-rotating fine ring ---- */}
        <g className="anim-spin-ccw" style={{ transformOrigin: "210px 210px" }}>
          <circle cx={C} cy={C} r="146" fill="none" stroke={p} strokeOpacity="0.32" strokeWidth="1" strokeDasharray="1.5 8" />
        </g>

        {/* ---- radial callout lines (where trend feeds anchor) ---- */}
        <g stroke={p} strokeOpacity="0.4">
          {spokes.map((deg, i) => {
            const [x1, y1] = pt(deg, 104);
            const [x2, y2] = pt(deg, 190);
            const warm = i % 3 === 0;
            return (
              <g key={deg}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth="0.9" stroke={warm ? a : p} strokeOpacity={warm ? 0.55 : 0.35} />
                <circle cx={x2} cy={y2} r="2.2" fill={warm ? a : p} fillOpacity="0.8" />
              </g>
            );
          })}
        </g>

        {/* ---- amplitude bars ---- */}
        {emitting && (
          <g className="anim-spin-cw" style={{ transformOrigin: "210px 210px" }}>
            {bars.map((i) => {
              const deg = (i / bars.length) * 360;
              const h = 5 + ((i * 41) % 20);
              const [x1, y1] = pt(deg, 116);
              const [x2, y2] = pt(deg, 116 + h);
              return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={p} strokeOpacity="0.5" strokeWidth="2.4" strokeLinecap="round" />;
            })}
          </g>
        )}

        {/* ---- hex reticle + inner ticks ---- */}
        <polygon
          points={[0, 60, 120, 180, 240, 300].map((d) => pt(d - 90, 96).join(",")).join(" ")}
          fill="none" stroke={p} strokeOpacity="0.22" strokeWidth="1"
        />
        <g stroke={p} strokeOpacity="0.3">
          {innerTicks.map((i) => {
            const deg = (i / innerTicks.length) * 360;
            const [x1, y1] = pt(deg, 78);
            const [x2, y2] = pt(deg, 84);
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth="0.7" />;
          })}
        </g>

        {/* ---- crosshair ---- */}
        <g stroke={p} strokeOpacity="0.15" strokeWidth="1">
          <line x1={C} y1="22" x2={C} y2="58" />
          <line x1={C} y1="362" x2={C} y2="398" />
          <line x1="22" y1={C} x2="58" y2={C} />
          <line x1="362" y1={C} x2="398" y2={C} />
        </g>

        {/* ---- bright hotspot nodes ---- */}
        <circle cx={pt(224, 164)[0]} cy={pt(224, 164)[1]} r="4" fill={p} style={{ filter: `drop-shadow(0 0 8px ${p})` }} />
        <circle cx={pt(-12, 164)[0]} cy={pt(-12, 164)[1]} r="3.5" fill={a} style={{ filter: `drop-shadow(0 0 8px ${a})` }} />
      </svg>

      {/* core orb + wordmark */}
      <div className="absolute inset-0 grid place-items-center">
        <div
          className={`relative grid h-[30%] w-[30%] place-items-center rounded-full ${coreAnim}`}
          style={{
            background: `radial-gradient(circle at 50% 36%, ${p}, ${p}22 55%, transparent 72%)`,
            boxShadow: speaking
              ? `0 0 120px -6px ${p}, 0 0 50px -6px ${a}88, inset 0 0 46px -12px ${p}`
              : `0 0 100px -8px ${p}, 0 0 40px -6px ${a}66, inset 0 0 44px -14px ${p}`,
          }}
        >
          <span className="holo font-mono text-[clamp(13px,3vw,24px)] font-semibold tracking-[0.36em] text-white/90">
            JARVIS
          </span>
        </div>
      </div>

      {/* rim readouts */}
      <div className="pointer-events-none absolute inset-0">
        {readouts.slice(0, 4).map((r, i) => {
          const deg = [-125, -55, 55, 125][i];
          const [x, y] = pt(deg, 218);
          return (
            <div
              key={r.label}
              className="absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap text-center font-mono"
              style={{ left: `${(x / 420) * 100}%`, top: `${(y / 420) * 100}%` }}
            >
              <div className="text-[9px] uppercase tracking-[0.2em] text-jarvis/45">{r.label}</div>
              <div className="holo text-sm text-jarvis">{r.value}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
