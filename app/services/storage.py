"""Fotos enviadas pelo painel.

A cópia que vale fica no banco (tabela stored_files): se o disco do servidor se perder, nada some.
A pasta upload_dir é só cache, servida em /static/uploads e recriada a partir do banco quando falta.
"""
import logging
import re
import uuid
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import StoredFile

THUMB_WIDTHS = (400, 800, 1200)
FILE_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp|gif)")  # só o nome que save_image gera: nada de "../"
log = logging.getLogger("app.storage")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")  # dois pedidos ao mesmo tempo não deixam arquivo pela metade
    tmp.write_bytes(content)
    tmp.replace(path)


def save_image(content: bytes, ext: str) -> str:
    """Grava a imagem (já validada) no banco e no cache em disco; devolve a URL usada no catálogo."""
    name = f"{uuid.uuid4().hex}{ext}"
    with SessionLocal() as db:
        db.add(StoredFile(name=name, data=content))
        db.commit()
    _write(Path(settings.upload_dir) / name, content)
    return f"/static/uploads/{name}"


def local_file(name: str) -> Path | None:
    """Caminho da foto no disco; se o cache não tem, busca no banco e grava."""
    if not FILE_NAME.fullmatch(name):
        return None
    path = Path(settings.upload_dir) / name
    if not path.is_file():
        with SessionLocal() as db:
            data = db.scalar(select(StoredFile.data).where(StoredFile.name == name))
        if data is None:
            return None
        _write(path, data)
    return path


def remove_cached(name: str) -> None:
    """Apaga a foto e as miniaturas do disco (senão import_disk_files a traria de volta ao banco)."""
    folder = Path(settings.upload_dir)
    (folder / name).unlink(missing_ok=True)
    for width in THUMB_WIDTHS:
        (folder / "thumbs" / str(width) / f"{Path(name).stem}.webp").unlink(missing_ok=True)


def import_disk_files() -> int:
    """Copia para o banco as fotos que só existem no disco (as enviadas antes de as fotos irem para o banco)."""
    folder = Path(settings.upload_dir)
    if not folder.is_dir():
        return 0
    with SessionLocal() as db:
        known = set(db.scalars(select(StoredFile.name)))
        added = 0
        for path in folder.iterdir():
            if path.is_file() and FILE_NAME.fullmatch(path.name) and path.name not in known:
                db.add(StoredFile(name=path.name, data=path.read_bytes()))
                db.commit()  # uma por vez: uma foto com problema não impede as outras
                added += 1
    if added:
        log.info("%d foto(s) do disco copiadas para o banco", added)
    return added


def thumbnail(name: str, width: int) -> Path | None:
    """Versão WebP da foto com essa largura, para a vitrine não baixar a foto inteira num cartão pequeno.

    Gerada na primeira vez que alguém pede e guardada em upload_dir/thumbs (cache: dá para apagar).
    """
    if width not in THUMB_WIDTHS:
        return None
    original = local_file(name)
    if original is None:
        return None
    out = Path(settings.upload_dir) / "thumbs" / str(width) / f"{original.stem}.webp"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(original) as img:
            img.thumbnail((width, width * 4))  # nunca aumenta; só a largura limita
            img = img.convert("RGBA" if img.has_transparency_data else "RGB")
            tmp = out.with_suffix(f".{uuid.uuid4().hex}.tmp")
            img.save(tmp, "WEBP", quality=80)
            tmp.replace(out)
    return out
