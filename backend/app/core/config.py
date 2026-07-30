"""
Descrição da funcionalidade
---------------------------
Configuração central do backend: segredos (chaves JWT, chave de criptografia
Fernet, credenciais OAuth do Google) fora do código-fonte, via variáveis de
ambiente (padrão para uma API FastAPI/Docker).

Contexto técnico
-----------------
`pydantic-settings` lê de variáveis de ambiente (e opcionalmente de um `.env`
local em desenvolvimento). `db_path` aponta para o SQLite existente em
`data/app.db` (usuários/credenciais/histórico reais).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_path: str = "data/app.db"

    jwt_secret_key: str = "dev-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Precisa ser uma chave Fernet válida (32 bytes raw, base64 url-safe) —
    # o placeholder anterior era só texto legível em base64 e derrubava
    # save/get_credentials com "Fernet key must be 32 url-safe
    # base64-encoded bytes" na primeira vez que alguém esquecesse de
    # configurar um valor real em produção, em vez de um erro claro sobre a
    # causa. Continua inseguro como default (mesmo espírito de
    # jwt_secret_key acima) — troque sempre em produção.
    app_encryption_key: str = "3zW1kQhX8pL0mN2vB5tR7yF9cA4dE6gH1jK3nP5qS8w="

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
