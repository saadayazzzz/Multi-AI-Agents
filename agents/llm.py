"""Model backend shared by all three agents and the orchestrator.

Provider-neutral surface (pick with LLM_PROVIDER=openai|anthropic):
  * json_out()       - structured JSON constrained to a JSON Schema
  * research()        - answer a question with live web search
  * generate_text()   - long free-form generation (used for codegen)
  * tool_loop()       - agentic tool-calling loop for the orchestrator
  * parse_file_blocks - split the "=== FILE: path ===" codegen protocol
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from config import settings

# --------------------------------------------------------------------------- #
# provider-neutral helper
# --------------------------------------------------------------------------- #
_FILE_RE = re.compile(
    r"=== FILE: (?P<path>[^\n=]+?) ===\n(?P<body>.*?)\n=== END FILE ===",
    re.DOTALL,
)


def parse_file_blocks(text: str) -> dict[str, str]:
    return {m.group("path").strip(): m.group("body") for m in _FILE_RE.finditer(text)}


# execute(name, args) -> (output_text, is_error)
ExecuteFn = Callable[[str, dict], tuple[str, bool]]
# emit(actor, kind, message, data) -> None
EmitFn = Callable[[str, str, str, dict], None]


def _openai_image(client: Any, prompt: str, size: str) -> bytes:
    """Shared OpenAI image-generation path (gpt-image-1 -> dall-e-3 -> -2).

    Used both by the OpenAI backend directly and, when OPENAI_API_KEY is
    configured, as the preferred image path for the other backends (their own
    image models are either nonexistent or free-tier-gated to a hard 0
    quota) - text/orchestration can stay on a free provider while images use
    a paid one that actually has credit.
    """
    import base64

    last: Exception | None = None
    for model in (settings.openai_image_model, "dall-e-3", "dall-e-2"):
        kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "n": 1}
        if model.startswith("dall-e"):
            kwargs["response_format"] = "b64_json"
            if model == "dall-e-2":
                kwargs["size"] = "1024x1024"
        try:
            d = client.images.generate(**kwargs).data[0]
            if getattr(d, "b64_json", None):
                return base64.b64decode(d.b64_json)
            if getattr(d, "url", None):
                import httpx

                return httpx.get(d.url, timeout=60).content
        except Exception as e:  # noqa: BLE001 - try the next model
            last = e
    raise RuntimeError(f"image generation failed: {last}")


def _aspect_ratio(size: str) -> str:
    try:
        w, h = (int(v) for v in size.lower().split("x", 1))
    except ValueError:
        return "1:1"
    ratio = w / h
    if ratio < 0.8:
        return "9:16"
    if ratio > 1.2:
        return "16:9"
    return "1:1"


def _openrouter_image(prompt: str, size: str) -> bytes:
    """OpenRouter's unified gateway - tried first for image generation when
    configured. Cheaper per image than OpenAI's gpt-image-1 at portrait
    sizes and, unlike Gemini's direct API, not gated to a 0 free-tier quota.
    """
    import base64

    import httpx

    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openrouter_image_model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": _aspect_ratio(size)},
        },
        timeout=60,
    )
    r.raise_for_status()
    images = r.json()["choices"][0]["message"].get("images") or []
    if not images:
        raise RuntimeError("OpenRouter returned no image")
    return base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1])


def _best_effort_image(prompt: str, size: str, native: Callable[[], bytes] | None = None) -> bytes:
    """Try, in order: OpenRouter -> OpenAI -> the backend's own image model
    (if given) -> Pollinations.ai (free, no key, last resort). Each provider
    is only tried if configured; the first success wins.
    """
    import io

    import httpx
    from PIL import Image

    errs: list[str] = []

    if settings.openrouter_api_key:
        try:
            return _openrouter_image(prompt, size)
        except Exception as e:  # noqa: BLE001
            errs.append(f"openrouter: {e}")

    if settings.openai_api_key:
        try:
            from openai import OpenAI

            oai_size = size if size in ("1024x1024", "1024x1536", "1536x1024") else "1024x1536"
            return _openai_image(OpenAI(api_key=settings.openai_api_key), prompt, oai_size)
        except Exception as e:  # noqa: BLE001
            errs.append(f"openai: {e}")

    if native is not None:
        try:
            return native()
        except Exception as e:  # noqa: BLE001
            errs.append(f"native: {e}")

    try:
        boosted = (
            f"{prompt}, photorealistic, professional photography, "
            "bright soft natural lighting, clean simple composition, "
            "shallow depth of field, DSLR, 8k, highly detailed"
        )
        try:
            req_w, req_h = (int(v) for v in size.lower().split("x", 1))
        except ValueError:
            req_w, req_h = 1024, 1024
        import urllib.parse
        import time as _time

        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(boosted)
        r = None
        last_err: Exception | None = None
        for attempt, (w, h) in enumerate([(req_w, req_h)] * 2 + [(1024, 1024)]):
            try:
                r = httpx.get(
                    url, timeout=45,
                    params={"width": w, "height": h, "nologo": "true", "enhance": "true"},
                )
                r.raise_for_status()
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                r = None
                if attempt < 2:
                    _time.sleep(2 * (attempt + 1))
        if r is None:
            raise last_err  # noqa: RSE102

        # The free tier ignores nologo and stamps a watermark in the
        # bottom-right corner regardless - crop that strip off and scale
        # back up rather than ship a competitor's logo.
        img = Image.open(io.BytesIO(r.content))
        w, h = img.size
        crop_h = h - int(h * 0.06)
        img = img.crop((0, 0, w, crop_h)).resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        errs.append(f"pollinations: {e}")

    raise RuntimeError("image generation failed (" + "; ".join(errs) + ")")


# --------------------------------------------------------------------------- #
# Anthropic backend
# --------------------------------------------------------------------------- #
class _Anthropic:
    max_output = 64000

    def __init__(self) -> None:
        import anthropic

        key = settings.anthropic_api_key
        if key.startswith("sk-ant-oat"):
            self.c = anthropic.Anthropic(
                auth_token=key,
                default_headers={"anthropic-beta": "oauth-2025-04-20"},
                max_retries=8,
            )
        else:
            self.c = anthropic.Anthropic(api_key=key or None, max_retries=8)
        self.model = settings.model
        self._web = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}

    def json_out(self, system: str, user: str, schema: dict, max_tokens: int) -> Any:
        resp = self.c.messages.create(
            model=self.model,
            max_tokens=min(max_tokens, self.max_output),
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        return json.loads(next(b.text for b in resp.content if b.type == "text"))

    def research(self, system: str, user: str, max_tokens: int, max_rounds: int) -> str:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        final = None
        for _ in range(max_rounds):
            resp = self.c.messages.create(
                model=self.model,
                max_tokens=min(max_tokens, self.max_output),
                system=system,
                tools=[self._web],
                messages=messages,
            )
            final = resp
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "pause_turn":
                break
        return "\n".join(b.text for b in final.content if b.type == "text")

    def generate_text(self, system: str, user: str, max_tokens: int) -> str:
        with self.c.messages.stream(
            model=self.model,
            max_tokens=min(max_tokens, self.max_output),
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            msg = stream.get_final_message()
        return "\n".join(b.text for b in msg.content if b.type == "text")

    def generate_image(self, prompt: str, size: str) -> bytes:
        # Anthropic has no image model of its own - route through
        # OpenRouter/OpenAI/Pollinations regardless.
        return _best_effort_image(prompt, size)

    def tool_loop(
        self, system: str, user: str, tools: list[dict],
        execute: ExecuteFn, emit: EmitFn, max_iters: int,
    ) -> tuple[str, list[str]]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        spoken, steps = "", []
        for _ in range(max_iters):
            resp = self.c.messages.create(
                model=self.model, max_tokens=8000, system=system,
                tools=tools, messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})
            for b in resp.content:
                if b.type == "text" and b.text.strip():
                    spoken = b.text.strip()
                    emit("orchestrator", "message", spoken, {})
            if resp.stop_reason == "pause_turn":
                continue
            if resp.stop_reason != "tool_use":
                break
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                emit("orchestrator", "tool_call",
                     f"{b.name}({json.dumps(b.input)})", {"tool": b.name, "input": b.input})
                out, err = execute(b.name, b.input or {})
                steps.append(f"{b.name}: {out}")
                emit("orchestrator", "tool_result", out[:2000], {"tool": b.name, "is_error": err})
                results.append({
                    "type": "tool_result", "tool_use_id": b.id,
                    "content": out, "is_error": err,
                })
            messages.append({"role": "user", "content": results})
        return spoken, steps


# --------------------------------------------------------------------------- #
# OpenAI backend
# --------------------------------------------------------------------------- #
class _OpenAI:
    max_output = 32000

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("LLM_PROVIDER=openai but the openai package is missing "
                               "- run: pip install openai") from e
        self.c = OpenAI(api_key=settings.openai_api_key or None)
        self.model = settings.openai_model

    def json_out(self, system: str, user: str, schema: dict, max_tokens: int) -> Any:
        r = self.c.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
            max_completion_tokens=min(max_tokens, self.max_output),
        )
        return json.loads(r.choices[0].message.content)

    def research(self, system: str, user: str, max_tokens: int, max_rounds: int) -> str:
        payload = dict(
            model=self.model,
            input=[{"role": "system", "content": system},
                   {"role": "user", "content": user}],
            max_output_tokens=min(max_tokens, self.max_output),
        )
        for tool in ({"type": "web_search"}, {"type": "web_search_preview"}):
            try:
                r = self.c.responses.create(tools=[tool], **payload)
                return r.output_text
            except Exception:  # noqa: BLE001 - tool name varies by SDK version
                continue
        # last resort: no web tool, model knowledge only
        return self.c.responses.create(**payload).output_text

    def generate_text(self, system: str, user: str, max_tokens: int) -> str:
        stream = self.c.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_completion_tokens=min(max_tokens, self.max_output),
            stream=True,
        )
        parts = [c.choices[0].delta.content for c in stream
                 if c.choices and c.choices[0].delta.content]
        return "".join(parts)

    def generate_image(self, prompt: str, size: str) -> bytes:
        # _best_effort_image already tries OpenAI (via settings.openai_api_key)
        # right after OpenRouter, so no separate "native" path is needed here.
        return _best_effort_image(prompt, size)

    def tool_loop(
        self, system: str, user: str, tools: list[dict],
        execute: ExecuteFn, emit: EmitFn, max_iters: int,
    ) -> tuple[str, list[str]]:
        oai_tools = [{
            "type": "function",
            "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["input_schema"],
            },
        } for t in tools]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        spoken, steps = "", []
        for _ in range(max_iters):
            r = self.c.chat.completions.create(
                model=self.model, messages=messages, tools=oai_tools,
                max_completion_tokens=min(8000, self.max_output),
            )
            m = r.choices[0].message
            messages.append(m.model_dump(exclude_none=True))
            if m.content and m.content.strip():
                spoken = m.content.strip()
                emit("orchestrator", "message", spoken, {})
            if not m.tool_calls:
                break
            for tc in m.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                emit("orchestrator", "tool_call",
                     f"{name}({tc.function.arguments})", {"tool": name, "input": args})
                out, err = execute(name, args)
                steps.append(f"{name}: {out}")
                emit("orchestrator", "tool_result", out[:2000], {"tool": name, "is_error": err})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        return spoken, steps


# --------------------------------------------------------------------------- #
# Gemini backend (free tier - aistudio.google.com/apikey)
# --------------------------------------------------------------------------- #
class _Gemini:
    max_output = 32000

    def __init__(self) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "LLM_PROVIDER=gemini but the google-genai package is missing "
                "- run: pip install google-genai"
            ) from e
        self._genai, self._types = genai, types
        self.model = settings.gemini_model
        self.image_model = settings.gemini_image_model
        self._client: Any = None

    @property
    def c(self) -> Any:
        # Built lazily (not at import time) so a missing GEMINI_API_KEY only
        # errors when Gemini is actually called, not on app startup.
        if self._client is None:
            if not settings.gemini_api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set - add it to .env "
                    "(get a free key at aistudio.google.com/apikey)"
                )
            self._client = self._genai.Client(api_key=settings.gemini_api_key)
        return self._client

    def json_out(self, system: str, user: str, schema: dict, max_tokens: int) -> Any:
        t = self._types
        resp = self.c.models.generate_content(
            model=self.model,
            contents=user,
            config=t.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema,
                max_output_tokens=min(max_tokens, self.max_output),
            ),
        )
        return json.loads(resp.text)

    def research(self, system: str, user: str, max_tokens: int, max_rounds: int) -> str:
        t = self._types
        try:
            resp = self.c.models.generate_content(
                model=self.model,
                contents=user,
                config=t.GenerateContentConfig(
                    system_instruction=system,
                    tools=[t.Tool(google_search=t.GoogleSearch())],
                    max_output_tokens=min(max_tokens, self.max_output),
                ),
            )
            return resp.text
        except Exception:
            # Search grounding needs a billed Gemini project - many free-tier
            # keys get a hard 0 quota for it. Fall back to the model's own
            # knowledge rather than failing the whole agent run.
            resp = self.c.models.generate_content(
                model=self.model,
                contents=user,
                config=t.GenerateContentConfig(
                    system_instruction=system
                    + "\n\nNote: live web search is unavailable right now - answer "
                    "from your best general knowledge instead, and say so.",
                    max_output_tokens=min(max_tokens, self.max_output),
                ),
            )
            return resp.text

    def generate_text(self, system: str, user: str, max_tokens: int) -> str:
        t = self._types
        resp = self.c.models.generate_content(
            model=self.model,
            contents=user,
            config=t.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=min(max_tokens, self.max_output),
            ),
        )
        return resp.text

    def generate_image(self, prompt: str, size: str) -> bytes:
        # Text/orchestration stays on Gemini's free tier; images go through
        # the shared OpenRouter -> OpenAI -> (Gemini's own model) ->
        # Pollinations chain - Gemini's own image model is free-tier-gated
        # to a hard 0 quota (confirmed via RESOURCE_EXHAUSTED), so it rarely
        # actually gets used, but stays as a native option if ever billed.
        def _native() -> bytes:
            t = self._types
            resp = self.c.models.generate_content(
                model=self.image_model,
                contents=prompt,
                config=t.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for part in resp.candidates[0].content.parts:
                if getattr(part, "inline_data", None):
                    return part.inline_data.data
            raise RuntimeError("Gemini returned no image part")

        return _best_effort_image(prompt, size, native=_native)

    def tool_loop(
        self, system: str, user: str, tools: list[dict],
        execute: ExecuteFn, emit: EmitFn, max_iters: int,
    ) -> tuple[str, list[str]]:
        t = self._types
        fn_decls = [
            t.FunctionDeclaration(
                name=tl["name"],
                description=tl["description"],
                parameters_json_schema=tl["input_schema"],
            )
            for tl in tools
        ]
        gemini_tools = [t.Tool(function_declarations=fn_decls)]
        contents: list[Any] = [t.Content(role="user", parts=[t.Part.from_text(text=user)])]
        spoken, steps = "", []
        for _ in range(max_iters):
            resp = self.c.models.generate_content(
                model=self.model,
                contents=contents,
                config=t.GenerateContentConfig(system_instruction=system, tools=gemini_tools),
            )
            cand = resp.candidates[0]
            contents.append(cand.content)
            calls = [p.function_call for p in cand.content.parts if getattr(p, "function_call", None)]
            texts = [p.text for p in cand.content.parts if getattr(p, "text", None)]
            joined = " ".join(x.strip() for x in texts if x and x.strip())
            if joined:
                spoken = joined
                emit("orchestrator", "message", spoken, {})
            if not calls:
                break
            response_parts = []
            for fc in calls:
                args = dict(fc.args or {})
                emit("orchestrator", "tool_call", f"{fc.name}({json.dumps(args)})",
                     {"tool": fc.name, "input": args})
                out, err = execute(fc.name, args)
                steps.append(f"{fc.name}: {out}")
                emit("orchestrator", "tool_result", out[:2000], {"tool": fc.name, "is_error": err})
                response_parts.append(
                    t.Part.from_function_response(name=fc.name, response={"result": out, "is_error": err})
                )
            contents.append(t.Content(role="user", parts=response_parts))
        return spoken, steps


# --------------------------------------------------------------------------- #
# selection + public surface
# --------------------------------------------------------------------------- #
PROVIDER = settings.llm_provider.strip().lower()
_backend: Any = {"openai": _OpenAI, "anthropic": _Anthropic, "gemini": _Gemini}[PROVIDER]()
MODEL = _backend.model


def json_out(system: str, user: str, schema: dict, *, max_tokens: int = 16000) -> Any:
    return _backend.json_out(system, user, schema, max_tokens)


def research(system: str, user: str, *, max_tokens: int = 16000, max_rounds: int = 8) -> str:
    return _backend.research(system, user, max_tokens, max_rounds)


def generate_text(system: str, user: str, *, max_tokens: int = 64000) -> str:
    return _backend.generate_text(system, user, max_tokens)


def generate_image(prompt: str, *, size: str = "1024x1024") -> bytes:
    return _backend.generate_image(prompt, size)


def tool_loop(
    system: str, user: str, tools: list[dict],
    execute: ExecuteFn, emit: EmitFn, *, max_iters: int = 20,
) -> tuple[str, list[str]]:
    return _backend.tool_loop(system, user, tools, execute, emit, max_iters)
