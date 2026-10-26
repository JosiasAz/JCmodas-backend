from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "dev-secret-troque-em-producao-com-uma-chave-longa"
DEFAULT_ADMIN_PASSWORD = "admin123"


class Settings(BaseSettings):
    # .env.local (gerado pelo `neon`) tem prioridade sobre o .env; vale o da pasta acima ou o daqui
    model_config = SettingsConfigDict(env_file=(".env", "../.env.local", ".env.local"), extra="ignore")

    # em "production" a API se recusa a subir com chave/senha padrão e esconde o /docs
    environment: Literal["development", "production"] = "development"

    # Neon: DATABASE_URL passa pelo pooler (uso normal da API); DATABASE_URL_UNPOOLED é a conexão
    # direta, usada para criar/alterar tabelas
    database_url: str = "sqlite:///./jcmoda.db"
    database_url_unpooled: str | None = None
    secret_key: str = DEFAULT_SECRET
    # sessão curta: um token roubado vale por pouco tempo (V-003)
    token_expire_hours: int = 4
    cors_origins: list[str] = ["http://localhost:4200"]
    upload_dir: str = "static/uploads"

    # usuário administrador criado no primeiro start. Depois de criado, apague ADMIN_PASSWORD do .env.
    admin_email: str = "admin@jcmoda.com"
    admin_password: str | None = None

    # gerado pelo `neon` no .env.local: protege a branch de produção contra comandos destrutivos
    neon_branch: str | None = None

    # verificação em duas etapas obrigatória para entrar no painel (sempre ligada em produção)
    mfa_required: bool = False

    # "Entrar com Google" no painel: ID do cliente OAuth (Google Cloud > Credenciais).
    # Vazio = botão escondido. Só entra quem já é administrador com o mesmo e-mail.
    google_client_id: str | None = None

    @field_validator("database_url", "database_url_unpooled")
    @classmethod
    def use_psycopg(cls, url: str | None) -> str | None:
        """postgresql://... vira postgresql+psycopg://... (driver psycopg 3)."""
        if url:
            for prefix in ("postgres://", "postgresql://"):
                if url.startswith(prefix):
                    return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def enforce_mfa(self) -> bool:
        return self.mfa_required or self.is_production

    @property
    def points_to_production_db(self) -> bool:
        return self.is_production or (self.neon_branch or "").lower() in ("production", "main")

    def check_production(self) -> None:
        """Impede publicar a loja com valores de exemplo."""
        if not self.is_production:
            return
        problems = []
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL não definida (use a conexão do Neon no .env do servidor)")
        if self.secret_key == DEFAULT_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY padrão ou curta (use 32+ caracteres aleatórios)")
        if self.admin_password == DEFAULT_ADMIN_PASSWORD:
            problems.append("ADMIN_PASSWORD padrão (troque ou, se o admin já existe, apague a linha)")
        if any(o.startswith("http://") and "localhost" not in o for o in self.cors_origins):
            problems.append("CORS_ORIGINS deve usar https:// em produção")
        if not any(o.startswith("https://") for o in self.cors_origins):
            problems.append("CORS_ORIGINS sem o endereço https do site (ex.: https://jc-moda.vercel.app)")
        if problems:
            raise RuntimeError("Configuração insegura para produção: " + "; ".join(problems))


settings = Settings()
