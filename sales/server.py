"""Standalone sales console + API (no JARVIS needed).

    python -m sales.server            # http://127.0.0.1:8092
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from db.database import wait_for_db
from sales.api import router
from sales.db import init_sales_db

app = FastAPI(title="Sales engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.mount("/sales", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="console")


@app.on_event("startup")
def _startup() -> None:
    wait_for_db()
    init_sales_db()


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/sales/")


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host=os.getenv("SALES_HOST", "127.0.0.1"), port=int(os.getenv("SALES_PORT", "8092")))
