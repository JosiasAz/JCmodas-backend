"""Onde ficam as fotos enviadas pelo painel.

- Na Vercel: Vercel Blob, que devolve um link https público. Stores novos usam BLOB_STORE_ID +
  o token OIDC que a Vercel injeta na requisição; stores antigos usam BLOB_READ_WRITE_TOKEN.
- Fora dela (desenvolvimento ou servidor próprio): pasta upload_dir, servida em /static/uploads.
"""
import json
import logging
import os
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


def _blob_credentials(oidc_token: str | None) -> tuple[str, str] | None:
    """(token, id do store) para o Vercel Blob, ou None se o Blob não estiver configurado."""
    oidc_token = (oidc_token or os.environ.get("VERCEL_OIDC_TOKEN") or "").strip()
    if settings.blob_store_id and oidc_token:
        return oidc_token, settings.blob_store_id.strip().removeprefix("store_")
    if settings.blob_read_write_token:
        # formato vercel_blob_rw_<storeId>_<segredo>
        parts = settings.blob_read_write_token.split("_")
        return settings.blob_read_write_token, parts[3] if len(parts) > 3 else ""
    return None


def save_image(content: bytes, ext: str, oidc_token: str | None = None) -> str:
    """Grava a imagem (já validada) e devolve a URL usada no catálogo."""
    name = f"{uuid.uuid4().hex}{ext}"
    credentials = _blob_credentials(oidc_token)
    if credentials:
        return _put_blob(f"produtos/{name}", content, CONTENT_TYPES[ext], *credentials)
    if settings.vercel:
        raise HTTPException(503, "Armazenamento de imagens não configurado (Vercel Blob).")
    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return f"/static/uploads/{name}"


def _put_blob(pathname: str, content: bytes, content_type: str, token: str, store_id: str) -> str:
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
    except urllib.error.HTTPError as err:
        detail = err.read()[:300].decode("utf-8", "replace")
        logging.getLogger("jc.security").error(
            json.dumps({"event": "blob_upload_failed", "status": err.code, "detail": detail})
        )
        raise HTTPException(502, "Não foi possível salvar a imagem agora. Tente novamente.")
    except (urllib.error.URLError, KeyError, ValueError):
        raise HTTPException(502, "Não foi possível salvar a imagem agora. Tente novamente.")
