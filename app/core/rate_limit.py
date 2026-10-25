"""Limite de requisições por IP (janela deslizante, em memória).

Suficiente para uma loja rodando em um único processo. Com vários workers/servidores (ou na
Vercel, onde cada instância tem a sua memória), troque o armazenamento por Redis para o limite
valer entre todos.
Atrás de proxy (Nginx), rode o uvicorn com --proxy-headers para o IP real do cliente chegar aqui.
"""
import json
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _clean(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)
            hits = self._hits[key]
        return hits

    def hit(self, key: str) -> int | None:
        """Registra uma tentativa. Devolve None se liberado ou os segundos até liberar."""
        now = time.monotonic()
        with self._lock:
            hits = self._clean(key, now)
            if len(hits) >= self.limit:
                return int(hits[0] + self.window - now) + 1
            hits.append(now)
            return None

    def blocked(self, key: str) -> int | None:
        """Só consulta, sem contar tentativa."""
        now = time.monotonic()
        with self._lock:
            hits = self._clean(key, now)
            if len(hits) >= self.limit:
                return int(hits[0] + self.window - now) + 1
            return None

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def too_many(retry_after: int, message: str = "Muitas tentativas. Aguarde um pouco e tente novamente."):
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message, headers={"Retry-After": str(retry_after)})


def client_ip(request: Request) -> str:
    # na Vercel o IP do cliente vem em x-real-ip, preenchido pela própria plataforma (o cliente
    # não consegue forjar); fora dela o cabeçalho é ignorado, senão qualquer um trocaria de IP
    if settings.vercel and (real_ip := request.headers.get("x-real-ip")):
        return real_ip
    return request.client.host if request.client else "desconhecido"


def limit(max_requests: int, window_seconds: int):
    """Dependência do FastAPI: `dependencies=[Depends(limit(5, 60))]`."""
    limiter = RateLimiter(max_requests, window_seconds)

    def dependency(request: Request) -> None:
        # molde da rota (/api/orders/{code}), não a URL: trocar o código não zera o limite
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        retry = limiter.hit(f"{client_ip(request)}:{path}")
        if retry:
            logging.getLogger("jc.security").info(
                json.dumps({"event": "rate_limited", "ip": client_ip(request), "path": path})
            )
            raise too_many(retry)

    return dependency
