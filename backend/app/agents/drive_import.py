"""Agente -1b: Google Drive Import (architettura sez. 5, M7).

Legge state["drive_import_request"] = {file_ids, folder_ids}: espande la
selezione (cartelle ricorsive), scarica i media in parallelo in
data/projects/<id>/media/ (uuid + nome originale preservato) e li mette in
media_staging con source="google_drive" + drive_file_id. I file non
supportati vanno in errors[] senza bloccare gli altri. Non modifica Drive,
non tocca i metadata (quelli li fa l'Intake a valle, come da grafo).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from app.jobs import progress as prog
from app.pipeline import state as state_store
from app.services import drive_client as dc


async def _download_one(service, meta: dict, media_dir: Path,
                        sem: asyncio.Semaphore) -> dict:
    name = f"{uuid.uuid4().hex[:8]}_{dc.sanitize_filename(meta.get('name') or 'file')}"
    dest = media_dir / name
    async with sem:
        try:
            await asyncio.to_thread(dc.download_file, service, meta["id"], dest)
        except Exception as exc:
            return {"error": {"stage": "drive_import",
                              "message": f"{meta.get('name', meta['id'])}: download fallito: {exc}"}}
    return {"path": str(dest), "source": "google_drive", "drive_file_id": meta["id"]}


async def run(project_state: dict) -> dict:
    req = project_state.pop("drive_import_request", None)
    if not req:
        return project_state

    try:
        service = await asyncio.to_thread(dc.get_drive_service)
    except RuntimeError as exc:
        project_state.setdefault("errors", []).append(
            {"stage": "drive_import", "message": str(exc)})
        raise

    file_ids = list(req.get("file_ids", []))
    folder_ids = list(req.get("folder_ids", []))
    if not file_ids and not folder_ids:
        raise ValueError("selezione vuota: indica file_ids e/o folder_ids")

    media, skipped = await asyncio.to_thread(dc.expand_selection, service,
                                             file_ids, folder_ids)
    errors = project_state.setdefault("errors", [])
    for s in skipped:
        label = s.get("name") or s.get("id") or "?"
        errors.append({"stage": "drive_import", "message": f"{label}: {s.get('reason')}"})
    if not media:
        raise ValueError("nessun file immagine/video nella selezione")

    media_dir = state_store.media_dir(project_state["project_id"])
    media_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(dc.DOWNLOAD_WORKERS)
    job_id = project_state.get("_job_id")

    async def _indexed(idx: int, meta: dict) -> tuple[int, dict]:
        return idx, await _download_one(service, meta, media_dir, sem)

    # as_completed per il progress, ma staging in ordine deterministico (indice)
    results: list = [None] * len(media)
    done_n = 0
    for coro in asyncio.as_completed([_indexed(i, m) for i, m in enumerate(media)]):
        idx, r = await coro
        results[idx] = r
        done_n += 1
        prog.set(job_id, done_n / len(media), f"{done_n}/{len(media)} file")

    staging = project_state.setdefault("media_staging", [])
    for r in results:
        if "error" in r:
            errors.append(r["error"])
        else:
            staging.append(r)
    if not staging:
        raise ValueError("tutti i download sono falliti")
    return project_state
