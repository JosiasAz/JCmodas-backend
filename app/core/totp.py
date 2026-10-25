"""Verificação em duas etapas (TOTP, RFC 6238): o código de 6 dígitos dos apps autenticadores
(Google Authenticator, Microsoft Authenticator, Authy...). Implementado sem dependências externas."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # aceita o código anterior e o próximo (relógio do celular um pouco fora)


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now or time.time()) // STEP_SECONDS)


def verify(secret: str, code: str, last_step: int = 0) -> int | None:
    """Confere o código. Devolve o passo usado (para impedir reuso do mesmo código) ou None."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = current_step()
    for step in range(now - WINDOW, now + WINDOW + 1):
        if step > last_step and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str, issuer: str = "JC Moda") -> str:
    """Link otpauth:// que os apps autenticadores entendem (abrir no celular ou digitar a chave)."""
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"


# ---------------------------------------------------------------- códigos de recuperação

def new_recovery_codes(count: int = 8) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)) for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    # códigos aleatórios de alta entropia: SHA-256 basta (não são senhas escolhidas por pessoas)
    return hashlib.sha256(code.strip().upper().replace(" ", "").encode()).hexdigest()
