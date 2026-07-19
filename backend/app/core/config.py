"""
Descrição da funcionalidade
---------------------------
Configuração central do backend (equivalente ao antigo `.streamlit/secrets.toml`
lido via `st.secrets`). Resolve o mesmo problema de negócio de antes: manter
segredos (chaves JWT, chave de criptografia Fernet, credenciais OAuth do
Google) fora do código-fonte, agora via variáveis de ambiente (padrão para uma
API FastAPI/Docker) em vez de um arquivo TOML lido pelo runtime do Streamlit.

Contexto técnico
-----------------
`pydantic-settings` lê de variáveis de ambiente (e opcionalmente de um `.env`
local em desenvolvimento). `DB_PATH` mantém o mesmo default relativo
(`data/app.db`) que `db.py` usava, para que o banco SQLite existente
(`data/app.db`, com usuários/credenciais/histórico reais) continue sendo lido
sem qualquer migração.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_path: str = "data/app.db"

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    app_encryption_key: str

    cors_origins: list[str] = ["http://localhost:5173"]

    # False só em desenvolvimento local sem HTTPS (o cookie de refresh exige
    # Secure em produção, atrás do Caddy — ver Fase 8/deploy).
    cookie_secure: bool = True

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    google_server_metadata_url: str = "https://accounts.google.com/.well-known/openid-configuration"

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)


@lru_cache
def get_settings() -> Settings:
    return Settings()
