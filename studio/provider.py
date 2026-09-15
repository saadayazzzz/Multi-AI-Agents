"""Text-to-video generation.

    VIDEO_PROVIDER=comfy    -> local ComfyUI (100% free, needs a GPU + ComfyUI running)
    VIDEO_PROVIDER=hf       -> Hugging Face Inference (tiny free credit, then paid)
    VIDEO_PROVIDER=openai   -> OpenAI Sora (paid; needs Sora API access)

Env:
    COMFY_URL=http://127.0.0.1:8188
    COMFY_WORKFLOW=studio/comfy_workflow.json   # your "Save (API Format)" export
    HF_TOKEN=hf_xxx ; HF_VIDEO_MODEL=Wan-AI/Wan2.2-TI2V-5B
    OPENAI_VIDEO_MODEL=sora-2 ; VIDEO_SIZE=1280x720
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from config import settings

_PROVIDER = os.getenv("VIDEO_PROVIDER", "openai").lower()


def _read(binary) -> bytes:
    for attr in ("read", "content"):
        v = getattr(binary, attr, None)
        if callable(v):
            return v()
        if isinstance(v, (bytes, bytearray)):
            return bytes(v)
    return bytes(binary)


# --------------------------------------------------------------------------- #
def _openai_clip(prompt: str, seconds: int) -> tuple[bytes, bytes | None]:
    from openai import OpenAI

    oai = OpenAI(api_key=settings.openai_api_key or None)
    model = os.getenv("OPENAI_VIDEO_MODEL", "sora-2")
    size = os.getenv("VIDEO_SIZE", "1280x720")

    v = oai.videos.create_and_poll(
        prompt=prompt, model=model, seconds=str(seconds), size=size,
        poll_interval_ms=5000,
    )
    status = getattr(v, "status", "")
    if status not in ("completed", "succeeded"):
        raise RuntimeError(f"video {getattr(v, 'id', '?')} status={status!r}")

    mp4 = _read(oai.videos.download_content(v.id, variant="video"))
    thumb = None
    try:
        thumb = _read(oai.videos.download_content(v.id, variant="thumbnail"))
    except Exception:  # noqa: BLE001
        pass
    return mp4, thumb


# --------------------------------------------------------------------------- #
def _hf_clip(prompt: str, seconds: int) -> tuple[bytes, bytes | None]:
    from huggingface_hub import InferenceClient

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY")
    if not token:
        raise RuntimeError(
            "VIDEO_PROVIDER=hf needs HF_TOKEN in .env "
            "(free from https://huggingface.co/settings/tokens)"
        )
    model = os.getenv("HF_VIDEO_MODEL", "Wan-AI/Wan2.2-TI2V-5B")
    provider = os.getenv("HF_VIDEO_PROVIDER", "auto")
    client = InferenceClient(token=token, provider=provider)

    try:
        mp4 = client.text_to_video(prompt, model=model)
    except (KeyError, TypeError):
        # some models return a non-standard fal response shape huggingface_hub
        # can't parse; Wan2.2-5B is known-good
        mp4 = client.text_to_video(prompt, model="Wan-AI/Wan2.2-TI2V-5B")
    return bytes(mp4), None  # no thumbnail from HF -> pipeline grabs a frame


# --------------------------------------------------------------------------- #
def _to_mp4(data: bytes) -> bytes:
    """Re-container/encode whatever ComfyUI produced (webp/webm/gif) to mp4."""
    if data[4:8] == b"ftyp":  # already mp4
        return data
    d = Path(tempfile.mkdtemp(prefix="cf_"))
    src, dst = d / "in", d / "out.mp4"
    src.write_bytes(data)
    p = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
        capture_output=True, text=True,
    )
    if p.returncode != 0 or not dst.exists():
        raise RuntimeError(f"ffmpeg convert failed:\n{p.stderr[-500:]}")
    return dst.read_bytes()


def _comfy_clip(prompt: str, seconds: int) -> tuple[bytes, bytes | None]:
    base = os.getenv("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
    wf_path = os.getenv("COMFY_WORKFLOW", str(Path(__file__).with_name("comfy_workflow.json")))
    if not Path(wf_path).exists():
        raise RuntimeError(
            f"missing {wf_path} — in ComfyUI, load a text-to-video workflow, then "
            "'Save (API Format)' it there. Mark the positive-prompt node's text as "
            "'{prompt}' or title it PROMPT."
        )
    wf = json.loads(Path(wf_path).read_text(encoding="utf-8"))

    injected = False
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        ins = node.get("inputs", {})
        title = str((node.get("_meta") or {}).get("title", "")).upper()
        if "text" in ins and (title == "PROMPT" or "{prompt}" in str(ins.get("text", ""))):
            ins["text"] = (
                str(ins["text"]).replace("{prompt}", prompt)
                if "{prompt}" in str(ins["text"]) else prompt
            )
            injected = True
        for k in ("seed", "noise_seed"):
            if isinstance(ins.get(k), (int, float)):
                ins[k] = random.randint(1, 2**31 - 1)
    if not injected:
        for node in wf.values():
            if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
                node.setdefault("inputs", {})["text"] = prompt
                injected = True
                break
    if not injected:
        raise RuntimeError("comfy: could not find a prompt node in the workflow")

    cid = str(random.randint(1, 10**9))
    try:
        r = httpx.post(f"{base}/prompt", json={"prompt": wf, "client_id": cid}, timeout=30)
    except httpx.HTTPError as e:
        raise RuntimeError(f"comfy: cannot reach {base} — is ComfyUI running? ({e})")
    r.raise_for_status()
    pid = r.json()["prompt_id"]

    deadline = time.time() + 1800
    while time.time() < deadline:
        h = httpx.get(f"{base}/history/{pid}", timeout=30).json()
        if pid in h:
            for node_out in h[pid].get("outputs", {}).values():
                for key in ("gifs", "videos", "images"):
                    for f in node_out.get(key, []):
                        raw = httpx.get(
                            f"{base}/view",
                            params={
                                "filename": f["filename"],
                                "subfolder": f.get("subfolder", ""),
                                "type": f.get("type", "output"),
                            },
                            timeout=300,
                        ).content
                        return _to_mp4(raw), None
            raise RuntimeError(f"comfy: run {pid} produced no video/image output")
        time.sleep(3)
    raise RuntimeError("comfy: generation timed out (30 min)")


# --------------------------------------------------------------------------- #
_ADAPTERS = {"comfy": _comfy_clip, "openai": _openai_clip, "hf": _hf_clip}


def generate_clip(prompt: str, seconds: int = 8) -> tuple[bytes, bytes | None]:
    """Return (mp4_bytes, thumbnail_jpg_bytes_or_None)."""
    fn = _ADAPTERS.get(_PROVIDER)
    if not fn:
        raise RuntimeError(
            f"VIDEO_PROVIDER '{_PROVIDER}' unknown — use 'comfy', 'hf' or 'openai'"
        )
    return fn(prompt, seconds)
