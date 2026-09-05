"""Entrypoint FastAPI.

Avvio: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
(dalla cartella backend/, con il venv attivo)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.drive import router as drive_router
from app.config import PROJECTS_DIR
from app.jobs import manager as jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    recovered = jobs.recover()
    if recovered:
        print(f"[jobs] {recovered} job riaccodati dopo riavvio")
    worker = asyncio.create_task(jobs.worker_loop())
    try:
        yield
    finally:
        worker.cancel()


app = FastAPI(title="AI Video Maker", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(drive_router, prefix="/api")
