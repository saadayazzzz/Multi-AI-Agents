"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Kokoro voices with a British accent — George is the older, deeper butler register. */
export const BRITISH_VOICES = [
  { id: "bm_george", name: "George", note: "older, deeper — most butler-like" },
  { id: "bm_fable", name: "Fable", note: "measured, storyteller cadence" },
  { id: "bm_lewis", name: "Lewis", note: "crisp, a little younger" },
  { id: "bm_daniel", name: "Daniel", note: "neutral, lighter" },
] as const;
export type VoiceId = (typeof BRITISH_VOICES)[number]["id"];

const VOICE_KEY = "auren.voice";
const SPEED = 0.94; // unhurried, like a butler who is never late

// Best built-in British male voices, used until the neural model is ready (or if it can't load).
const BROWSER_PREFERENCE = [
  /Microsoft Thomas Online \(Natural\)/i,
  /Microsoft Ryan Online \(Natural\)/i,
  /Google UK English Male/i,
  /^Daniel\b/i,
  /Microsoft George/i,
];

export type VoiceEngine = "loading" | "neural" | "browser";

type VoiceApi = {
  supported: boolean;
  listening: boolean;
  speaking: boolean;
  interim: string;
  engine: VoiceEngine;
  /** 0-1 model download progress while the neural voice loads */
  progress: number;
  voice: VoiceId;
  setVoice: (v: VoiceId) => void;
  listenOnce: () => void;
  stop: () => void;
  speak: (text: string) => void;
  /** live 0-1 loudness of what AUREN is saying right now */
  level: () => number;
  onResult: (cb: (text: string) => void) => void;
};

function readVoice(): VoiceId {
  try {
    const v = localStorage.getItem(VOICE_KEY);
    if (v && BRITISH_VOICES.some((x) => x.id === v)) return v as VoiceId;
  } catch {}
  return "bm_george";
}

function britishBrowserVoice(): SpeechSynthesisVoice | null {
  const all = window.speechSynthesis?.getVoices() ?? [];
  for (const re of BROWSER_PREFERENCE) {
    const v = all.find((x) => re.test(x.name));
    if (v) return v;
  }
  return all.find((x) => x.lang === "en-GB") ?? null;
}

// markdown and symbols read badly aloud
function speakable(text: string) {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[*_#`>|~]/g, "")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "the link")
    .replace(/\s+/g, " ")
    .trim();
}

export function useVoice(): VoiceApi {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [interim, setInterim] = useState("");
  const [engine, setEngine] = useState<VoiceEngine>("loading");
  const [progress, setProgress] = useState(0);
  const [voice, setVoiceState] = useState<VoiceId>("bm_george");

  const recRef = useRef<any>(null);
  const resultCb = useRef<(t: string) => void>(() => {});
  const finalRef = useRef("");

  const engineRef = useRef<VoiceEngine>("loading");
  const voiceRef = useRef<VoiceId>("bm_george");
  const workerRef = useRef<Worker | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sampleBuf = useRef<Float32Array | null>(null);
  const sources = useRef<AudioBufferSourceNode[]>([]);
  const playhead = useRef(0);
  const utterance = useRef(0);
  const streamDone = useRef(0);
  const lastText = useRef("");
  const browserSpeaking = useRef(false);

  // ---------- speech recognition ----------
  useEffect(() => {
    const SR =
      (typeof window !== "undefined" &&
        ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)) ||
      null;
    if (!SR) return;
    setSupported(true);
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;

    rec.onresult = (e: any) => {
      let interimTxt = "";
      let finalTxt = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const chunk = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalTxt += chunk;
        else interimTxt += chunk;
      }
      if (interimTxt) setInterim(interimTxt);
      if (finalTxt) finalRef.current += finalTxt;
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => {
      setListening(false);
      setInterim("");
      const txt = finalRef.current.trim();
      finalRef.current = "";
      if (txt) resultCb.current(txt);
    };
    recRef.current = rec;
    return () => {
      try {
        rec.abort();
      } catch {}
    };
  }, []);

  // ---------- audio output ----------
  const audio = useCallback(() => {
    if (!ctxRef.current) {
      const AC = window.AudioContext || (window as any).webkitAudioContext;
      const ctx: AudioContext = new AC();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.6;
      analyser.connect(ctx.destination);
      ctxRef.current = ctx;
      analyserRef.current = analyser;
      sampleBuf.current = new Float32Array(analyser.fftSize);
    }
    return ctxRef.current;
  }, []);

  const silence = useCallback(() => {
    sources.current.forEach((s) => {
      try {
        s.stop();
      } catch {}
    });
    sources.current = [];
    playhead.current = 0;
    workerRef.current?.postMessage({ type: "cancel" });
    if (browserSpeaking.current) window.speechSynthesis?.cancel();
    browserSpeaking.current = false;
  }, []);

  const browserSpeak = useCallback((text: string) => {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = britishBrowserVoice();
    const natural = !!v && /Natural/i.test(v.name);
    if (v) u.voice = v;
    u.lang = "en-GB";
    // neural voices sound best untouched; older ones gain gravitas from a lower pitch
    u.rate = natural ? 0.96 : 0.92;
    u.pitch = natural ? 1 : 0.85;
    u.onstart = () => {
      browserSpeaking.current = true;
      setSpeaking(true);
    };
    u.onend = u.onerror = () => {
      browserSpeaking.current = false;
      setSpeaking(false);
    };
    window.speechSynthesis.speak(u);
  }, []);

  // ---------- neural voice worker ----------
  useEffect(() => {
    const chosen = readVoice();
    voiceRef.current = chosen;
    setVoiceState(chosen);
    window.speechSynthesis?.getVoices(); // browsers load the list lazily

    let worker: Worker;
    try {
      worker = new Worker("/tts-worker.js", { type: "module" });
    } catch {
      engineRef.current = "browser";
      setEngine("browser");
      return;
    }
    workerRef.current = worker;

    worker.onmessage = ({ data }) => {
      switch (data.type) {
        case "progress":
          setProgress(data.total ? data.loaded / data.total : 0);
          break;
        case "ready":
          engineRef.current = "neural";
          setEngine("neural");
          setProgress(1);
          break;
        case "error":
          engineRef.current = "browser";
          setEngine("browser");
          break;
        case "chunk": {
          if (data.id !== utterance.current) return;
          const ctx = audio();
          const buf = ctx.createBuffer(1, data.pcm.length, data.rate);
          buf.copyToChannel(data.pcm, 0);
          const src = ctx.createBufferSource();
          src.buffer = buf;
          src.connect(analyserRef.current!);
          const at = Math.max(ctx.currentTime + 0.04, playhead.current);
          src.start(at);
          playhead.current = at + buf.duration;
          sources.current.push(src);
          setSpeaking(true);
          const id = data.id;
          src.onended = () => {
            sources.current = sources.current.filter((s) => s !== src);
            if (!sources.current.length && streamDone.current === id) setSpeaking(false);
          };
          break;
        }
        case "done":
          if (data.id !== utterance.current) return;
          streamDone.current = data.id;
          if (!sources.current.length) setSpeaking(false);
          break;
        case "failed":
          if (data.id === utterance.current) browserSpeak(lastText.current);
          break;
      }
    };
    worker.onerror = () => {
      engineRef.current = "browser";
      setEngine("browser");
    };

    return () => {
      worker.terminate();
      workerRef.current = null;
    };
  }, [audio, browserSpeak]);

  const speak = useCallback(
    (raw: string) => {
      const text = speakable(raw);
      if (!text || typeof window === "undefined") return;
      lastText.current = text;
      silence();
      if (engineRef.current === "neural" && workerRef.current) {
        const id = ++utterance.current;
        streamDone.current = 0;
        audio().resume().catch(() => {});
        workerRef.current.postMessage({ type: "speak", id, text, voice: voiceRef.current, speed: SPEED });
      } else {
        utterance.current++;
        browserSpeak(text);
      }
    },
    [audio, browserSpeak, silence],
  );

  const level = useCallback(() => {
    const a = analyserRef.current;
    const buf = sampleBuf.current;
    if (a && buf && sources.current.length) {
      a.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      return Math.min(1, Math.sqrt(sum / buf.length) * 5);
    }
    // the browser voice exposes no audio stream — approximate a speaking cadence
    if (browserSpeaking.current) {
      const t = performance.now() / 1000;
      return 0.35 + 0.35 * Math.abs(Math.sin(t * 9.5) * Math.sin(t * 3.7));
    }
    return 0;
  }, []);

  const setVoice = useCallback((v: VoiceId) => {
    voiceRef.current = v;
    setVoiceState(v);
    try {
      localStorage.setItem(VOICE_KEY, v);
    } catch {}
  }, []);

  const listenOnce = useCallback(() => {
    if (!recRef.current || listening) return;
    silence(); // don't talk over the operator
    setSpeaking(false);
    finalRef.current = "";
    setInterim("");
    try {
      recRef.current.start();
      setListening(true);
    } catch {
      /* start() throws if already started */
    }
  }, [listening, silence]);

  const stop = useCallback(() => {
    try {
      recRef.current?.stop();
    } catch {}
  }, []);

  const onResult = useCallback((cb: (t: string) => void) => {
    resultCb.current = cb;
  }, []);

  return {
    supported,
    listening,
    speaking,
    interim,
    engine,
    progress,
    voice,
    setVoice,
    listenOnce,
    stop,
    speak,
    level,
    onResult,
  };
}
