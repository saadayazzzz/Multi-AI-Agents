"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { magColor, type Quake, type Sensor, type Telemetry } from "@/components/CesiumGlobe";

const CesiumGlobe = dynamic(() => import("@/components/CesiumGlobe").then((m) => m.CesiumGlobe), {
  ssr: false,
});

const FEEDS = {
  hour: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
  day: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
  week: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
} as const;

type Window_ = keyof typeof FEEDS;

const SENSORS: { key: Sensor; label: string }[] = [
  { key: "optical", label: "optical" },
  { key: "flir", label: "flir / thermal" },
  { key: "nvg", label: "night vision" },
];

function ago(ts: number) {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function GodsEye() {
  const [win, setWin] = useState<Window_>("day");
  const [quakes, setQuakes] = useState<Quake[]>([]);
  const [status, setStatus] = useState<"live" | "stale">("live");
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [lockedId, setLockedId] = useState<string | null>(null);
  const [sensor, setSensor] = useState<Sensor>("optical");
  const [tel, setTel] = useState<Telemetry>({ lat: 0, lon: 0, alt: 0, heading: 0 });
  const [clock, setClock] = useState("");

  const load = useCallback(async (w: Window_) => {
    try {
      const res = await fetch(FEEDS[w], { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const json = await res.json();
      const rows: Quake[] = (json.features ?? [])
        .map((f: any) => ({
          id: f.id,
          mag: f.properties.mag ?? 0,
          place: f.properties.place ?? "unknown region",
          time: f.properties.time,
          lon: f.geometry.coordinates[0],
          lat: f.geometry.coordinates[1],
          depth: f.geometry.coordinates[2],
          tsunami: f.properties.tsunami ?? 0,
          alert: f.properties.alert ?? null,
          url: f.properties.url,
        }))
        .sort((a: Quake, b: Quake) => b.time - a.time);
      setQuakes(rows);
      setStatus("live");
      setLastSync(Date.now());
    } catch {
      setStatus("stale");
    }
  }, []);

  useEffect(() => {
    load(win);
    const iv = setInterval(() => load(win), 60000);
    return () => clearInterval(iv);
  }, [win, load]);

  useEffect(() => {
    const iv = setInterval(() => {
      const d = new Date();
      setClock(
        `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}:${String(
          d.getUTCSeconds(),
        ).padStart(2, "0")}`,
      );
    }, 1000);
    return () => clearInterval(iv);
  }, []);

  const locked = useMemo(() => quakes.find((q) => q.id === lockedId) ?? null, [quakes, lockedId]);
  const strongest = useMemo(
    () => quakes.reduce<Quake | null>((a, q) => (!a || q.mag > a.mag ? q : a), null),
    [quakes],
  );

  const onTelemetry = useCallback((t: Telemetry) => setTel(t), []);
  const onPick = useCallback((id: string) => setLockedId(id), []);

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-void">
      <CesiumGlobe
        quakes={quakes}
        lockedId={lockedId}
        sensor={sensor}
        onPick={onPick}
        onTelemetry={onTelemetry}
      />

      {/* ---- HUD overlay ---- */}
      <div className="pointer-events-none absolute inset-0 z-10">
        {/* corner brackets */}
        {(["tl", "tr", "bl", "br"] as const).map((c) => (
          <span
            key={c}
            className={`absolute h-8 w-8 border-jarvis/50 ${
              c === "tl"
                ? "left-3 top-3 border-l-2 border-t-2"
                : c === "tr"
                  ? "right-3 top-3 border-r-2 border-t-2"
                  : c === "bl"
                    ? "bottom-3 left-3 border-b-2 border-l-2"
                    : "bottom-3 right-3 border-b-2 border-r-2"
            }`}
          />
        ))}

        {/* centre reticle */}
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
          <div className="relative h-24 w-24">
            <span className="absolute left-1/2 top-0 h-5 w-px -translate-x-1/2 bg-jarvis/40" />
            <span className="absolute bottom-0 left-1/2 h-5 w-px -translate-x-1/2 bg-jarvis/40" />
            <span className="absolute left-0 top-1/2 h-px w-5 -translate-y-1/2 bg-jarvis/40" />
            <span className="absolute right-0 top-1/2 h-px w-5 -translate-y-1/2 bg-jarvis/40" />
            <span className="absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-jarvis/20" />
          </div>
        </div>

        {/* top bar */}
        <header className="absolute inset-x-0 top-0 flex flex-wrap items-center justify-between gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-jarvis/60" />
              <span className="relative inline-flex h-3 w-3 rounded-full border-2 border-jarvis" />
            </span>
            <div>
              <h1 className="holo font-mono text-base font-semibold uppercase tracking-[0.4em] text-jarvis">
                God&apos;s Eye
              </h1>
              <div className="font-mono text-[9px] uppercase tracking-[0.25em] text-jarvis/40">
                orbital seismic trace · usgs public feed
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-4 font-mono text-[10px] uppercase tracking-[0.15em] text-jarvis/55">
            <span className="flex items-center gap-1.5">
              <span
                className={`h-1.5 w-1.5 rounded-full ${status === "live" ? "bg-jarvis anim-blip" : "bg-jarvis-amber"}`}
              />
              {status === "live" ? "feed live" : "feed stale"}
            </span>
            <span>
              contacts <b className="text-jarvis">{quakes.length}</b>
            </span>
            <span>
              sync <b className="text-jarvis">{lastSync ? ago(lastSync) : "—"}</b>
            </span>
            <span className="text-jarvis">{clock} UTC</span>
          </div>
        </header>

        {/* left rail */}
        <aside className="pointer-events-auto absolute left-6 top-24 w-52 space-y-4">
          <div>
            <div className="label mb-1.5">Window</div>
            <div className="flex flex-col gap-1">
              {(Object.keys(FEEDS) as Window_[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setWin(k)}
                  className={`chip justify-start ${win === k ? "bg-jarvis/20 text-jarvis" : "opacity-55"}`}
                >
                  {k === "hour" ? "past hour" : k === "day" ? "past day" : "past week · M2.5+"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="label mb-1.5">Sensor</div>
            <div className="flex flex-col gap-1">
              {SENSORS.map((s) => (
                <button
                  key={s.key}
                  onClick={() => setSensor(s.key)}
                  className={`chip justify-start ${
                    sensor === s.key ? "border-jarvis-amber/50 bg-jarvis-amber/15 text-jarvis-amber" : "opacity-55"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="label mb-1.5">Magnitude</div>
            <div className="space-y-1 font-mono text-[10px] text-jarvis/50">
              {[
                ["M6.0+", "#ff5c72"],
                ["M4.5–6.0", "#ffb454"],
                ["M2.5–4.5", "#ffe066"],
                ["< M2.5", "#38e0d0"],
              ].map(([label, color]) => (
                <div key={label} className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                  {label}
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* right rail — lock + log */}
        <aside className="pointer-events-auto absolute bottom-20 right-6 top-24 flex w-[19rem] flex-col gap-3">
          {locked ? (
            <div className="hud-panel shrink-0 p-3">
              <div className="label mb-2">Event Lock</div>
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-3xl" style={{ color: magColor(locked.mag) }}>
                  M{locked.mag.toFixed(1)}
                </span>
                <span className="font-mono text-[10px] text-jarvis/40">{ago(locked.time)}</span>
              </div>
              <div className="mt-1 text-xs leading-snug text-jarvis-soft">{locked.place}</div>
              <dl className="mt-2 grid grid-cols-2 gap-y-1 font-mono text-[10px]">
                <dt className="text-jarvis/35">LAT</dt>
                <dd className="text-right text-jarvis/80">{locked.lat.toFixed(3)}°</dd>
                <dt className="text-jarvis/35">LON</dt>
                <dd className="text-right text-jarvis/80">{locked.lon.toFixed(3)}°</dd>
                <dt className="text-jarvis/35">DEPTH</dt>
                <dd className="text-right text-jarvis/80">{locked.depth?.toFixed(1)} km</dd>
                <dt className="text-jarvis/35">TSUNAMI</dt>
                <dd className={`text-right ${locked.tsunami ? "text-jarvis-red" : "text-jarvis/80"}`}>
                  {locked.tsunami ? "FLAGGED" : "none"}
                </dd>
              </dl>
              <a href={locked.url} target="_blank" rel="noreferrer" className="chip mt-2 inline-flex">
                usgs event page ↗
              </a>
            </div>
          ) : (
            <div className="hud-panel shrink-0 p-3 font-mono text-[10px] text-jarvis/40">
              click any contact on the globe to lock
            </div>
          )}

          <div className="hud-panel flex min-h-0 flex-1 flex-col">
            <div className="flex h-8 shrink-0 items-center justify-between border-b border-jarvis/20 px-3">
              <span className="label">Trace Log</span>
              {strongest && (
                <span className="font-mono text-[10px] text-jarvis-red">
                  max M{strongest.mag.toFixed(1)}
                </span>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {quakes.slice(0, 60).map((q) => (
                <button
                  key={q.id}
                  onClick={() => setLockedId(q.id)}
                  className={`flex w-full items-center gap-2 px-1 py-1 text-left text-[10.5px] transition ${
                    q.id === lockedId ? "bg-jarvis/10" : "hover:bg-jarvis/5"
                  }`}
                >
                  <span className="w-8 shrink-0 text-right font-mono" style={{ color: magColor(q.mag) }}>
                    {q.mag.toFixed(1)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-jarvis/70">{q.place}</span>
                  <span className="shrink-0 font-mono text-[9px] text-jarvis/30">{ago(q.time)}</span>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* bottom telemetry strip */}
        <footer className="absolute inset-x-0 bottom-0 flex flex-wrap items-center justify-between gap-4 border-t border-jarvis/15 bg-black/50 px-6 py-2 font-mono text-[10px] uppercase tracking-[0.15em] text-jarvis/55">
          <div className="flex flex-wrap gap-5">
            <span>
              CAM LAT <b className="text-jarvis">{tel.lat.toFixed(2)}°</b>
            </span>
            <span>
              CAM LON <b className="text-jarvis">{tel.lon.toFixed(2)}°</b>
            </span>
            <span>
              ALT <b className="text-jarvis">{(tel.alt / 1000).toFixed(0)} km</b>
            </span>
            <span>
              HDG <b className="text-jarvis">{tel.heading.toFixed(0)}°</b>
            </span>
          </div>
          <a href="/" className="pointer-events-auto chip">
            ← auren console
          </a>
        </footer>
      </div>
    </div>
  );
}
