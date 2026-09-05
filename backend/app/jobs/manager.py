"""Manager della coda job (vedi package docstring)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app.jobs import progress as prog
from app.pipeline import state as state_store

JOBS_DIR = DATA_DIR / "jobs"
KINDS = ("render", "drive_import")


class JobExistsError(Exception):
    pass


def _path(job_id: str) -> Path:
    if "/" in job_id or "\\" in job_id or not job_id:
        raise ValueError("job_id non valido")
    return JOBS_DIR / f"{job_id}.json"


def _write(job: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_DIR / f".{job['job_id']}.tmp"
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_path(job["job_id"]))


def get(job_id: str) -> dict | None:
    try:
        p = _path(job_id)
    except ValueError:
        return None
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _all() -> list[dict]:
    if not JOBS_DIR.is_dir():
        return []
    out = []
    for p in JOBS_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def recent_for_project(project_id: str, limit: int = 5) -> list[dict]:
    jobs = [j for j in _all() if j.get("project_id") == project_id]
    jobs.sort(key=lambda j: j.get("updated_at", 0), reverse=True)
    return jobs[:limit]


def active_for_project(project_id: str, kind: str) -> dict | None:
    for j in _all():
        if (j.get("project_id") == project_id and j.get("kind") == kind
                and j.get("status") in ("queued", "running")):
            return j
    return None


def submit(project_id: str, kind: str, params: dict | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind non supportato: {kind}")
    if active_for_project(project_id, kind):
        raise JobExistsError(f"job {kind} già in corso per questo progetto")
    now = time.time()
    job = {"job_id": uuid.uuid4().hex[:12], "project_id": project_id, "kind": kind,
           "status": "queued", "params": params or {},
           "progress": {"fraction": 0.0, "note": "in coda", "stage": "queued"},
           "result": None, "error": None,
           "created_at": now, "updated_at": now}
    _write(job)
    return job


def _touch(job: dict, **fields) -> dict:
    job.update(fields)
    job["updated_at"] = time.time()
    _write(job)
    return job


def set_stage(job_id: str, stage: str, note: str = "") -> None:
    job = get(job_id)
    if not job:
        return
    lvl = prog.pop(job_id)
    frac, pnote = lvl if lvl else (job["progress"].get("fraction", 0.0),
                                  job["progress"].get("note", ""))
    job["progress"] = {"fraction": frac, "note": pnote or note, "stage": stage}
    _touch(job)


def recover() -> int:
    """-running -> queued all'avvio (crash precedenti). Ritorna i recuperati."""
    n = 0
    for job in _all():
        if job.get("status") == "running":
            job["status"] = "queued"
            job["progress"] = {"fraction": 0.0, "note": "riaccodato dopo riavvio",
                               "stage": "queued"}
            _touch(job)
            n += 1
    return n


def _claim() -> dict | None:
    queued = [j for j in _all() if j.get("status") == "queued"]
    if not queued:
        return None
    queued.sort(key=lambda j: j.get("created_at", 0))
    job = queued[0]
    job["status"] = "running"
    job["progress"] = {"fraction": 0.0, "note": "avvio", "stage": "starting"}
    _touch(job)
    return job


async def _handle_render(job: dict) -> dict:
    from app.pipeline.orchestrator import run_qa_with_retry, run_stages
    from app.agents import edit_director, render, sequence, timeline_compiler

    jid = job["job_id"]
    state = state_store.load_state(job["project_id"])
    if not state.get("media"):
        raise ValueError("Nessun media: carica prima foto/video")
    state["_job_id"] = jid
    try:
        set_stage(jid, "sequence", "piano di montaggio")
        state = await run_stages(state, [("sequence", sequence.run),
                                         ("edit_director", edit_director.run),
                                         ("timeline_compiler", timeline_compiler.run)])
        set_stage(jid, "render", "rendering ffmpeg")
        state = await run_stages(state, [("render", render.run)])
        set_stage(jid, "qa", "controllo qualità")
        state = await run_qa_with_retry(state)
    except Exception:
        state.pop("_job_id", None)
        state_store.save_state(state)  # preserva log failed + errors
        raise
    state.pop("_job_id", None)
    state_store.save_state(state)
    mf = state.get("render_manifest") or {}
    return {"total_sec": mf.get("total_sec"),
            "output_path": (mf.get("output") or {}).get("path"),
            "qa_status": (state.get("qa_report") or {}).get("status")}


async def _handle_drive_import(job: dict) -> dict:
    from app.pipeline.orchestrator import run_stages
    from app.agents import drive_import, intake, normalizer, sequence

    jid = job["job_id"]
    params = job.get("params", {})
    state = state_store.load_state(job["project_id"])
    state["drive_import_request"] = {"file_ids": params.get("file_ids", []),
                                     "folder_ids": params.get("folder_ids", [])}
    state["_job_id"] = jid
    try:
        set_stage(jid, "drive_import", "download da Drive")
        state = await run_stages(state, [("drive_import", drive_import.run),
                                         ("intake", intake.run),
                                         ("normalizer", normalizer.run),
                                         ("sequence", sequence.run)])
    except Exception:
        state.pop("_job_id", None)
        state_store.save_state(state)
        raise
    state.pop("_job_id", None)
    state_store.save_state(state)
    return {"media_count": len(state.get("media", []))}


async def _run_one(job: dict) -> None:
    jid = job["job_id"]
    stop = asyncio.Event()

    async def heartbeat() -> None:
        """Riversa frazione/nota dal registro nel record ogni 2s."""
        while not stop.is_set():
            await asyncio.sleep(2)
            lvl = prog.peek(jid)
            if lvl is None:
                continue
            cur = get(jid)
            if cur is None or cur.get("status") != "running":
                continue
            cur["progress"] = {"fraction": lvl[0], "note": lvl[1],
                               "stage": cur["progress"].get("stage", "")}
            _touch(cur)

    beat = asyncio.create_task(heartbeat())
    try:
        if job["kind"] == "render":
            result = await _handle_render(job)
        elif job["kind"] == "drive_import":
            result = await _handle_drive_import(job)
        else:
            raise ValueError(f"kind sconosciuto: {job['kind']}")
    except Exception as exc:
        cur = get(jid) or job
        cur["status"] = "failed"
        cur["error"] = str(exc)[-1000:]
        _touch(cur)
        return
    finally:
        stop.set()
        await beat
    cur = get(jid) or job
    cur["status"] = "done"
    cur["progress"] = {"fraction": 1.0, "note": "completato", "stage": "done"}
    cur["result"] = result
    _touch(cur)


async def worker_loop(poll_sec: float = 1.0) -> None:
    """Loop infinito del worker (task di lifespan). Un job alla volta, FIFO."""
    while True:
        job = await asyncio.to_thread(_claim)
        if job is None:
            await asyncio.sleep(poll_sec)
            continue
        await _run_one(job)
