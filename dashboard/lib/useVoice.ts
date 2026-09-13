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
    const synth = window.speechSynthesis;

    const fire = () => {
      const wasSpeaking = synth.speaking || synth.pending;
      if (wasSpeaking) synth.cancel();

      const go = () => {
        const u = new SpeechSynthesisUtterance(text);
        u.rate = 1.02;
        u.pitch = 0.9;
        const pick = synth
          .getVoices()
          .find((v) => /Google UK English Male|Daniel|Microsoft (Guy|Ryan)/i.test(v.name));
        if (pick) u.voice = pick;

        // Chrome/Edge on Windows frequently drop the onstart/onend events
        // right after a cancel() - set speaking optimistically and clear it
        // with a fallback timer (~110ms/word) so the UI never desyncs from
        // what's actually being said, whether or not those events fire.
        setSpeaking(true);
        const fallbackMs = Math.max(1200, text.split(/\s+/).length * 350);
        const fallback = setTimeout(() => setSpeaking(false), fallbackMs);
        u.onstart = () => setSpeaking(true);
        u.onend = () => {
          clearTimeout(fallback);
          setSpeaking(false);
        };
        u.onerror = () => {
          clearTimeout(fallback);
          setSpeaking(false);
        };
        synth.speak(u);
      };

      // Give a just-cancelled utterance a beat to flush - starting a new one
      // immediately after cancel() is what causes Chrome to drop its events.
      wasSpeaking ? setTimeout(go, 60) : go();
    };

    // Chrome loads the voice list asynchronously - if it's not ready yet,
    // wait for it once so the right voice is picked on the first (only) call.
    if (synth.getVoices().length === 0) {
      const onReady = () => {
        synth.removeEventListener("voiceschanged", onReady);
        fire();
      };
      synth.addEventListener("voiceschanged", onReady);
    } else {
      fire();
    }
  }, []);

  const onResult = useCallback((cb: (t: string) => void) => {
    resultCb.current = cb;
  }, []);

  return { supported, listening, speaking, interim, listenOnce, stop, speak, onResult };
}
