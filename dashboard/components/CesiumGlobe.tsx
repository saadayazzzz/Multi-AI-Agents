"use client";

import { useEffect, useRef, useState } from "react";
import "cesium/Build/Cesium/Widgets/widgets.css";

export type Quake = {
  id: string;
  mag: number;
  place: string;
  time: number;
  lon: number;
  lat: number;
  depth: number;
  tsunami: number;
  alert: string | null;
  url: string;
};

export type Sensor = "optical" | "flir" | "nvg";

const SENSOR_FILTER: Record<Sensor, string> = {
  optical: "none",
  flir: "saturate(0) sepia(1) hue-rotate(-35deg) saturate(5) contrast(1.35) brightness(1.05)",
  nvg: "saturate(0) sepia(1) hue-rotate(50deg) saturate(4.5) contrast(1.3) brightness(1.15)",
};

export function magColor(mag: number) {
  if (mag >= 6) return "#ff5c72";
  if (mag >= 4.5) return "#ffb454";
  if (mag >= 2.5) return "#ffe066";
  return "#38e0d0";
}

export type Telemetry = { lat: number; lon: number; alt: number; heading: number };

export function CesiumGlobe({
  quakes,
  lockedId,
  sensor,
  onPick,
  onTelemetry,
}: {
  quakes: Quake[];
  lockedId: string | null;
  sensor: Sensor;
  onPick: (id: string) => void;
  onTelemetry: (t: Telemetry) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);
  const cesiumRef = useRef<any>(null);
  const entityByIdRef = useRef<Map<string, any>>(new Map());
  const lockedRef = useRef<string | null>(null);
  const onPickRef = useRef(onPick);
  const onTelemetryRef = useRef(onTelemetry);
  const [ready, setReady] = useState(false);

  lockedRef.current = lockedId;
  onPickRef.current = onPick;
  onTelemetryRef.current = onTelemetry;

  useEffect(() => {
    let cancelled = false;
    let viewer: any;
    let spinHandler: (() => void) | null = null;

    (async () => {
      (window as any).CESIUM_BASE_URL = "/cesium";
      const Cesium = await import("cesium");
      if (cancelled || !hostRef.current) return;
      cesiumRef.current = Cesium;

      // Keyless Esri satellite imagery — same public source the reference project falls back to.
      const esri = new Cesium.UrlTemplateImageryProvider({
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        maximumLevel: 17,
        credit: "Imagery © Esri, Maxar, Earthstar Geographics",
      });

      viewer = new Cesium.Viewer(hostRef.current, {
        baseLayer: new Cesium.ImageryLayer(esri),
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        animation: false,
        timeline: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
        creditContainer: document.createElement("div"),
      });
      viewerRef.current = viewer;

      const scene = viewer.scene;
      // even illumination: a surveillance feed should never have half the world in night
      scene.globe.enableLighting = false;
      scene.globe.baseColor = Cesium.Color.fromCssColorString("#0b2036");
      scene.skyAtmosphere.show = true;
      scene.fog.enabled = true;
      scene.screenSpaceCameraController.minimumZoomDistance = 250000;

      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(20, 15, 26000000),
      });

      // idle auto-rotation, stopped the moment the operator grabs the globe
      let spinning = true;
      const stopSpin = () => {
        spinning = false;
      };
      scene.canvas.addEventListener("pointerdown", stopSpin);
      scene.canvas.addEventListener("wheel", stopSpin);
      spinHandler = () => {
        scene.canvas.removeEventListener("pointerdown", stopSpin);
        scene.canvas.removeEventListener("wheel", stopSpin);
      };

      viewer.clock.onTick.addEventListener(() => {
        if (spinning) viewer.camera.rotate(Cesium.Cartesian3.UNIT_Z, -0.0006);
        const c = viewer.camera.positionCartographic;
        onTelemetryRef.current({
          lat: Cesium.Math.toDegrees(c.latitude),
          lon: Cesium.Math.toDegrees(c.longitude),
          alt: c.height,
          heading: Cesium.Math.toDegrees(viewer.camera.heading),
        });
      });

      const handler = new Cesium.ScreenSpaceEventHandler(scene.canvas);
      handler.setInputAction((click: any) => {
        const picked = scene.pick(click.position);
        const id = picked?.id?.id;
        if (typeof id === "string") onPickRef.current(id);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      setReady(true);
    })();

    return () => {
      cancelled = true;
      spinHandler?.();
      if (viewer && !viewer.isDestroyed()) viewer.destroy();
      viewerRef.current = null;
      entityByIdRef.current.clear();
    };
  }, []);

  // sync epicentres onto the globe
  useEffect(() => {
    const Cesium = cesiumRef.current;
    const viewer = viewerRef.current;
    if (!Cesium || !viewer || viewer.isDestroyed()) return;

    const map = entityByIdRef.current;
    const seen = new Set(quakes.map((q) => q.id));

    map.forEach((entity, id) => {
      if (!seen.has(id)) {
        viewer.entities.remove(entity);
        map.delete(id);
      }
    });

    quakes.forEach((q) => {
      if (map.has(q.id)) return;
      const color = Cesium.Color.fromCssColorString(magColor(q.mag));
      const base = Math.max(6, Math.min(26, 5 + q.mag * 3.4));
      const entity = viewer.entities.add({
        id: q.id,
        position: Cesium.Cartesian3.fromDegrees(q.lon, q.lat),
        point: {
          pixelSize: new Cesium.CallbackProperty(() => {
            const locked = lockedRef.current === q.id;
            const pulse = 1 + 0.28 * Math.sin(Date.now() / (locked ? 220 : 520));
            return base * pulse * (locked ? 1.5 : 1);
          }, false),
          color: color.withAlpha(0.9),
          outlineColor: Cesium.Color.WHITE.withAlpha(0.8),
          outlineWidth: new Cesium.CallbackProperty(
            () => (lockedRef.current === q.id ? 2.5 : 0.8),
            false,
          ),
        },
        label: {
          text: `M${q.mag.toFixed(1)}`,
          font: "600 11px ui-monospace, monospace",
          fillColor: color,
          showBackground: true,
          backgroundColor: Cesium.Color.fromCssColorString("#04060b").withAlpha(0.65),
          pixelOffset: new Cesium.Cartesian2(0, -20),
          show: new Cesium.CallbackProperty(
            () => lockedRef.current === q.id || q.mag >= 4.5,
            false,
          ),
        },
      });
      map.set(q.id, entity);
    });
  }, [quakes, ready]);

  // fly the camera to whatever is locked
  useEffect(() => {
    const Cesium = cesiumRef.current;
    const viewer = viewerRef.current;
    if (!Cesium || !viewer || viewer.isDestroyed() || !lockedId) return;
    const q = quakes.find((x) => x.id === lockedId);
    if (!q) return;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(q.lon, q.lat, 1200000),
      duration: 1.6,
    });
  }, [lockedId, quakes]);

  return (
    <div className="absolute inset-0">
      <div
        ref={hostRef}
        className="absolute inset-0 transition-[filter] duration-500"
        style={{ filter: SENSOR_FILTER[sensor] }}
      />
      {!ready && (
        <div className="absolute inset-0 grid place-items-center font-mono text-[11px] uppercase tracking-[0.3em] text-jarvis/50">
          initialising orbital feed…
        </div>
      )}
    </div>
  );
}
