from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.core import google, totp
from app.core.config import settings
from app.core.deps import DB, Admin
from app.core.rate_limit import RateLimiter, client_ip, too_many
from app.core.security import MFA, create_token, decode_token, hash_password, needs_rehash, verify_password
from app.models import User
from app.schemas.store import GoogleLoginIn, LoginIn, LoginOut, MfaLoginIn
from app.services.audit import record, security_event

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])

# contra força bruta:
#  - 10 tentativas/min por IP;
#  - 5 senhas erradas para o mesmo e-mail a partir do mesmo IP bloqueiam esse par por 15 min
#    (um atacante não consegue mais trancar o dono para fora só errando a senha de outro lugar);
#  - 20 erros para o mesmo e-mail vindos de qualquer lugar bloqueiam por 1 h (ataque distribuído).
_login_per_ip = RateLimiter(10, 60)
_fail_pair = RateLimiter(5, 15 * 60)
_fail_email = RateLimiter(20, 60 * 60)
_mfa_fail = RateLimiter(5, 15 * 60)
# hash usado quando o e-mail não existe, para a resposta levar o mesmo tempo (não revela quem tem conta)
_DUMMY_HASH = hash_password("senha-inexistente")
MFA_TOKEN_MINUTES = 5


def _session(user: User, request: Request) -> LoginOut:
    record("login", request=request, user_id=user.id, user_email=user.email, entity="users", entity_id=user.id)
    security_event("login_ok", request, user=user.email)
    return LoginOut(
        access_token=create_token(user.id, user.token_version),
        name=user.name,
        mfa_enabled=user.mfa_enabled,
        mfa_setup_required=settings.enforce_mfa and not user.mfa_enabled,
    )


@router.post("/login", response_model=LoginOut)
def login(data: LoginIn, db: DB, request: Request):
    email = data.email.lower()
    pair = f"{client_ip(request)}|{email}"
    retry = _login_per_ip.hit(client_ip(request)) or _fail_pair.blocked(pair) or _fail_email.blocked(email)
    if retry:
        security_event("login_blocked", request, user=email)
        raise too_many(retry, "Muitas tentativas de login. Aguarde alguns minutos.")

    user = db.scalar(select(User).where(User.email == email))
    valid = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not valid:
        _fail_pair.hit(pair)
        _fail_email.hit(email)
        record("login_falhou", request=request, user_email=email, entity="users",
               summary="senha incorreta" if user else "e-mail não cadastrado")
        security_event("login_fail", request, user=email)
        raise HTTPException(401, "E-mail ou senha incorretos")

    _fail_pair.reset(pair)
    if needs_rehash(user.password_hash):  # hash antigo (240 mil iterações) vira o atual
        user.password_hash = hash_password(data.password)
        db.commit()
    return _after_credentials(user, request)


def _after_credentials(user: User, request: Request) -> LoginOut:
    """Senha ou conta Google conferida: com verificação em duas etapas ainda falta o código."""
    if user.mfa_enabled:
        return LoginOut(
            name=user.name,
            mfa_required=True,
            mfa_token=create_token(user.id, user.token_version, scope=MFA, minutes=MFA_TOKEN_MINUTES),
            mfa_enabled=True,
        )
    return _session(user, request)


@router.get("/google")
def google_config():
    """ID do cliente para o botão "Entrar com Google" (null = recurso desligado)."""
    return {"client_id": settings.google_client_id}


@router.post("/google", response_model=LoginOut)
def login_google(data: GoogleLoginIn, db: DB, request: Request):
    """Entrar com a conta Google. Não cria conta: o e-mail precisa ser de um administrador já cadastrado."""
    if not settings.google_client_id:
        raise HTTPException(404, "Login com Google não está ativado")
    retry = _login_per_ip.hit(client_ip(request))
    if retry:
        security_event("login_blocked", request)
        raise too_many(retry, "Muitas tentativas de login. Aguarde alguns minutos.")

    claims = google.verify_id_token(data.credential)
    if not claims:
        security_event("login_fail", request)
        raise HTTPException(401, "Não foi possível confirmar a conta Google. Tente de novo.")
    email = claims["email"].lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_admin:
        record("login_falhou", request=request, user_email=email, entity="users",
               summary="conta Google sem acesso ao painel")
        security_event("login_fail", request, user=email)
        raise HTTPException(401, "Esta conta Google não tem acesso ao painel")
    return _after_credentials(user, request)


@router.post("/mfa", response_model=LoginOut)
def login_mfa(data: MfaLoginIn, db: DB, request: Request):
    """Segunda etapa: código do app autenticador ou um código de recuperação."""
    decoded = decode_token(data.mfa_token, scope=MFA)
    user = db.get(User, decoded[0]) if decoded else None
    if not user or user.token_version != decoded[1] or not user.mfa_enabled:
        raise HTTPException(401, "Sessão expirada. Entre com a senha de novo.")
    key = str(user.id)
    retry = _login_per_ip.hit(client_ip(request)) or _mfa_fail.blocked(key)
    if retry:
        raise too_many(retry, "Muitas tentativas. Aguarde alguns minutos.")

    step = totp.verify(user.mfa_secret or "", data.code, user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
    else:
        hashed = totp.hash_recovery_code(data.code)
        if hashed not in (user.mfa_recovery or []):
            _mfa_fail.hit(key)
            record("mfa_falhou", request=request, user_id=user.id, user_email=user.email, entity="users")
            security_event("mfa_fail", request, user=user.email)
            raise HTTPException(401, "Código inválido")
        # código de recuperação só vale uma vez
        user.mfa_recovery = [h for h in user.mfa_recovery if h != hashed]
        record("codigo_recuperacao_usado", request=request, user_id=user.id, user_email=user.email,
               entity="users", summary=f"restam {len(user.mfa_recovery)} códigos")
    db.commit()
    _mfa_fail.reset(key)
    return _session(user, request)


@router.post("/logout", status_code=204)
def logout(admin: Admin, db: DB, request: Request):
    """Encerra a sessão em todos os aparelhos (o token atual e os antigos deixam de valer)."""
    admin.token_version += 1
    db.commit()
    record("logout", request=request, user_id=admin.id, user_email=admin.email, entity="users", entity_id=admin.id)


@router.get("/me")
def me(admin: Admin):
    return {
        "id": admin.id,
        "name": admin.name,
        "email": admin.email,
        "mfa_enabled": admin.mfa_enabled,
        "mfa_setup_required": settings.enforce_mfa and not admin.mfa_enabled,
    }
