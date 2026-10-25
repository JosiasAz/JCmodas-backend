from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models import User

DB = Annotated[Session, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False)

# rotas liberadas para quem ainda precisa ativar a verificação em duas etapas
MFA_SETUP_PATHS = ("/api/admin/me/mfa", "/api/auth/me", "/api/auth/logout")
MFA_SETUP_REQUIRED = "Ative a verificação em duas etapas para usar o painel"


def get_admin(
    request: Request,
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    decoded = decode_token(credentials.credentials) if credentials else None
    user = db.get(User, decoded[0]) if decoded else None
    # usuário removido, sem permissão, ou que trocou a senha / saiu depois de gerar este token
    if not user or not user.is_admin or user.token_version != decoded[1]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login como administrador")
    if settings.enforce_mfa and not user.mfa_enabled and not request.url.path.startswith(MFA_SETUP_PATHS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, MFA_SETUP_REQUIRED)
    # o middleware de auditoria usa para saber quem fez a alteração
    request.state.admin = (user.id, user.email)
    return user


Admin = Annotated[User, Depends(get_admin)]
