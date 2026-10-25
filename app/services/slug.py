import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"


def unique_slug(db: Session, model, text: str, current_id: int | None = None) -> str:
    """Gera um slug que ainda não existe na tabela (camisa-polo, camisa-polo-2, ...)."""
    base = slugify(text)
    slug, n = base, 2
    while True:
        found = db.scalar(select(model.id).where(model.slug == slug))
        if found is None or found == current_id:
            return slug
        slug, n = f"{base}-{n}", n + 1
