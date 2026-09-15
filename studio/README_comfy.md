# Free local video — ComfyUI backend

`VIDEO_PROVIDER=comfy` generates every clip on your own GPU. Zero API cost,
unlimited. You have an RTX 3090 (24 GB) — plenty for this.

The project's Python is 3.14, which PyTorch doesn't support yet, so we don't run
the model in-process — we drive a local **ComfyUI** (it ships its own Python +
CUDA PyTorch) over its HTTP API.

## One-time setup

1. **Install ComfyUI** (portable Windows build):
   <https://github.com/comfyanonymous/ComfyUI/releases> → download
   `ComfyUI_windows_portable_nvidia.7z`, extract, run `run_nvidia_gpu.bat`.
   It opens at <http://127.0.0.1:8188>.

2. **Load a text-to-video workflow** and download its models:
   - In ComfyUI: **Workflow → Browse Templates → Video → "LTXV text to video"**
     (or **"Wan 2.1 text to video"** — 1.3B fits easily on a 3090 and is fast).
   - ComfyUI will prompt to download the missing model files — accept.
   - Hit **Queue** once with any prompt to confirm it renders end to end.

3. **Mark the prompt node** so the adapter can inject text:
   - Click the **positive** `CLIPTextEncode` node → set its text to exactly
     `{prompt}`  *(or)*  right-click it → *Title* → rename to `PROMPT`.

4. **Export it**: top menu **Workflow → Save (API Format)** → save as
   `studio/comfy_workflow.json` in this repo.

5. **`.env`**:
   ```
   VIDEO_PROVIDER=comfy
   COMFY_URL=http://127.0.0.1:8188
   COMFY_WORKFLOW=studio/comfy_workflow.json
   ```

## Run

Keep `run_nvidia_gpu.bat` running, then:

```bash
python studio_cli.py make "soap cutting" --clips 3 --seconds 5 --target 30
```

or say to JARVIS: *"make a soap-cutting ASMR video"*.

The adapter POSTs the workflow to `/prompt`, polls `/history`, downloads the
output from `/view`, and ffmpeg-converts it to mp4 (LTXV/Wan often output
animated webp/webm). Assembly, thumbnail, metadata and YouTube upload are
unchanged.

## Notes

- 3090 speed: ~20-60 s per 5 s clip (LTX faster, Wan 1.3B ~30 s, Wan 14B slow).
- If `/prompt` returns an error, the workflow has a bad/missing node — fix it in
  ComfyUI and re-export.
- Model downloads live under `ComfyUI/models/` — a few GB per model, one time.
