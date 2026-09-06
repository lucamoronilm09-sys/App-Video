"""Client Google Drive: OAuth2 + browse + download (Agente -1b, M7).

Scope minimo: drive.readonly. Le credenziali OAuth (client_id/secret inseriti
una tantum dall'utente) e il token vivono in data/ (gitignored, mai esposti via
API). Tutte le funzioni che toccano la rete prendono un `service` Drive
iniettabile -> test senza rete con service finti.
"""
from __future__ import annotations

import json
import re
import secrets
from collections import deque
from io import FileIO
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.config import DATA_DIR

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
REDIRECT_PATH = "/api/drive/callback"
MAX_IMPORT_ITEMS = 3000
DOWNLOAD_WORKERS = 6

CREDS_PATH = DATA_DIR / "google_credentials.json"
TOKEN_PATH = DATA_DIR / "drive_token.json"
OAUTH_STATE_PATH = DATA_DIR / "drive_oauth_state.json"


def redirect_uri(host: str = "http://127.0.0.1:8000") -> str:
    return f"{host}{REDIRECT_PATH}"


# --- credenziali OAuth (client) ---

def save_client_config(client_id: str, client_secret: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CREDS_PATH.write_text(json.dumps({"client_id": client_id.strip(),
                                      "client_secret": client_secret.strip()}),
                          encoding="utf-8")


def load_client_config() -> dict[str, str] | None:
    if not CREDS_PATH.is_file():
        return None
    try:
        cfg = json.loads(CREDS_PATH.read_text(encoding="utf-8"))
        if cfg.get("client_id") and cfg.get("client_secret"):
            return {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"]}
    except Exception:
        pass
    return None


def _client_config_for_flow(cfg: dict[str, str], host: str) -> dict[str, Any]:
    return {"web": {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri(host)]}}


def build_flow(host: str = "http://127.0.0.1:8000") -> Flow:
    cfg = load_client_config()
    if not cfg:
        raise RuntimeError("Credenziali Google non configurate")
    return Flow.from_client_config(_client_config_for_flow(cfg, host),
                                   scopes=SCOPES, redirect_uri=redirect_uri(host))


def get_authorization_url(host: str = "http://127.0.0.1:8000") -> str:
    """URL consenso Google; salva lo state anti-CSRF lato server."""
    flow = build_flow(host)
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OAUTH_STATE_PATH.write_text(
        json.dumps({"state": state, "code_verifier": flow.code_verifier}),
        encoding="utf-8"
    )
    return url


def exchange_code_and_save(code: str, returned_state: str,
                           host: str = "http://127.0.0.1:8000") -> None:
    try:
        saved_data = json.loads(OAUTH_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        saved_data = {}
    saved_state = saved_data.get("state")
    saved_verifier = saved_data.get("code_verifier")
    if not saved_state or not returned_state or saved_state != returned_state:
        raise ValueError("state OAuth non valido (riprova la connessione)")
    flow = build_flow(host)
    if saved_verifier:
        flow.code_verifier = saved_verifier
    flow.fetch_token(code=code)
    TOKEN_PATH.write_text(flow.credentials.to_json(), encoding="utf-8")
    try:
        OAUTH_STATE_PATH.unlink()
    except OSError:
        pass


def load_credentials() -> Credentials | None:
    """Credenziali salvate (con refresh automatico); None se assenti/revocate."""
    if not TOKEN_PATH.is_file():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception:
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            return None
    if not creds or not creds.valid:
        return None
    return creds


def disconnect() -> None:
    try:
        TOKEN_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def get_drive_service():
    creds = load_credentials()
    if not creds:
        raise RuntimeError("Drive non connesso: completa prima il collegamento OAuth")
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    return build("drive", "v3", credentials=None,
                 http=AuthorizedHttp(creds, http=httplib2.Http(timeout=300)),
                 cache_discovery=False)


def get_account_email(service) -> str | None:
    try:
        about = service.about().get(fields="user(emailAddress)").execute()
        return (about.get("user") or {}).get("emailAddress")
    except Exception:
        return None


# --- browse ---

def is_supported_media(mime: str) -> bool:
    if mime == "image/svg+xml":
        return False
    return mime.startswith("image/") or mime.startswith("video/")


def _safe_id(folder_id: str) -> str:
    if folder_id == "root" or re.fullmatch(r"[\w-]+", folder_id):
        return folder_id
    raise ValueError(f"folder_id non valido: {folder_id}")


def list_children(service, folder_id: str = "root", page_token: str | None = None,
                  page_size: int = 100) -> dict[str, Any]:
    """Figli non cestinati di una cartella: {entries: [{id,name,mimeType,is_folder}], nextPageToken}."""
    fid = _safe_id(folder_id)
    q = f"'{fid}' in parents and trashed=false"
    req = service.files().list(q=q, fields="nextPageToken,files(id,name,mimeType)",
                               orderBy="folder,name", pageSize=max(1, min(page_size, 200)),
                               pageToken=page_token)
    res = req.execute()
    entries = [{"id": f["id"], "name": f.get("name", "?"),
                "mimeType": f.get("mimeType", ""),
                "is_folder": f.get("mimeType") == FOLDER_MIME}
               for f in res.get("files", [])]
    return {"entries": entries, "nextPageToken": res.get("nextPageToken")}


def get_file_meta(service, file_id: str) -> dict[str, Any]:
    res = service.files().get(fileId=file_id,
                              fields="id,name,mimeType").execute()
    return {"id": res["id"], "name": res.get("name", "?"),
            "mimeType": res.get("mimeType", ""),
            "is_folder": res.get("mimeType") == FOLDER_MIME}


def expand_selection(service, file_ids: list[str],
                     folder_ids: list[str]) -> tuple[list[dict], list[dict]]:
    """Espande la selezione: cartelle ricorsive (BFS, nomi ordinati per stabilita').

    Ritorna (media[{id,name,mimeType}], skipped[{id?,name?,reason}]).
    I formati non supportati non bloccano gli altri (architettura sez. 5).
    """
    media: list[dict] = []
    skipped: list[dict] = []
    queue: deque[str] = deque(folder_ids)
    visited: set[str] = set()
    touched = 0

    for fid in file_ids:
        try:
            meta = get_file_meta(service, fid)
        except HttpError as exc:
            skipped.append({"id": fid, "reason": f"non leggibile: {exc}"})
            continue
        if meta["is_folder"]:
            queue.append(meta["id"])
        elif is_supported_media(meta["mimeType"]):
            media.append(meta)
        else:
            skipped.append({"id": meta["id"], "name": meta["name"],
                            "reason": f"formato non supportato ({meta['mimeType']})"})

    while queue:
        fid = queue.popleft()
        if fid in visited:
            continue
        visited.add(fid)
        page = None
        while True:
            batch = list_children(service, fid, page_token=page, page_size=200)
            entries = sorted(batch["entries"], key=lambda e: e["name"].lower())
            for e in entries:
                touched += 1
                if touched > MAX_IMPORT_ITEMS:
                    skipped.append({"reason": f"limite di {MAX_IMPORT_ITEMS} elementi raggiunto"})
                    queue.clear()
                    break
                if e["is_folder"]:
                    queue.append(e["id"])
                elif is_supported_media(e["mimeType"]):
                    media.append(e)
                else:
                    skipped.append({"id": e["id"], "name": e["name"],
                                    "reason": f"formato non supportato ({e['mimeType']})"})
            page = batch.get("nextPageToken")
            if not page:
                break
    return media, skipped


# --- download ---

def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._+() -]", "_", (name or "file").strip())
    base = base[:120] or "file"
    return base


def _execute_download(request, dest: Path) -> int:
    """Download reale via MediaIoBaseDownload (mockabile nei test)."""
    size = 0
    with FileIO(str(dest), "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    size = dest.stat().st_size
    return size


def download_file(service, file_id: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    return _execute_download(request, dest)
