"""API REST del backend. M1: upload media + Intake Agent. M2: normalizer nel
flusso upload + riordino timeline + fill cover/contain + serving anteprime.
M8: eventi realtime (SSE) + gestione errori."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.api.schemas import (
    HealthCheck,
    ProjectState,
    ReorderRequest,
    UpdateMediaRequest,
    UpdateSettingsRequest,
)
from app.agents import (
    audio_analysis,
    edit_director,
    intake,
    normalizer,
    render as render_agent,
    sequence,
    timeline_compiler,
)
from app.pipeline import state as state_store
from app.pipeline.orchestrator import run_qa_with_retry
from app.pipeline.orchestrator import run_stages as _orch_run_stages
from app.jobs import manager as jobs
from app.services.audio_features import AUDIO_EXTS

router = APIRouter()


@router.get("/health", response_model=HealthCheck)
def health() -> HealthCheck:
    return HealthCheck(
        status="ok",
        service="ai-video-maker-backend",
        projects_count=len(state_store.list_projects()),
    )


@router.get("/projects")
def list_projects() -> list[dict]:
    return state_store.list_projects()


@router.post("/projects", response_model=ProjectState, status_code=201)
def create_project() -> dict:
    state = state_store.new_project_state()
    state_store.ensure_project_dirs(state["project_id"])
    state_store.save_state(state)
    return state


@router.get("/projects/{project_id}", response_model=ProjectState)
def get_project(project_id: str) -> dict:
    try:
        return state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None


@router.post("/projects/{project_id}/media", response_model=ProjectState)
async def upload_media(
    project_id: str,
    files: list[UploadFile] = File(...),
    source: str = Form("local"),
) -> dict:
    try:
        state = state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None

    media_dir = state_store.media_dir(project_id)
    media_dir.mkdir(parents=True, exist_ok=True)

    staging = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        safe_name = f"{uuid.uuid4().hex[:8]}{ext}"
        dest = media_dir / safe_name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        staging.append({"path": str(dest), "source": source, "drive_file_id": None})

    state["media_staging"] = staging
    state = await intake.run(state)
    # M2: ogni nuovo media viene subito normalizzato (fit cover/contain,
    # background blur/solid, order_index contigui) — architettura sez. 5 Agente 1.
    state = await normalizer.run(state)
    # M3: durate foto + trim video (deterministico per id, non tocca ordine/fit).
    state = await sequence.run(state)
    state_store.save_state(state)
    return state


_RESOLUTION_RE = re.compile(r"^(\d+)x(\d+)$")
_ALLOWED_FPS = {23, 24, 25, 29, 30, 50, 59, 60}


def _get_state_or_404(project_id: str) -> dict:
    try:
        return state_store.load_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Progetto non trovato") from None


@router.put("/projects/{project_id}/media/order", response_model=ProjectState)
async def reorder_media(project_id: str, body: ReorderRequest) -> dict:
    """M2: applica l'ordine manuale della timeline (RF2).

    `media_ids` deve contenere esattamente tutti gli id esistenti, nel nuovo
    ordine. Rispetta l'ordine utente (Sequence Agent M3 non riordinerà mai
    autonomamente) e rinormalizza gli order_index 0..N-1 + fit via Normalizer.
    """
    state = _get_state_or_404(project_id)
    media = state.get("media", [])
    existing_ids = [m["id"] for m in media]
    if len(body.media_ids) != len(existing_ids):
        raise HTTPException(
            status_code=400,
            detail=f"media_ids deve contenere tutti i {len(existing_ids)} media "
            f"(ricevuti {len(body.media_ids)})",
        )
    if set(body.media_ids) != set(existing_ids):
        raise HTTPException(
            status_code=400, detail="media_ids contiene id sconosciuti o ne omette alcuni"
        )
    if len(set(body.media_ids)) != len(body.media_ids):
        raise HTTPException(status_code=400, detail="media_ids contiene duplicati")

    by_id = {m["id"]: m for m in media}
    for idx, mid in enumerate(body.media_ids):
        by_id[mid]["order_index"] = idx
    state["media"] = [by_id[mid] for mid in body.media_ids]
    # Rinormalizza fit/background senza alterare l'ordine appena impostato.
    # (order_index gia' contigui nell'ordine voluto: il sort del normalizer
    # preserva l'ordine richiesto.)
    state = await normalizer.run(state)
    # M3: riassegna durate/trim in modo idempotente (non altera l'ordine).
    state = await sequence.run(state)
    state_store.save_state(state)
    return state


@router.patch("/projects/{project_id}/media/{media_id}", response_model=ProjectState)
async def update_media(project_id: str, media_id: str, body: UpdateMediaRequest) -> dict:
    """M2: preferenza di sfondo del singolo media (solo portrait ha effetto).

    Per landscape/square il Normalizer forza fit=cover e background=None
    (il frame e' pieno, nessuno sfondo visibile): la preferenza viene
    accettata ma normalizzata a None.
    """
    state = _get_state_or_404(project_id)
    target = next((m for m in state.get("media", []) if m["id"] == media_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Media non trovato")
    if body.background_fill is not None:
        # Marca come override esplicito dell'utente sul singolo media.
        target["background_fill"] = body.background_fill
    state = await normalizer.run(state)
    state_store.save_state(state)
    return state


@router.patch("/projects/{project_id}/settings", response_model=ProjectState)
async def update_settings(project_id: str, body: UpdateSettingsRequest) -> dict:
    """M2: output_spec (sfondo di default, risoluzione, fps).

    Se cambia background_fill, viene propagato a tutti i portrait (il default
    di progetto si applica a tutti; la personalizzazione per-singolo si fa
    dopo via PATCH media).
    """
    state = _get_state_or_404(project_id)
    spec = state.setdefault("output_spec", {})

    if body.background_fill is not None:
        spec["background_fill"] = body.background_fill
        # Propagazione: il nuovo default si applica a tutti i portrait.
        for m in state.get("media", []):
            if m.get("orientation") == "portrait":
                m["background_fill"] = body.background_fill

    if body.resolution is not None:
        m = _RESOLUTION_RE.match(body.resolution)
        if not m:
            raise HTTPException(
                status_code=400, detail="resolution deve essere nel formato LARGHEZZAxALTEZZA (es. 1920x1080)"
            )
        w, h = int(m.group(1)), int(m.group(2))
        if w <= 0 or h <= 0 or w > 7680 or h > 4320:
            raise HTTPException(status_code=400, detail="resolution fuori intervallo supportato")
        spec["resolution"] = body.resolution

    if body.fps is not None:
        if body.fps not in _ALLOWED_FPS:
            raise HTTPException(
                status_code=400,
                detail=f"fps deve essere uno di {sorted(_ALLOWED_FPS)}",
            )
        spec["fps"] = body.fps

    if body.vcodec is not None:
        spec["vcodec"] = body.vcodec

    state = await normalizer.run(state)
    state_store.save_state(state)
    return state


@router.post("/projects/{project_id}/audio", response_model=ProjectState)
async def upload_audio(project_id: str, file: UploadFile = File(...)) -> dict:
    """M3: carica la traccia utente (RF7) e la analizza (Agente 2b).

    Salva in data/projects/<id>/audio/, aggiorna state["audio"] con path +
    duration/bpm/beat_markers/energy. Se l'analisi fallisce, l'errore va in
    errors[] (non bloccante): il path resta salvato per riprovare.
    Un nuovo upload sostituisce la traccia precedente (file vecchio rimosso).
    """
    state = _get_state_or_404(project_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato audio non supportato: {ext or '(nessuna estensione)'} "
            f"(supportati: {sorted(AUDIO_EXTS)})",
        )

    audio_dir = state_store.audio_dir(project_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    dest = audio_dir / f"{uuid.uuid4().hex[:8]}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    old_path = (state.get("audio") or {}).get("path")
    if old_path and old_path != str(dest):
        try:
            Path(old_path).unlink(missing_ok=True)
        except OSError:
            pass

    state.setdefault("audio", {})["path"] = str(dest)
    state = await audio_analysis.run(state)
    state_store.save_state(state)
    return state


@router.post("/projects/{project_id}/edit", response_model=ProjectState)
async def plan_edit(project_id: str) -> dict:
    """M4: genera il piano di montaggio (Sequence -> Edit Director -> Compiler).

    Popola edit_decision_list + render_manifest (manifest ffmpeg pronto, M5 lo
    eseguira'). Errori di stage -> errors[] + pipeline_log failed (500) e stop
    del flusso downstream, come da AGENTS.md.
    """
    state = _get_state_or_404(project_id)
    if not state.get("media"):
        raise HTTPException(status_code=400, detail="Nessun media: carica prima foto/video")
    state = await _run_stages(state, (("sequence", sequence.run),
                                      ("edit_director", edit_director.run),
                                      ("timeline_compiler", timeline_compiler.run)))
    state_store.save_state(state)
    return state


async def _run_stages(state: dict, stages) -> dict:
    """Esegue stage via orchestratore; al primo errore salva e solleva 500
    (stop downstream, AGENTS.md). Errori/log failed gia' registrati dal runner."""
    try:
        return await _orch_run_stages(state, list(stages))
    except HTTPException:
        raise
    except Exception as exc:
        state_store.save_state(state)
        raise HTTPException(status_code=500, detail=f"{exc}") from None


@router.post("/projects/{project_id}/render", response_model=ProjectState)
async def render_video(project_id: str, background: bool = False) -> dict:
    """M5/M6: esportazione end-to-end (piano fresco + render + QA con retry).

    Riesegue Sequence -> Director -> Compiler (idempotenti) poi Render e QA;
    se il QA rigetta per motivi creativi, una ripianificazione con qa_feedback.
    Con background=true accoda invece un job (202) per progetti lunghi.
    Il download e' su GET /projects/{id}/download.
    """
    state = _get_state_or_404(project_id)
    if not state.get("media"):
        raise HTTPException(status_code=400, detail="Nessun media: carica prima foto/video")
    if background:
        try:
            job = jobs.submit(project_id, "render")
        except jobs.JobExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return JSONResponse(status_code=202, content={"job": job})
    state = await _run_stages(state, (("sequence", sequence.run),
                                      ("edit_director", edit_director.run),
                                      ("timeline_compiler", timeline_compiler.run),
                                      ("render", render_agent.run)))
    if not (state.get("render_manifest") or {}).get("status") == "done":
        raise HTTPException(status_code=500, detail="render: manifest non completato")
    try:
        state = await run_qa_with_retry(state)
    except Exception as exc:
        state_store.save_state(state)
        raise HTTPException(status_code=500, detail=f"{exc}") from None
    state_store.save_state(state)
    return state


@router.get("/projects/{project_id}/download")
def download_video(project_id: str):
    """M5: scarica l'mp4 finale (404 se mai renderizzato, 404 se file mancante)."""
    state = _get_state_or_404(project_id)
    out_path = (state.get("render_manifest") or {}).get("output", {}).get("path")
    if not out_path:
        raise HTTPException(status_code=404, detail="Nessun video renderizzato: usa prima Esporta")
    p = Path(out_path)
    if not p.is_absolute():
        p = state_store.project_dir(project_id) / p
    try:
        resolved = p.resolve()
        project_root = state_store.project_dir(project_id).resolve()
        if project_root not in resolved.parents:
            raise HTTPException(status_code=404, detail="Video non trovato")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Video non trovato") from None
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File video mancante su disco")
    return FileResponse(path=str(resolved), media_type="video/mp4",
                        filename=f"video-{project_id}.mp4")


def _resolve_media_path(project_id: str, media_id: str) -> tuple[dict, Path]:
    """Metadata + path assoluto verificato (dentro il progetto, esistente)."""
    state = _get_state_or_404(project_id)
    target = next((m for m in state.get("media", []) if m["id"] == media_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Media non trovato")
    p = Path(target["path"])
    if not p.is_absolute():
        p = state_store.project_dir(project_id) / p
    try:
        resolved = p.resolve()
        project_root = state_store.project_dir(project_id).resolve()
        if project_root not in resolved.parents and resolved != project_root:
            raise HTTPException(status_code=404, detail="Media non trovato")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Media non trovato") from None
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File media mancante su disco")
    return target, resolved


@router.get("/projects/{project_id}/media/{media_id}/file")
def get_media_file(project_id: str, media_id: str):
    """M2: serve il file originale per le anteprime nella timeline.

    Risolve il path dal Project State (non dal nome file richiesto) e verifica
    che resti dentro la cartella del progetto (anti path-traversal).
    """
    _, resolved = _resolve_media_path(project_id, media_id)
    media_type, _ = mimetypes.guess_type(resolved.name)
    return FileResponse(path=str(resolved), media_type=media_type or "application/octet-stream")


def _photo_thumb(src: Path, dest: Path, w: int) -> None:
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((w, w * 4))
        im.save(dest, "JPEG", quality=72)


def _video_thumb(src: Path, dest: Path, w: int, target: dict) -> None:
    ts = float(target.get("trim_start_sec") or 0.0)
    te = target.get("trim_end_sec")
    eff = (float(te) - ts) if te else float(target.get("duration_sec") or 2.0)
    ss = round(ts + max(0.1, min(2.0, eff * 0.1)), 2)
    for attempt_ss in (ss, 0):
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(attempt_ss), "-i", str(src),
             "-frames:v", "1", "-vf", f"scale={w}:-2", "-q:v", "4", str(dest)],
            capture_output=True)
        if proc.returncode == 0 and dest.is_file():
            return
    raise RuntimeError(f"thumb video non generabile: {src.name}")


@router.get("/projects/{project_id}/media/{media_id}/thumb")
def get_media_thumb(project_id: str, media_id: str,
                    w: int = Query(320, ge=64, le=960)):
    """Polish: anteprima JPEG leggera con cache (foto via Pillow, video via ffmpeg).

    La timeline usa queste invece degli originali (centinaia di file OK).
    """
    target, src = _resolve_media_path(project_id, media_id)
    tdir = state_store.thumbs_dir(project_id)
    tdir.mkdir(parents=True, exist_ok=True)
    thumb = tdir / f"{media_id}_w{w}.jpg"
    fresh = thumb.is_file() and thumb.stat().st_mtime >= src.stat().st_mtime
    if not fresh:
        try:
            if target["type"] == "photo":
                _photo_thumb(src, thumb, w)
            else:
                _video_thumb(src, thumb, w, target)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Anteprima non generabile: {exc}") from None
    return FileResponse(path=str(thumb), media_type="image/jpeg")


def progress_payload(state: dict) -> dict:
    """Snapshot leggero per la UI realtime (M8): avanzamento, errori, esiti."""
    manifest = state.get("render_manifest") or {}
    qa = state.get("qa_report") or {}
    return {
        "pipeline_log": (state.get("pipeline_log") or [])[-100:],
        "errors_count": len(state.get("errors", [])),
        "media_count": len(state.get("media", [])),
        "has_audio": bool((state.get("audio") or {}).get("path")),
        "has_edit": bool(state.get("edit_decision_list")),
        "has_render": bool(manifest.get("status") == "done"),
        "qa_status": qa.get("status"),
        "updated_at": state.get("updated_at", 0),
        "jobs": jobs.recent_for_project(state.get("project_id", ""), 5),
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """Stato di un job in coda (202 submit -> poll fino a done/failed)."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return job


@router.get("/projects/{project_id}/events")
async def project_events(project_id: str):
    """M8: stream SSE con lo snapshot di avanzamento a ogni cambiamento.

    Il client riceve subito uno snapshot e poi un evento per ogni modifica
    dello state (upload, reorder, import, render...), piu' heartbeat.
    La chiusura del client cancella il task (fine stream ordinata).
    """
    _get_state_or_404(project_id)
    return StreamingResponse(watch_project(project_id),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


async def watch_project(project_id: str, poll_sec: float = 1.0,
                        heartbeat_every: int = 15):
    """Generatore SSE (anche per test): snapshot a ogni modifica + ping.

    Termina se il progetto sparisce o se il consumer chiude (CancelledError).
    """
    last: str | None = None
    idle = 0
    try:
        while True:
            try:
                state = state_store.load_state(project_id)
            except FileNotFoundError:
                break
            payload = json.dumps(progress_payload(state), ensure_ascii=False)
            if payload != last:
                last = payload
                idle = 0
                yield f"data: {payload}\n\n"
            else:
                idle += 1
                if idle >= heartbeat_every:
                    idle = 0
                    yield ": ping\n\n"
            await asyncio.sleep(poll_sec)
    except asyncio.CancelledError:
        pass


@router.post("/projects/{project_id}/errors/clear", response_model=ProjectState)
def clear_errors(project_id: str) -> dict:
    """M8: azzera gli errori non bloccanti dopo che l'utente li ha visionati."""
    state = _get_state_or_404(project_id)
    state["errors"] = []
    state_store.save_state(state)
    return state