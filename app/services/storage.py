"""Onde ficam as fotos enviadas pelo painel: pasta upload_dir do servidor, servida em /static/uploads.

Faça backup dessa pasta (as fotos não ficam no banco).
"""
import uuid
from pathlib import Path

from app.core.config import settings


def save_image(content: bytes, ext: str) -> str:
    """Grava a imagem (já validada) e devolve a URL usada no catálogo."""
    name = f"{uuid.uuid4().hex}{ext}"
    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return f"/static/uploads/{name}"
