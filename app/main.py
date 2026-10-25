import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import Base, SessionLocal, migrate, schema_engine
from app.routers import admin_catalog, admin_marketing, admin_orders, admin_users, auth, store
from app.seed import seed_if_empty
from app.services.audit import record, security_log
from app.services.orders import expire_pending_orders

settings.check_production()

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


EXPIRE_EVERY_SECONDS = 10 * 60


def _expire_once() -> None:
    with SessionLocal() as db:
        expire_pending_orders(db)


async def _expire_loop() -> None:
    """Cancela pedidos não pagos vencidos a cada 10 min (o estoque volta para a loja)."""
    while True:
        try:
            await asyncio.to_thread(_expire_once)
        except Exception:  # noqa: BLE001 - nunca derruba a API
            security_log.exception("falha ao expirar pedidos")
        await asyncio.sleep(EXPIRE_EVERY_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(schema_engine)
    migrate()
    seed_if_empty()
    task = asyncio.create_task(_expire_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="JC Moda Masculina - API",
    version="1.0.0",
    lifespan=lifespan,
    # documentação interativa só em desenvolvimento (em produção ela expõe o mapa da API)
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


ACTIONS = {"POST": "criou", "PUT": "alterou", "PATCH": "alterou", "DELETE": "excluiu"}


@app.middleware("http")
async def audit_admin_changes(request: Request, call_next):
    """Registra na trilha de auditoria toda alteração bem-sucedida feita no painel.

    O corpo da requisição não é gravado (pode ter senha ou dados de clientes); as rotas podem
    descrever a mudança em `request.state.audit_summary`.
    """
    response = await call_next(request)
    path = request.url.path
    admin = getattr(request.state, "admin", None)
    if request.method in ACTIONS and path.startswith("/api/admin/") and response.status_code < 400 and admin:
        parts = path.removeprefix("/api/admin/").split("/")
        entity_id = next((p for p in parts[1:] if p.isdigit()), "")
        summary = getattr(request.state, "audit_summary", "")
        await run_in_threadpool(
            record, ACTIONS[request.method], request=request, user_id=admin[0], user_email=admin[1],
            entity=parts[0], entity_id=entity_id, summary=summary,
        )
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers["X-Content-Type-Options"] = "nosniff"  # navegador não "adivinha" o tipo do arquivo
    headers["X-Frame-Options"] = "DENY"  # ninguém embute a API/imagens em iframe
    headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not request.url.path.startswith(DOCS_PATHS):
        # respostas da API e imagens nunca executam script, mesmo se abertas direto no navegador
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    if settings.is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


for module in (store, auth, admin_catalog, admin_marketing, admin_orders, admin_users):
    app.include_router(module.router)


@app.get("/api/health", tags=["Sistema"])
def health():
    return {"status": "ok"}


# fotos enviadas pelo painel, gravadas no disco do servidor
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
