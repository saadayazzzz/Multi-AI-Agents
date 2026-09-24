// AUREN's neural voice. Runs Kokoro (open-source, Apache-2.0) in a background thread so
// speech synthesis never stalls the console's render loop. Audio streams back one sentence
// at a time, so playback starts before the whole reply has been generated.
import { KokoroTTS } from "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js";

const MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";

let tts = null;
let current = 0; // only this utterance may keep streaming
let chain = Promise.resolve(); // one inference at a time on the shared session

const ready = (async () => {
  try {
    tts = await KokoroTTS.from_pretrained(MODEL, {
      dtype: "q8",
      device: "wasm",
      progress_callback: (p) => {
        if (p.status === "progress" && typeof p.file === "string" && p.file.endsWith(".onnx")) {
          self.postMessage({ type: "progress", loaded: p.loaded, total: p.total });
        }
      },
    });
    self.postMessage({ type: "ready" });
  } catch (e) {
    self.postMessage({ type: "error", message: String((e && e.message) || e) });
  }
})();

async function speak({ id, text, voice, speed }) {
  await ready;
  if (!tts || current !== id) return;
  try {
    for await (const { audio } of tts.stream(text, { voice, speed })) {
      if (current !== id) return;
      const pcm = audio.audio;
      self.postMessage({ type: "chunk", id, pcm, rate: audio.sampling_rate }, [pcm.buffer]);
    }
    if (current === id) self.postMessage({ type: "done", id });
  } catch (e) {
    self.postMessage({ type: "failed", id, message: String((e && e.message) || e) });
  }
}

self.onmessage = ({ data }) => {
  if (data.type === "cancel") {
    current = -1;
  } else if (data.type === "speak") {
    current = data.id;
    chain = chain.then(() => speak(data));
  }
};
