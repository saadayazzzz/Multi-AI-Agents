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
    icp_to_prompt_string,
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


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8091)
