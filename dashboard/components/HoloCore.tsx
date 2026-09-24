"use client";

import { useEffect, useRef, useState } from "react";
import { JarvisCore } from "./JarvisCore";

export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "offline";
export type Readout = { label: string; value: string | number };

/** On-screen radius (px) of the reactor's outer ring — beams and pop-ups anchor to it. */
export function coreRadiusPx(w: number, h: number) {
  return Math.min(h * 0.28, w * 0.19, 285);
}

const PALETTE: Record<
  CoreState,
  { line: string; orb: string; spike: string; speed: number; glow: number; amp: number }
> = {
  idle: { line: "#5ad8ff", orb: "#bff3ff", spike: "#5ad8ff", speed: 1, glow: 1, amp: 0.035 },
  listening: { line: "#7fe6ff", orb: "#ffe2b8", spike: "#ffab40", speed: 1.4, glow: 1.15, amp: 0.17 },
  thinking: { line: "#5ad8ff", orb: "#d8f8ff", spike: "#8fe9ff", speed: 3.2, glow: 1.2, amp: 0.08 },
  speaking: { line: "#9ef0ff", orb: "#ffffff", spike: "#e6fbff", speed: 1.7, glow: 1.35, amp: 0.21 },
  offline: { line: "#ff4d5e", orb: "#ff8a95", spike: "#ff4d5e", speed: 0.12, glow: 0.45, amp: 0.01 },
};

const R_OUT = 1.76;
const FOV = 38;
const SPIKES = 120;
const TAU = Math.PI * 2;
// render above screen resolution and let the browser downsample: thin rings stay razor sharp
const SUPERSAMPLE = 1.5;
// if the GPU can't hold ~45fps at that resolution, fall back to native
const SLOW_FRAME_S = 0.022;

export function HoloCore({
  state,
  readouts = [],
  level,
}: {
  state: CoreState;
  readouts?: Readout[];
  /** live 0-1 loudness of the voice, so the reactor moves with real speech */
  level?: () => number;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef(state);
  const levelRef = useRef(level);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState({ w: 0, h: 0 });

  stateRef.current = state;
  levelRef.current = level;

  useEffect(() => {
    const on = () => setView({ w: window.innerWidth, h: window.innerHeight });
    on();
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  useEffect(() => {
    let alive = true;
    let teardown = () => {};

    (async () => {
      const THREE = await import("three");
      const [
        { EffectComposer },
        { RenderPass },
        { UnrealBloomPass },
        { OutputPass },
        { LineSegments2 },
        { LineSegmentsGeometry },
        { LineMaterial },
      ] = await Promise.all([
        import("three/examples/jsm/postprocessing/EffectComposer.js"),
        import("three/examples/jsm/postprocessing/RenderPass.js"),
        import("three/examples/jsm/postprocessing/UnrealBloomPass.js"),
        import("three/examples/jsm/postprocessing/OutputPass.js"),
        import("three/examples/jsm/lines/LineSegments2.js"),
        import("three/examples/jsm/lines/LineSegmentsGeometry.js"),
        import("three/examples/jsm/lines/LineMaterial.js"),
      ]);
      const host = hostRef.current;
      if (!alive || !host) return;

      let renderer: InstanceType<typeof THREE.WebGLRenderer>;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
      } catch {
        setFailed(true);
        return;
      }
      const dpr = window.devicePixelRatio || 1;
      let pixelRatio = Math.min(2, dpr * SUPERSAMPLE);
      renderer.setPixelRatio(pixelRatio);
      host.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      // not setClearColor: with the composer's linear targets that clears sRGB values and
      // the output pass encodes them twice, lifting black to navy
      scene.background = new THREE.Color(0x02050a);
      scene.fog = new THREE.FogExp2(0x02050a, 0.05);
      const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 200);

      const disposables: { dispose: () => void }[] = [];
      const track = <T extends { dispose: () => void }>(x: T): T => {
        disposables.push(x);
        return x;
      };

      const lineColor = new THREE.Color(PALETTE.idle.line);
      const spikeColor = new THREE.Color(PALETTE.idle.spike);
      const orbColor = new THREE.Color(PALETTE.idle.orb);
      const amber = new THREE.Color("#ffab40");
      const tmp = new THREE.Color();

      const primaryMats: { color: InstanceType<typeof THREE.Color> }[] = [];
      const spikeMats: { color: InstanceType<typeof THREE.Color> }[] = [];
      const fatMats: InstanceType<typeof LineMaterial>[] = [];

      // screen-space-width lines: real pixel widths, anti-aliased by the MSAA target
      const fatMat = (opacity: number, width: number, bucket = primaryMats) => {
        const m = track(
          new LineMaterial({
            color: lineColor.getHex(),
            linewidth: width,
            transparent: true,
            opacity,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          }),
        );
        m.resolution.set(window.innerWidth, window.innerHeight);
        fatMats.push(m);
        bucket.push(m);
        return m;
      };
      const fat = (positions: ArrayLike<number>, mat: InstanceType<typeof LineMaterial>) => {
        const g = track(new LineSegmentsGeometry());
        g.setPositions(positions instanceof Float32Array ? positions : Float32Array.from(positions));
        return new LineSegments2(g, mat);
      };

      const loopSegments = (r: number, n = 200) => {
        const p: number[] = [];
        for (let i = 0; i < n; i++) {
          const a0 = (i / n) * TAU;
          const a1 = ((i + 1) / n) * TAU;
          p.push(Math.cos(a0) * r, Math.sin(a0) * r, 0, Math.cos(a1) * r, Math.sin(a1) * r, 0);
        }
        return p;
      };
      const circle = (r: number, opacity: number, width = 1.3) => fat(loopSegments(r), fatMat(opacity, width));

      const ticks = (
        n: number,
        r1: number,
        r2: number,
        majorEvery: number,
        r1Major: number,
        opacity: number,
        width = 1.1,
      ) => {
        const pos: number[] = [];
        for (let i = 0; i < n; i++) {
          const a = (i / n) * TAU;
          const inner = i % majorEvery === 0 ? r1Major : r1;
          pos.push(Math.cos(a) * inner, Math.sin(a) * inner, 0, Math.cos(a) * r2, Math.sin(a) * r2, 0);
        }
        return fat(pos, fatMat(opacity, width));
      };

      const meshMat = (color: InstanceType<typeof THREE.Color> | null, opacity: number) => {
        const m = track(
          new THREE.MeshBasicMaterial({
            color: color ?? lineColor,
            transparent: true,
            opacity,
            side: THREE.DoubleSide,
            fog: false,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          }),
        );
        if (!color) primaryMats.push(m);
        return m;
      };
      const band = (
        rIn: number,
        rOut: number,
        start: number,
        len: number,
        color: InstanceType<typeof THREE.Color> | null,
        opacity: number,
      ) =>
        new THREE.Mesh(
          track(new THREE.RingGeometry(rIn, rOut, Math.max(12, Math.ceil(len * 48)), 1, start, len)),
          meshMat(color, opacity),
        );

      const ringPoints = (r: number, n = 160) => {
        const p: InstanceType<typeof THREE.Vector3>[] = [];
        for (let i = 0; i < n; i++) {
          const a = (i / n) * TAU;
          p.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0));
        }
        return p;
      };

      const glowTexture = () => {
        const c = document.createElement("canvas");
        c.width = c.height = 256;
        const g = c.getContext("2d")!;
        const grd = g.createRadialGradient(128, 128, 0, 128, 128, 128);
        grd.addColorStop(0, "rgba(255,255,255,1)");
        grd.addColorStop(0.18, "rgba(255,255,255,0.5)");
        grd.addColorStop(0.5, "rgba(255,255,255,0.08)");
        grd.addColorStop(1, "rgba(255,255,255,0)");
        g.fillStyle = grd;
        g.fillRect(0, 0, 256, 256);
        return track(new THREE.CanvasTexture(c));
      };
      const glowTex = glowTexture();

      // ---------- reactor ----------
      type Reveal = {
        obj: InstanceType<typeof THREE.Object3D>;
        mats: { opacity: number }[];
        base: number[];
        delay: number;
        from: number;
      };
      const reveals: Reveal[] = [];
      const reactor = new THREE.Group();
      scene.add(reactor);

      const add = <T extends InstanceType<typeof THREE.Object3D>>(obj: T, delay: number, from = 0.75): T => {
        reactor.add(obj);
        const mats: { opacity: number }[] = [];
        obj.traverse((o: any) => {
          const m = o.material;
          if (Array.isArray(m)) mats.push(...m);
          else if (m) mats.push(m);
        });
        reveals.push({ obj, mats, base: mats.map((m) => m.opacity), delay, from });
        return obj;
      };

      add(circle(1.8, 0.38, 1.2), 0.05, 0.92);
      const outerTicks = add(ticks(180, 1.68, 1.76, 15, 1.6, 0.72, 1.15), 0.2, 0.86);

      const segRing = new THREE.Group();
      (
        [
          [0, 0.9],
          [1.1, 0.4],
          [1.7, 1.2],
          [3.2, 0.15],
          [3.6, 1.6],
          [5.4, 0.6],
        ] as const
      ).forEach(([s, l]) => segRing.add(band(1.44, 1.49, s, l, null, 0.62)));
      add(segRing, 0.4, 0.78);

      const amberArc = new THREE.Group();
      amberArc.add(band(1.54, 1.572, 0, 1.9, amber, 0.95));
      const lead = new THREE.Mesh(track(new THREE.CircleGeometry(0.035, 24)), meshMat(amber, 1));
      lead.position.set(Math.cos(1.9) * 1.556, Math.sin(1.9) * 1.556, 0);
      amberArc.add(lead);
      add(amberArc, 0.7, 0.8);

      const dotMat = track(
        new THREE.PointsMaterial({
          color: lineColor,
          size: 2.2,
          sizeAttenuation: false,
          transparent: true,
          opacity: 0.85,
          fog: false,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        }),
      );
      primaryMats.push(dotMat);
      const dotRing = add(
        new THREE.Points(track(new THREE.BufferGeometry().setFromPoints(ringPoints(1.31, 120))), dotMat),
        0.55,
        0.8,
      );

      const innerTicks = add(ticks(72, 1.05, 1.12, 6, 1.0, 0.62, 1.1), 0.8, 0.8);
      add(circle(0.95, 0.46, 1.2), 0.85, 0.8);

      // voice-reactive spikes: one buffer rewritten in place every frame
      const spikePos = new Float32Array(SPIKES * 6);
      const spikeGeo = track(new LineSegmentsGeometry());
      spikeGeo.setPositions(spikePos);
      const spikeBuffer = (spikeGeo.attributes.instanceStart as any).data as { array: Float32Array; needsUpdate: boolean };
      const spikes = new LineSegments2(spikeGeo, fatMat(0.95, 1.6, spikeMats));
      spikes.frustumCulled = false;
      add(spikes, 0.95, 0.9);

      const gyro = (r: number, opacity: number, rx: number, ry: number, delay: number) => {
        const g = new THREE.Group();
        g.rotation.set(rx, ry, 0);
        const spin = new THREE.Group();
        spin.add(circle(r, opacity, 1.15));
        const bead = new THREE.Mesh(track(new THREE.SphereGeometry(0.022, 16, 16)), meshMat(null, 1));
        bead.position.set(r, 0, 0);
        spin.add(bead);
        g.add(spin);
        add(g, delay, 0.4);
        return spin;
      };
      const gyroA = gyro(0.84, 0.55, 1.25, 0, 1.0);
      const gyroB = gyro(0.74, 0.5, 0, 1.15, 1.08);
      const gyroC = gyro(0.9, 0.3, 0.7, 0.9, 1.16);

      const icoEdges = track(new THREE.EdgesGeometry(track(new THREE.IcosahedronGeometry(0.42, 1))));
      const ico = add(fat(icoEdges.attributes.position.array as Float32Array, fatMat(0.5, 1.0)), 1.22, 0.4);

      // a crisp lens ring hugging the core, so the centre has a defined edge
      add(circle(0.26, 0.85, 1.4), 1.3, 0.3);

      const orbMat = track(new THREE.MeshBasicMaterial({ color: orbColor, fog: false, transparent: true, opacity: 1 }));
      const orb = add(new THREE.Mesh(track(new THREE.SphereGeometry(0.15, 48, 48)), orbMat), 1.35, 0.2);

      const haloMat = track(
        new THREE.SpriteMaterial({
          map: glowTex,
          color: lineColor,
          transparent: true,
          opacity: 0.32,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
          fog: false,
        }),
      );
      primaryMats.push(haloMat);
      const halo = add(new THREE.Sprite(haloMat), 1.3, 0.3);
      halo.scale.set(2.1, 2.1, 1);

      // ---------- ambient particles ----------
      const PN = 700;
      const pp = new Float32Array(PN * 3);
      for (let i = 0; i < PN; i++) {
        const u = Math.random() * 2 - 1;
        const th = Math.random() * TAU;
        const r = 2.3 + Math.random() * 6;
        const s = Math.sqrt(1 - u * u);
        pp[i * 3] = Math.cos(th) * s * r;
        pp[i * 3 + 1] = u * r * 0.6;
        pp[i * 3 + 2] = Math.sin(th) * s * r;
      }
      const partGeo = track(new THREE.BufferGeometry());
      partGeo.setAttribute("position", new THREE.BufferAttribute(pp, 3));
      const particles = new THREE.Points(
        partGeo,
        track(
          new THREE.PointsMaterial({
            color: new THREE.Color("#7fdcff"),
            size: 1.5,
            sizeAttenuation: false,
            transparent: true,
            opacity: 0.35,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          }),
        ),
      );
      scene.add(particles);

      // ---------- holotable floor ----------
      const floor = new THREE.Group();
      floor.position.y = -3.0;
      scene.add(floor);
      const grid = new THREE.GridHelper(90, 90, 0x1b5a7a, 0x123a52);
      const gm = grid.material as any;
      gm.transparent = true;
      gm.opacity = 0.16;
      track(grid.geometry);
      track(gm);
      floor.add(grid);
      [0.9, 1.7, 2.5, 3.4, 4.5].forEach((r, i) => {
        const ring = new THREE.LineLoop(
          track(new THREE.BufferGeometry().setFromPoints(ringPoints(r))),
          track(
            new THREE.LineBasicMaterial({
              color: 0x5ad8ff,
              transparent: true,
              opacity: 0.16 - i * 0.025,
              blending: THREE.AdditiveBlending,
              depthWrite: false,
            }),
          ),
        );
        ring.rotation.x = -Math.PI / 2;
        floor.add(ring);
      });
      const pad = new THREE.Mesh(
        track(new THREE.CircleGeometry(3.4, 64)),
        track(
          new THREE.MeshBasicMaterial({
            map: glowTex,
            color: 0x2a9ed0,
            transparent: true,
            opacity: 0.07,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          }),
        ),
      );
      pad.rotation.x = -Math.PI / 2;
      floor.add(pad);

      // ---------- post: MSAA target, tight bloom ----------
      const msaaTarget = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
      const composer = new EffectComposer(renderer, msaaTarget);
      composer.addPass(new RenderPass(scene, camera));
      // high threshold + small radius: only hot edges glow, so rings stay razor-defined
      const bloom = new UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 0.7, 0.22, 0.28);
      composer.addPass(bloom);
      composer.addPass(new OutputPass());

      let dist = 10;
      const resize = () => {
        const w = window.innerWidth;
        const h = window.innerHeight;
        renderer.setSize(w, h);
        composer.setSize(w, h);
        fatMats.forEach((m) => m.resolution.set(w, h));
        camera.aspect = w / h;
        dist = (R_OUT * h) / (2 * Math.tan((FOV * Math.PI) / 360) * coreRadiusPx(w, h));
        camera.updateProjectionMatrix();
      };
      resize();
      window.addEventListener("resize", resize);

      let mx = 0;
      let my = 0;
      const onMove = (e: PointerEvent) => {
        mx = (e.clientX / window.innerWidth) * 2 - 1;
        my = (e.clientY / window.innerHeight) * 2 - 1;
      };
      window.addEventListener("pointermove", onMove);

      const clock = new THREE.Clock();
      let raf = 0;
      let speed = 1;
      let glow = 1;
      let amp = PALETTE.idle.amp;
      let camX = 0;
      let camY = 0;
      let sampled = 0;
      let sampledTime = 0;
      let qualityChecked = false;

      const loop = () => {
        raf = requestAnimationFrame(loop);
        const dt = Math.min(clock.getDelta(), 0.05);
        const t = clock.elapsedTime;
        const s = stateRef.current;
        const P = PALETTE[s];

        // measure steady-state frame time once the boot sequence has settled
        if (!qualityChecked && t > 2.5) {
          sampled++;
          sampledTime += dt;
          if (t > 5) {
            qualityChecked = true;
            if (sampledTime / sampled > SLOW_FRAME_S && pixelRatio > dpr) {
              pixelRatio = dpr;
              renderer.setPixelRatio(pixelRatio);
              composer.setPixelRatio(pixelRatio);
              resize();
            }
          }
        }

        lineColor.lerp(tmp.set(P.line), 0.06);
        spikeColor.lerp(tmp.set(P.spike), 0.08);
        orbColor.lerp(tmp.set(P.orb), 0.06);
        primaryMats.forEach((m) => m.color.copy(lineColor));
        spikeMats.forEach((m) => m.color.copy(spikeColor));
        orbMat.color.copy(orbColor);
        speed += (P.speed - speed) * 0.05;
        glow += (P.glow - glow) * 0.05;
        const voiceLevel = s === "speaking" ? levelRef.current?.() ?? 0 : 0;
        const ampTarget = s === "speaking" ? 0.04 + voiceLevel * 0.3 : P.amp;
        amp += (ampTarget - amp) * (s === "speaking" ? 0.35 : 0.1);

        outerTicks.rotation.z += 0.02 * speed * dt;
        segRing.rotation.z -= 0.16 * speed * dt;
        amberArc.rotation.z += 0.38 * speed * dt;
        dotRing.rotation.z -= 0.06 * speed * dt;
        innerTicks.rotation.z += 0.09 * speed * dt;
        gyroA.rotation.z += 0.55 * speed * dt;
        gyroB.rotation.z -= 0.45 * speed * dt;
        gyroC.rotation.z += 0.3 * speed * dt;
        ico.rotation.x += 0.12 * speed * dt;
        ico.rotation.y += 0.18 * speed * dt;
        particles.rotation.y += 0.012 * dt;

        const pulse =
          s === "speaking"
            ? 1 + 0.32 * voiceLevel
            : s === "thinking"
              ? 1 + 0.1 * Math.sin(t * 8)
              : 1 + 0.05 * Math.sin(t * 1.6);

        const sp = spikeBuffer.array;
        for (let i = 0; i < SPIKES; i++) {
          const a = (i / SPIKES) * TAU;
          const n =
            s === "speaking" || s === "listening"
              ? 0.3 + 0.7 * Math.abs(Math.sin(t * 7 + i * 0.9) * Math.sin(t * 3.1 + i * 0.37))
              : s === "thinking"
                ? 0.5 + 0.5 * Math.sin(i * 0.35 - t * 6)
                : 0.5 + 0.5 * Math.sin(i * 0.2 + t * 1.2);
          const r0 = 0.58;
          const r1 = r0 + 0.015 + amp * n;
          const c = Math.cos(a);
          const sn = Math.sin(a);
          const o = i * 6;
          sp[o] = c * r0;
          sp[o + 1] = sn * r0;
          sp[o + 2] = 0;
          sp[o + 3] = c * r1;
          sp[o + 4] = sn * r1;
          sp[o + 5] = 0;
        }
        spikeBuffer.needsUpdate = true;

        const dim = s === "offline" ? 0.4 + 0.12 * Math.random() : 1;
        for (const r of reveals) {
          const raw = Math.min(1, Math.max(0, (t - r.delay) / 0.7));
          const k = 1 - Math.pow(1 - raw, 3);
          const flick = raw > 0 && raw < 1 ? 0.55 + 0.45 * Math.random() : 1;
          r.mats.forEach((m, i) => (m.opacity = r.base[i] * k * flick * dim));
          r.obj.scale.setScalar(r.from + (1 - r.from) * k);
        }
        orb.scale.multiplyScalar(pulse);
        haloMat.opacity = 0.32 * glow * Math.min(1, Math.max(0, (t - 1.3) / 0.7)) * dim;

        bloom.strength = 0.7 * glow;

        camX += (mx * 0.4 - camX) * 0.04;
        camY += (-my * 0.25 - camY) * 0.04;
        camera.position.set(camX, camY, dist);
        camera.lookAt(0, 0, 0);

        composer.render();
      };
      loop();

      teardown = () => {
        cancelAnimationFrame(raf);
        window.removeEventListener("resize", resize);
        window.removeEventListener("pointermove", onMove);
        disposables.forEach((d) => d.dispose());
        msaaTarget.dispose();
        composer.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      };
    })();

    return () => {
      alive = false;
      teardown();
    };
  }, []);

  const r = view.w ? coreRadiusPx(view.w, view.h) : 0;
  // flank the reactor's equator — the diagonals belong to the pop-ups
  const ANG = [-168, -12, 12, 168];

  return (
    <>
      <div ref={hostRef} className="pointer-events-none fixed inset-0 z-0" aria-hidden />

      {failed && (
        <div className="pointer-events-none fixed inset-0 z-0 grid place-items-center">
          <JarvisCore state={state} />
        </div>
      )}

      {r > 0 && (
        <div className="pointer-events-none fixed inset-0 z-[4]">
          {readouts.slice(0, 4).map((ro, i) => {
            const a = (ANG[i] * Math.PI) / 180;
            const x = view.w / 2 + Math.cos(a) * r * 1.22;
            const y = view.h / 2 + Math.sin(a) * r * 1.16;
            const left = Math.cos(a) < 0;
            return (
              <div
                key={ro.label}
                className="holo-flicker absolute -translate-y-1/2"
                style={{
                  left: x,
                  top: y,
                  transform: `translate(${left ? "-100%" : "0"}, -50%)`,
                  textAlign: left ? "right" : "left",
                  animationDelay: `${1.6 + i * 0.12}s`,
                }}
              >
                <div className="font-display text-[8px] uppercase tracking-[0.28em] text-jarvis/60">
                  {ro.label}
                </div>
                <div className="holo-hot font-mono text-xl font-medium leading-none">{ro.value}</div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
