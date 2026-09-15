"""Answer-engine adapters.

Each adapter takes a query and returns the engine's natural-language answer,
using live web access where the engine supports it. This is what we then analyse
for brand visibility.

MVP: one adapter ("openai") backed by the shared LLM layer with web search.
Next: dedicated Perplexity (sonar API), Anthropic (web search), and Google AI
Overviews (via a SERP data vendor) adapters — same signature.
"""
from __future__ import annotations

from agents.llm import PROVIDER, research

_ANSWER_SYSTEM = (
    "You are a helpful answer engine used by a real person doing product research. "
    "Answer the question directly and concisely using web search. Where relevant, "
    "recommend specific brands, products, tools or companies by name, and cite the "
    "sources (URLs) you relied on."
)


def openai_answer(query: str) -> str:
    return research(_ANSWER_SYSTEM, query, max_tokens=1400, max_rounds=4)


ENGINES = {
    "openai": openai_answer,
}


def check_engine(name: str) -> None:
    if name not in ENGINES:
        raise SystemExit(f"unknown engine '{name}' (have: {', '.join(ENGINES)})")
    if name == "openai" and PROVIDER != "openai":
        raise SystemExit(
            "engine 'openai' needs LLM_PROVIDER=openai in .env "
            f"(currently '{PROVIDER}')"
        )
