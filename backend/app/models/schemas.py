"""
Descrição da funcionalidade
---------------------------
Modelos Pydantic de request/response da API — o contrato explícito que a
antiga UI Streamlit nunca precisou ter (não havia serialização entre camadas,
`main()` chamava as funções de domínio diretamente). Fase 1 cobre só
autenticação; os demais schemas (análise, IBGE, matriz SSE, lote por
município) entram nas Fases 2-3.
"""
import re

from pydantic import BaseModel, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: str
    password: str
    password_confirm: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_RE.match(v or ""):
            raise ValueError("Informe um e-mail válido.")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v or "") < 8:
            raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    email: str


class AuthConfigResponse(BaseModel):
    google_oauth_enabled: bool
