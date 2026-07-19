"""
Descrição da funcionalidade
---------------------------
Emissão/validação de sessão (substitui `auth.py::_create_token/_decode_token`
do app Streamlit) e hashing de senha (bcrypt, reaproveitado sem mudanças de
`db.py`). Resolve o problema documentado em ROADMAP.md ("Bloqueio conhecido":
sessão não sobrevivia a um F5 por viver só em `st.session_state`, sem
cookie) — ver `refresh_token_*` abaixo.

Contexto técnico
-----------------
Dois tokens, dois propósitos:
- **Access token**: JWT HS256 de vida curta (`access_token_expire_minutes`,
  padrão 15min), mesmo formato `{email, exp}` de antes — carregado no corpo da
  resposta HTTP, o frontend guarda só em memória (nunca `localStorage`).
- **Refresh token**: string opaca (`secrets.token_urlsafe`), vida longa
  (`refresh_token_expire_days`, padrão 30 dias) — só o hash SHA-256 é
  persistido em `refresh_tokens` (db/refresh_tokens.py); o valor em claro só
  existe no cookie `httpOnly` do navegador. Rotacionado a cada uso em
  `/api/auth/refresh` (o token antigo é invalidado), limitando a janela de
  replay caso vaze.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def verify_password(password: str, password_hash: bytes) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash)


def create_access_token(email: str) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_expire_minutes * 60
    payload = {
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> str | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    return payload.get("email")


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Gera um novo refresh token. Retorna (valor em claro p/ cookie, hash p/
    persistir, timestamp de expiração)."""
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_refresh_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return raw_token, token_hash, expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
