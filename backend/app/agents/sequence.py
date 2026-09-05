"""Agente 2a: Sequence (architettura sez. 5).

Rispetta SEMPRE l'ordine manuale dell'utente (order_index): non riordina mai.
- Foto: durata base deterministica in [3.5, 5.5]s, derivata dall'hash del media id
  (ritmo naturale non uniforme + idempotenza: stesso progetto = stesse durate).
- Video: durata originale; se > MAX_VIDEO_SEC, trim centrale (trim_start/end_sec),
  altrimenti nessun trim.

Tocca solo i campi durata/trim dei media (disgiunti da Normalizer e Audio).
Idempotente: riesecuzioni successive danno lo stesso risultato.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

PHOTO_MIN_SEC = 3.5
PHOTO_MAX_SEC = 5.5
MAX_VIDEO_SEC = 8.0


def photo_duration(media_id: str) -> float:
    """Durata deterministica in [3.5, 5.5]s dall'hash dell'id (2 decimali)."""
    seed = hashlib.sha256(media_id.encode("utf-8")).digest()
    rng = random.Random(seed)
    return round(rng.uniform(PHOTO_MIN_SEC, PHOTO_MAX_SEC), 2)


async def run(project_state: dict) -> dict:
    media_list: list[dict[str, Any]] = project_state.get("media", [])
    for item in media_list:
        if item.get("type") == "photo":
            item["duration_sec"] = photo_duration(str(item.get("id", "")))
            item["trim_start_sec"] = None
            item["trim_end_sec"] = None
        else:  # video: mantiene la durata, eventuale trim centrale
            dur = float(item.get("duration_sec") or 0.0)
            if dur > MAX_VIDEO_SEC:
                start = round((dur - MAX_VIDEO_SEC) / 2.0, 2)
                item["trim_start_sec"] = start
                item["trim_end_sec"] = round(start + MAX_VIDEO_SEC, 2)
            else:
                item["trim_start_sec"] = None
                item["trim_end_sec"] = None
    return project_state
