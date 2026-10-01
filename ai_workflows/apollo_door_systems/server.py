"""Standalone demo server for the ai_workflows/ prototypes.

Completely separate from the main JARVIS backend (server/app.py) and
dashboard - its own FastAPI app, its own port, its own static frontend.
Meant to be opened in a browser and shown directly to a lead as a working
proof-of-concept of the exact agent being pitched to them.

Run: python ai_workflows/apollo_door_systems/server.py
Then open: http://localhost:8090
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from ai_workflows.apollo_door_systems.workflow import (  # noqa: E402
    SAMPLE_RFQ,
    compliance_checklist,
    draft_quote,
    extract_job_details,
    to_notion_ready_record,
)

app = FastAPI(title="AI Workflow Demos")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_STATIC = Path(__file__).parent / "static"


class RfqIn(BaseModel):
    rfq_text: str = Field(min_length=1, max_length=8000)


@app.get("/api/apollo/sample")
async def apollo_sample() -> dict[str, str]:
    return {"rfq_text": SAMPLE_RFQ.strip()}


@app.post("/api/apollo/process")
async def apollo_process(body: RfqIn) -> dict[str, Any]:
    job = extract_job_details(body.rfq_text)
    quote = draft_quote(job)
    compliance = compliance_checklist(job)
    record = to_notion_ready_record(job, quote, compliance)
    return {"job": job, "quote": quote, "compliance": compliance, "record": record}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090)
