"""API Google Drive (M7): OAuth2, browse account, import parallelo nel progetto.

Redirect URI da registrare in Google Cloud Console (URI di reindirizzamento
autorizzati): http://127.0.0.1:8000/api/drive/callback
Scope: drive.readonly. Secret/token solo su disco (data/, gitignored).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from googleapiclient.errors import HttpError

from app.agents import drive_import, intake, normalizer, sequence
from app.api.routes import _get_state_or_404, _run_stages
from app.api.schemas import DriveCredentialsRequest, DriveImportRequest, ProjectState
from app.jobs import manager as jobs
from app.pipeline import state as state_store
from app.services import drive_client as dc

router = APIRouter()

DRIVE_HOST = "http://127.0.0.1:8000"


def _drive_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, HttpError):
        return HTTPException(status_code=502, detail=f"Errore Google Drive: {exc}")
    return HTTPException(status_code=500, detail=str(exc))


@router.post("/drive/credentials")
def save_credentials(body: DriveCredentialsRequest) -> dict:
    if not body.client_id.strip() or not body.client_secret.strip():
        raise HTTPException(status_code=400, detail="client_id e client_secret obbligatori")
    dc.save_client_config(body.client_id, body.client_secret)
    dc.disconnect()  # token legato alle vecchie credenziali non piu' valido
    return {"configured": True}


@router.get("/drive/status")
def drive_status() -> dict:
    configured = dc.load_client_config() is not None
    if not configured:
        return {"configured": False, "connected": False, "email": None}
    try:
        service = dc.get_drive_service()
        email = dc.get_account_email(service)
        return {"configured": True, "connected": True, "email": email}
    except Exception:
        return {"configured": True, "connected": False, "email": None}


@router.get("/drive/auth-url")
def drive_auth_url() -> dict:
    try:
        return {"url": dc.get_authorization_url(DRIVE_HOST)}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _callback_page(ok: bool, message: str, status: int = 200) -> HTMLResponse:
    color, title = ("#34d399", "Drive collegato") if ok else ("#f87171", "Errore collegamento")
    close = "<script>setTimeout(function(){try{window.close()}catch(e){}},1500)</script>" if ok else ""
    return HTMLResponse(
        f"<html><body style='background:#0f172a;color:#e2e8f0;font-family:sans-serif;"
        f"display:flex;height:100vh;align-items:center;justify-content:center;text-align:center'>"
        f"<div><h2 style='color:{color}'>{title}</h2><p>{message}</p>"
        f"<p style='color:#64748b;font-size:12px'>Puoi chiudere questa finestra e tornare all'app.</p>"
        f"</div>{close}</body></html>", status_code=status)


@router.get("/drive/callback", response_class=HTMLResponse)
def drive_callback(code: str | None = Query(default=None),
                   state: str | None = Query(default=None)):
    if not code:
        return _callback_page(False, "Autorizzazione negata o codice mancante.", 400)
    try:
        dc.exchange_code_and_save(code, state or "", DRIVE_HOST)
    except Exception as exc:
        return _callback_page(False, f"{exc}", 400)
    return _callback_page(True, "Account collegato con successo.")


@router.post("/drive/disconnect")
def drive_disconnect() -> dict:
    dc.disconnect()
    return {"connected": False}


@router.get("/projects/{project_id}/drive/files")
def drive_files(project_id: str, folder_id: str = "root",
                page_token: str | None = None, page_size: int = 100) -> dict:
    _get_state_or_404(project_id)
    try:
        service = dc.get_drive_service()
        batch = dc.list_children(service, folder_id, page_token, page_size)
        current = {"id": "root", "name": "Il mio Drive"} if folder_id == "root" \
            else dc.get_file_meta(service, folder_id)
    except Exception as exc:
        raise _drive_error(exc) from None
    return {"current": current, "entries": batch["entries"],
            "nextPageToken": batch.get("nextPageToken")}


@router.post("/projects/{project_id}/drive/import", response_model=ProjectState)
async def drive_import_media(project_id: str, body: DriveImportRequest,
                             background: bool = False) -> dict:
    """M7: importa da Drive (cartelle ricorsive + file) poi Intake come da grafo.

    Con background=true accoda un job (202) con progress per-file.
    """
    state = _get_state_or_404(project_id)
    if not body.file_ids and not body.folder_ids:
        raise HTTPException(status_code=400, detail="Seleziona almeno un file o una cartella")
    if dc.load_credentials() is None:
        raise HTTPException(status_code=401,
                            detail="Drive non connesso: completa prima il collegamento OAuth")
    if background:
        try:
            job = jobs.submit(project_id, "drive_import",
                              {"file_ids": body.file_ids, "folder_ids": body.folder_ids})
        except jobs.JobExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return JSONResponse(status_code=202, content={"job": job})
    state["drive_import_request"] = {"file_ids": body.file_ids, "folder_ids": body.folder_ids}
    state = await _run_stages(state, (("drive_import", drive_import.run),
                                      ("intake", intake.run),
                                      ("normalizer", normalizer.run),
                                      ("sequence", sequence.run)))
    state_store.save_state(state)
    return state
