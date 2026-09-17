"""Talking-avatar video via a local ComfyUI + SadTalker workflow.

Free, local, unlimited - drives ComfyUI purely over HTTP (upload/prompt/
history), the same way studio/provider.py drives Wan2.1, so this doesn't
need to know where ComfyUI is installed on disk.

One-time setup (in ComfyUI's Manager, with allow_git_url_install/
allow_pip_install enabled in user/__manager/config.ini):
    Install via Git URL -> https://github.com/haomole/Comfyui-SadTalker
Then place its checkpoints under
    custom_nodes/Comfyui-SadTalker/SadTalker/checkpoints/
        SadTalker_V0.0.2_256.safetensors (always) and/or _512.safetensors
        mapping_00109-model.pth.tar, mapping_00229-model.pth.tar
and, for gfpgan_enhance=True, under custom_nodes/Comfyui-SadTalker/gfpgan/weights/
        GFPGANv1.4.pth, detection_Resnet50_Final.pth,
        alignment_WFLW_4HG.pth, parsing_parsenet.pth
See studio/README_comfy.md for the exact download links and the handful of
Windows/embedded-Python compatibility patches this fork needed here.
"""
from __future__ import annotations

import os
import time
import uuid

import httpx

_COMFY_URL = os.getenv("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")


def _upload(filename: str, data: bytes, content_type: str) -> None:
    r = httpx.post(
        f"{_COMFY_URL}/upload/image",
        files={"image": (filename, data, content_type)},
        data={"overwrite": "true"},
        timeout=60,
    )
    r.raise_for_status()


def available() -> bool:
    """True if ComfyUI is reachable and the SadTalker node is registered."""
    try:
        r = httpx.get(f"{_COMFY_URL}/object_info/SadTalker", timeout=5)
        return r.status_code == 200 and "SadTalker" in r.json()
    except Exception:  # noqa: BLE001
        return False


def generate_talking_head(
    image_bytes: bytes,
    audio_bytes: bytes,
    *,
    resolution: str = "256",
    gfpgan_enhance: bool = False,
    still: bool = True,
    pose_style: int = 0,
    timeout: int = 1800,
) -> bytes:
    """Animate a still face photo speaking the given audio. Returns mp4 bytes."""
    tag = uuid.uuid4().hex[:10]
    image_name = f"avatar_{tag}.jpg"
    audio_name = f"avatar_{tag}.mp3"
    _upload(image_name, image_bytes, "image/jpeg")
    _upload(audio_name, audio_bytes, "audio/mpeg")

    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "LoadAudio", "inputs": {"audio": audio_name}},
        "3": {"class_type": "SadTalker", "inputs": {
            "image": ["1", 0],
            "audio": ["2", 0],
            "poseStyle": pose_style,
            "faceModelResolution": resolution,
            "preprocess": "crop",
            "stillMode": still,
            "batchSizeInGeneration": 2,
            "gfpganAsFaceEnhancer": gfpgan_enhance,
            "useIdleMode": False,
            "idleModeTime": 5,
            "useRefVideo": False,
            "refInfo": "pose",
        }},
        "4": {"class_type": "ShowVideo", "inputs": {"show_video_path": ["3", 1]}},
    }
    cid = uuid.uuid4().hex
    r = httpx.post(f"{_COMFY_URL}/prompt", json={"prompt": workflow, "client_id": cid}, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("node_errors"):
        raise RuntimeError(f"SadTalker workflow rejected: {body['node_errors']}")
    pid = body["prompt_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        h = httpx.get(f"{_COMFY_URL}/history/{pid}", timeout=30).json()
        entry = h.get(pid)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msg = "SadTalker failed"
                for m in status.get("messages", []):
                    if m[0] == "execution_error":
                        msg = f"SadTalker failed: {m[1].get('exception_message')}"
                raise RuntimeError(msg)
            path = entry.get("outputs", {}).get("4", {}).get("show_video_path")
            if path:
                # Runs on the same host as ComfyUI (COMFY_URL is loopback in
                # every supported setup), so the absolute path it hands back
                # is directly readable - no /view download plumbing needed.
                with open(path[0], "rb") as f:
                    return f.read()
        time.sleep(3)
    raise RuntimeError("SadTalker generation timed out")
