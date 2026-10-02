"""Standalone demo server for the ICP Builder workflow.

Separate from the main JARVIS backend/dashboard - its own FastAPI app,
its own port, its own static frontend.

Run: python ai_workflows/icp_builder/server.py
Then open: http://localhost:8091
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from ai_workflows.icp_builder.workflow import (  # noqa: E402
    build_icp_from_description,
    build_icp_from_site,
    find_candidate_leads,
    icp_to_prompt_string,
    launch_campaign,
)

app = FastAPI(title="ICP Builder Demo")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_STATIC = Path(__file__).parent / "static"


class SiteIn(BaseModel):
    url: str = Field(min_length=3, max_length=300)


class DescriptionIn(BaseModel):
    description: str = Field(min_length=10, max_length=4000)


class FindLeadsIn(BaseModel):
    icp_prompt: str = Field(min_length=5, max_length=4000)
    n: int = Field(default=5, ge=1, le=10)


class LaunchIn(BaseModel):
    website_url: str
    icp_prompt: str
    offer: str = Field(default="")
    leads: list[dict] = Field(default_factory=list)
    icp: dict = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    tone: str = Field(default="professional")
    goal: str = Field(default="warm")


@app.post("/api/icp/from-site")
async def icp_from_site(body: SiteIn) -> dict[str, Any]:
    try:
        icp = build_icp_from_site(body.url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Couldn't read that site: {e}") from e
    return {"icp": icp, "prompt": icp_to_prompt_string(icp)}


@app.post("/api/icp/from-description")
async def icp_from_description(body: DescriptionIn) -> dict[str, Any]:
    icp = build_icp_from_description(body.description)
    return {"icp": icp, "prompt": icp_to_prompt_string(icp)}


@app.post("/api/icp/find-leads")
async def icp_find_leads(body: FindLeadsIn) -> dict[str, Any]:
    try:
        leads = find_candidate_leads(body.icp_prompt, n=body.n)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Lead search failed: {e}") from e
    return {"leads": leads}


@app.post("/api/icp/launch")
async def icp_launch(body: LaunchIn) -> dict[str, Any]:
    if not body.leads:
        raise HTTPException(400, "No leads to launch with.")
    try:
        result = launch_campaign(
            body.website_url, body.icp_prompt, body.offer, body.leads,
            icp=body.icp, keywords=body.keywords, tone=body.tone, goal=body.goal,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Launch failed: {e}") from e
    return result


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8091)
