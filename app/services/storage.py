"""Onde ficam as fotos enviadas pelo painel: pasta upload_dir do servidor, servida em /static/uploads.

Faça backup dessa pasta (as fotos não ficam no banco).
"""
import uuid
from pathlib import Path

from PIL import Image

from app.core.config import settings

THUMB_WIDTHS = (400, 800, 1200)


def save_image(content: bytes, ext: str) -> str:
    """Grava a imagem (já validada) e devolve a URL usada no catálogo."""
    name = f"{uuid.uuid4().hex}{ext}"
    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return f"/static/uploads/{name}"


def thumbnail(name: str, width: int) -> Path | None:
    """Versão WebP da foto com essa largura, para a vitrine não baixar a foto inteira num cartão pequeno.

    Gerada na primeira vez que alguém pede e guardada em upload_dir/thumbs (vale também para fotos antigas).
    """
    original = Path(settings.upload_dir) / name
    if width not in THUMB_WIDTHS or not original.is_file():
        return None
    out = Path(settings.upload_dir) / "thumbs" / str(width) / f"{original.stem}.webp"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(original) as img:
            img.thumbnail((width, width * 4))  # nunca aumenta; só a largura limita
            img = img.convert("RGBA" if img.has_transparency_data else "RGB")
            tmp = out.with_suffix(f".{uuid.uuid4().hex}.tmp")  # dois pedidos ao mesmo tempo não deixam arquivo pela metade
            img.save(tmp, "WEBP", quality=80)
            tmp.replace(out)
    return out
