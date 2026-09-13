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
        raise RuntimeError(
            "image generation needs LLM_PROVIDER=openai (Anthropic has no image model)"
        )

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
        import base64

        last: Exception | None = None
        for model in (settings.openai_image_model, "dall-e-3", "dall-e-2"):
            kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "n": 1}
            if model.startswith("dall-e"):
                kwargs["response_format"] = "b64_json"
                if model == "dall-e-2":
                    kwargs["size"] = "1024x1024"
            try:
                d = self.c.images.generate(**kwargs).data[0]
                if getattr(d, "b64_json", None):
                    return base64.b64decode(d.b64_json)
                if getattr(d, "url", None):
                    import httpx

                    return httpx.get(d.url, timeout=60).content
            except Exception as e:  # noqa: BLE001 - try the next model
                last = e
        raise RuntimeError(f"image generation failed: {last}")

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
        t = self._types
        try:
            resp = self.c.models.generate_content(
                model=self.image_model,
                contents=prompt,
                config=t.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for part in resp.candidates[0].content.parts:
                if getattr(part, "inline_data", None):
                    return part.inline_data.data
            raise RuntimeError("Gemini returned no image part")
        except Exception as gemini_err:
            try:
                import io
                import urllib.parse

                import httpx
                from PIL import Image

                # flux-realism + enhance gives noticeably more photorealistic
                # results than Pollinations' default model/prompt handling.
                boosted = (
                    f"{prompt}, photorealistic, professional photography, "
                    "cinematic lighting, shallow depth of field, DSLR, 8k, highly detailed"
                )
                url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(boosted)
                r = httpx.get(
                    url, timeout=90,
                    params={
                        "width": 1024, "height": 1024, "nologo": "true",
                        "model": "flux-realism", "enhance": "true",
                    },
                )
                r.raise_for_status()

                # The free tier ignores nologo and stamps a watermark in the
                # bottom-right corner regardless - crop that strip off and
                # scale back up rather than ship a competitor's logo.
                img = Image.open(io.BytesIO(r.content))
                w, h = img.size
                crop_h = h - int(h * 0.06)
                img = img.crop((0, 0, w, crop_h)).resize((w, h), Image.LANCZOS)
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=92)
                return buf.getvalue()
            except Exception as poll_err:
                raise RuntimeError(
                    f"image generation failed (gemini: {gemini_err}; pollinations: {poll_err})"
                ) from poll_err

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
