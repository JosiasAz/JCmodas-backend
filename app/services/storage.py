"""Onde ficam as fotos enviadas pelo painel.

- Com BLOB_READ_WRITE_TOKEN (Vercel): Vercel Blob, que devolve um link https público.
- Sem ele (desenvolvimento ou servidor próprio): pasta upload_dir, servida em /static/uploads.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.core.config import settings

BLOB_API = "https://vercel.com/api/blob"
BLOB_API_VERSION = "13"
CONTENT_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
ONE_YEAR = str(365 * 24 * 3600)


def save_image(content: bytes, ext: str) -> str:
    """Grava a imagem (já validada) e devolve a URL usada no catálogo."""
    name = f"{uuid.uuid4().hex}{ext}"
    if settings.blob_read_write_token:
        return _put_blob(f"produtos/{name}", content, CONTENT_TYPES[ext])
    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return f"/static/uploads/{name}"


def _put_blob(pathname: str, content: bytes, content_type: str) -> str:
    token = settings.blob_read_write_token or ""
    # o token tem o formato vercel_blob_rw_<storeId>_<segredo>
    parts = token.split("_")
    store_id = parts[3] if len(parts) > 3 else ""
    request = urllib.request.Request(
        f"{BLOB_API}/?{urllib.parse.urlencode({'pathname': pathname})}",
        data=content,
        method="PUT",
        headers={
            "authorization": f"Bearer {token}",
            "x-api-version": BLOB_API_VERSION,
            "x-vercel-blob-store-id": store_id,
            "x-content-type": content_type,
            "x-vercel-blob-access": "public",
            "x-cache-control-max-age": ONE_YEAR,  # nome aleatório: o arquivo nunca muda
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())["url"]
    except (urllib.error.URLError, KeyError, ValueError):
        raise HTTPException(502, "Não foi possível salvar a imagem agora. Tente novamente.")
