"""Painel: quem tem acesso ao painel, troca da própria senha, verificação em duas etapas e atividades."""
import math

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from app.core import totp
from app.core.deps import DB, Admin
from app.core.security import create_token, hash_password, verify_password
from app.models import AuditLog, User
from app.schemas.store import (
    AuditPage,
    MfaCodeIn,
    MfaDisableIn,
    MfaEnabledOut,
    MfaSetupOut,
    PasswordChange,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/api/admin", tags=["Painel - Usuários"])


def _out(user: User, me: User) -> UserOut:
    return UserOut.model_validate(user).model_copy(update={"is_me": user.id == me.id})


def _email_taken(db, email: str, except_id: int | None = None) -> bool:
    query = select(User.id).where(User.email == email)
    if except_id:
        query = query.where(User.id != except_id)
    return db.scalar(query) is not None


def _get(db, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Usuário não encontrado")
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, me: Admin):
    return [_out(u, me) for u in db.scalars(select(User).order_by(User.name))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: DB, me: Admin, request: Request):
    email = data.email.lower()
    if _email_taken(db, email):
        raise HTTPException(400, "Já existe um usuário com esse e-mail")
    user = User(name=data.name.strip(), email=email, password_hash=hash_password(data.password), is_admin=True)
    db.add(user)
    db.commit()
    request.state.audit_summary = f"acesso criado para {email}"
    return _out(user, me)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: DB, me: Admin, request: Request):
    user = _get(db, user_id)
    email = data.email.lower()
    if _email_taken(db, email, user.id):
        raise HTTPException(400, "Já existe um usuário com esse e-mail")
    changes = []
    user.name, user.email = data.name.strip(), email
    if data.password:
        if user.id == me.id:
            raise HTTPException(400, "Para trocar a sua senha, use 'Alterar minha senha'")
        user.password_hash = hash_password(data.password)
        user.token_version += 1  # derruba as sessões abertas dessa pessoa
        changes.append("senha redefinida")
    if data.reset_mfa:
        if user.id == me.id:
            raise HTTPException(400, "Para desativar a sua verificação, use a seção da sua conta")
        user.mfa_enabled, user.mfa_secret, user.mfa_recovery = False, None, []
        user.token_version += 1
        changes.append("verificação em duas etapas desativada")
    db.commit()
    request.state.audit_summary = f"{email}: " + (", ".join(changes) or "dados alterados")
    return _out(user, me)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: DB, me: Admin, request: Request):
    user = _get(db, user_id)
    if user.id == me.id:
        raise HTTPException(400, "Você não pode remover o seu próprio acesso")
    if db.scalar(select(func.count()).select_from(User).where(User.is_admin)) <= 1:
        raise HTTPException(400, "A loja precisa ter pelo menos um administrador")
    request.state.audit_summary = f"acesso removido de {user.email}"
    db.delete(user)  # o token dele deixa de valer na hora: get_admin não encontra mais o usuário
    db.commit()


@router.post("/me/password", response_model=TokenOut)
def change_my_password(data: PasswordChange, db: DB, me: Admin, request: Request):
    if not verify_password(data.current_password, me.password_hash):
        raise HTTPException(400, "Senha atual incorreta")
    me.password_hash = hash_password(data.new_password)
    me.token_version += 1  # encerra a sessão em outros aparelhos
    db.commit()
    request.state.audit_summary = "trocou a própria senha"
    # devolve um token novo para quem trocou continuar logado neste aparelho
    return TokenOut(access_token=create_token(me.id, me.token_version), name=me.name)


# ---------------------------------------------------------------- verificação em duas etapas


@router.get("/me/mfa")
def mfa_status(me: Admin):
    return {"enabled": me.mfa_enabled, "recovery_left": len(me.mfa_recovery or [])}


@router.post("/me/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(db: DB, me: Admin):
    """Gera a chave para cadastrar no app autenticador. Só vale depois de confirmada com um código."""
    if me.mfa_enabled:
        raise HTTPException(400, "A verificação em duas etapas já está ativa")
    me.mfa_secret = totp.new_secret()
    db.commit()
    return MfaSetupOut(secret=me.mfa_secret, otpauth_uri=totp.provisioning_uri(me.mfa_secret, me.email))


@router.post("/me/mfa/enable", response_model=MfaEnabledOut)
def mfa_enable(data: MfaCodeIn, db: DB, me: Admin, request: Request):
    if me.mfa_enabled:
        raise HTTPException(400, "A verificação em duas etapas já está ativa")
    step = totp.verify(me.mfa_secret or "", data.code) if me.mfa_secret else None
    if step is None:
        raise HTTPException(400, "Código incorreto. Confira o horário do celular e tente de novo.")
    codes = totp.new_recovery_codes()
    me.mfa_enabled, me.mfa_last_step = True, step
    me.mfa_recovery = [totp.hash_recovery_code(c) for c in codes]
    me.token_version += 1  # outras sessões abertas sem MFA são encerradas
    db.commit()
    request.state.audit_summary = "ativou a verificação em duas etapas"
    # os códigos de recuperação só são mostrados agora; no banco ficam apenas os hashes
    return MfaEnabledOut(recovery_codes=codes, access_token=create_token(me.id, me.token_version))


@router.post("/me/mfa/disable", response_model=TokenOut)
def mfa_disable(data: MfaDisableIn, db: DB, me: Admin, request: Request):
    if not me.mfa_enabled:
        raise HTTPException(400, "A verificação em duas etapas não está ativa")
    if not verify_password(data.password, me.password_hash):
        raise HTTPException(400, "Senha incorreta")
    if totp.verify(me.mfa_secret or "", data.code, me.mfa_last_step) is None:
        raise HTTPException(400, "Código incorreto")
    me.mfa_enabled, me.mfa_secret, me.mfa_recovery = False, None, []
    me.token_version += 1
    db.commit()
    request.state.audit_summary = "desativou a verificação em duas etapas"
    return TokenOut(access_token=create_token(me.id, me.token_version), name=me.name)


# ---------------------------------------------------------------- atividades (auditoria)


@router.get("/audit", response_model=AuditPage)
def audit_log(
    db: DB,
    _: Admin,
    q: str | None = Query(None, max_length=80),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    query = select(AuditLog)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            AuditLog.user_email.ilike(like) | AuditLog.summary.ilike(like)
            | AuditLog.action.ilike(like) | AuditLog.entity.ilike(like)
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return AuditPage(items=items, total=total, page=page, pages=max(1, math.ceil(total / page_size)))
