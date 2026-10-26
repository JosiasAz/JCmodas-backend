import jwt

from app.core.config import settings

# chaves públicas do Google; o PyJWKClient guarda em cache e só busca de novo quando aparece uma chave nova
_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]
_jwks = jwt.PyJWKClient(_CERTS_URL, cache_keys=True, timeout=10)


def verify_id_token(credential: str) -> dict | None:
    """Confere o ID token do botão "Entrar com Google": assinatura, validade, emissor e destinatário (este site).

    Devolve os dados da conta ou None se o token for inválido ou o e-mail não estiver confirmado no Google.
    """
    if not settings.google_client_id:
        return None
    try:
        key = _jwks.get_signing_key_from_jwt(credential)
        claims = jwt.decode(
            credential,
            key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=_ISSUERS,
            options={"require": ["exp", "iat", "aud", "iss", "sub", "email"]},
        )
    except (jwt.PyJWTError, ValueError):
        return None
    if claims.get("email_verified") is not True:
        return None
    return claims
