"""Configurazione centralizzata del backend AI Video Maker."""
from pathlib import Path

# backend/app/config.py -> repo root = parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

DATA_DIR = REPO_ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"
MEDIA_SUBDIR = "media"      # dentro la cartella di un progetto
AUDIO_SUBDIR = "audio"
OUTPUT_SUBDIR = "output"
THUMBS_SUBDIR = "thumbs"    # anteprime leggere (cache, M-polish)

# output_spec di default (vedi Project State nel documento di architettura)
DEFAULT_OUTPUT_SPEC: dict = {
    "resolution": "1920x1080",
    "fps": 30,
    "background_fill": "blur",
    "vcodec": "h264",
}
DEFAULT_STYLE_PROFILE = "album_memory"

# Permettiamo di correggere il PATH utente se node/ffmpeg sono portabili
# (installati in C:\Users\Marco\Tools). L'agente Render/Timeline li usera'
# da M4 in poi; qui serve solo che il PATH includa la cartella Tools.
TOOLS_DIR = Path.home() / "Tools"
