import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

# OWASP (2023) recomenda 600 mil iterações para PBKDF2-HMAC-SHA256
_ITERATIONS = 600_000
# hashes antigos ("salt$digest") foram gerados com 240 mil e são atualizados no próximo login
_LEGACY_ITERATIONS = 240_000
_PREFIX = "pbkdf2_sha256"


def _pbkdf2(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    return f"{_PREFIX}${_ITERATIONS}${salt}${_pbkdf2(password, salt, _ITERATIONS)}"


def _parse(stored: str) -> tuple[int, str, str]:
    parts = stored.split("$")
    if len(parts) == 4 and parts[0] == _PREFIX:
        return int(parts[1]), parts[2], parts[3]
    salt, digest = stored.split("$", 1)
    return _LEGACY_ITERATIONS, salt, digest


def verify_password(password: str, stored: str) -> bool:
    iterations, salt, digest = _parse(stored)
    return hmac.compare_digest(_pbkdf2(password, salt, iterations), digest)


def needs_rehash(stored: str) -> bool:
    return _parse(stored)[0] < _ITERATIONS


# ---------------------------------------------------------------- tokens

SESSION = "session"  # acesso ao painel
MFA = "mfa"  # senha conferida, falta o código da verificação em duas etapas


def create_token(user_id: int, version: int, scope: str = SESSION, minutes: int | None = None) -> str:
    """`version` = User.token_version. Trocar a senha ou sair muda a versão e derruba os tokens antigos."""
    lifetime = timedelta(minutes=minutes) if minutes else timedelta(hours=settings.token_expire_hours)
    payload = {"sub": str(user_id), "ver": version, "scope": scope, "exp": datetime.now(UTC) + lifetime}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str, scope: str = SESSION) -> tuple[int, int] | None:
    """Devolve (id do usuário, versão do token) ou None se inválido, expirado ou de outro escopo."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("scope", SESSION) != scope:
            return None
        return int(payload["sub"]), int(payload.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
