from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

def _make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # o Neon suspende o banco quando ocioso: testa a conexão antes de usar e renova as antigas
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


engine = _make_engine(settings.database_url)
# conexão direta (sem pooler) para create_all/ALTER TABLE; sem ela, usa o mesmo engine
schema_engine = _make_engine(settings.database_url_unpooled) if settings.database_url_unpooled else engine
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate() -> None:
    """Cria tabelas que faltam e adiciona colunas novas em bancos já existentes."""
    import app.models  # noqa: F401  registra todas as tabelas no Base.metadata

    Base.metadata.create_all(schema_engine)
    inspector = inspect(schema_engine)
    with schema_engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl_type = column.type.compile(dialect=schema_engine.dialect)
                default = column.server_default.arg if column.server_default is not None else None
                if default is None and not column.nullable:
                    # coluna obrigatória sem padrão: usa um valor neutro para as linhas antigas
                    default = "0" if ddl_type.upper().startswith(("INT", "BOOL", "FLOAT", "NUMERIC", "DOUBLE", "REAL")) else ""
                clause = ""
                if default is not None:
                    if ddl_type.upper().startswith("BOOL") and schema_engine.dialect.name == "postgresql":
                        default = "false" if str(default) in ("0", "false") else "true"
                    literal = default if str(default).replace(".", "", 1).isdigit() or default in ("true", "false") else f"'{default}'"
                    clause = f" DEFAULT {literal}" + ("" if column.nullable else " NOT NULL")
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl_type}{clause}'))
