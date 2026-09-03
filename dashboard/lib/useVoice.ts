"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type VoiceApi = {
  supported: boolean;
  listening: boolean;
  speaking: boolean;
  interim: string;
  /** starts listening; resolves with the final transcript (or "" if nothing) */
  listenOnce: () => void;
  stop: () => void;
  speak: (text: string) => void;
  /** set by the consumer: called with the final transcript */
  onResult: (cb: (text: string) => void) => void;
};

export function useVoice(): VoiceApi {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [interim, setInterim] = useState("");
  const recRef = useRef<any>(null);
  const resultCb = useRef<(t: string) => void>(() => {});
  const finalRef = useRef("");

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

  const listenOnce = useCallback(() => {
    if (!recRef.current || listening) return;
    finalRef.current = "";
    setInterim("");
    try {
      recRef.current.start();
      setListening(true);
    } catch {
      /* start() throws if already started */
    }
  }, [listening]);

  const stop = useCallback(() => {
    try {
      recRef.current?.stop();
    } catch {}
  }, []);

  const speak = useCallback((text: string) => {
    if (typeof window === "undefined" || !window.speechSynthesis || !text) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.02;
    u.pitch = 0.9;
    const pick = window.speechSynthesis
      .getVoices()
      .find((v) => /Google UK English Male|Daniel|Microsoft (Guy|Ryan)/i.test(v.name));
    if (pick) u.voice = pick;
    u.onstart = () => setSpeaking(true);
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(u);
  }, []);

  const onResult = useCallback((cb: (t: string) => void) => {
    resultCb.current = cb;
  }, []);

  return { supported, listening, speaking, interim, listenOnce, stop, speak, onResult };
}
