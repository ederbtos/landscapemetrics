"""
Descrição da funcionalidade
---------------------------
Rotas de autenticação — porte de `auth.py` (formulários Streamlit
`_render_login_form`/`_render_register_form`) para endpoints REST. Cobre
e-mail/senha e Google OAuth (`/google/login` + `/google/callback`, via
Authlib) — o endpoint `GET /config` informa o frontend se deve mostrar o
botão do Google (`google_oauth_configured`, ver core/config.py).

Contexto técnico
-----------------
Cada login/registro/callback do Google bem-sucedido: (1) devolve um access
token JWT de vida curta no corpo da resposta (ou, no caso do Google, embutido
no fragmento da URL de redirect — ver `_finish_google_login` abaixo, já que
esse fluxo é uma navegação de página inteira, não um fetch), (2) grava um
refresh token opaco (hash SHA-256) em `refresh_tokens` e o envia em cookie
httpOnly — isso é o que resolve o "Bloqueio conhecido" do ROADMAP.md (sessão
sobrevive a F5 via `POST /refresh`, que o frontend chama ao carregar a
página).

Um usuário que loga só via Google nunca ganha uma linha na tabela `users`
(essa tabela é só para senha/hash bcrypt) — igual ao app Streamlit original,
onde `st.user.email` bastava como identidade em `db.py`/demais tabelas
(nenhuma tem FOREIGN KEY para `users`, ver `db/schema.py`).
"""
from datetime import datetime, timezone
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db import refresh_tokens as refresh_tokens_db
from app.db import users as users_db
from app.models.schemas import (
    AuthConfigResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.api.deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"

_oauth = OAuth()
if get_settings().google_oauth_configured:
    _oauth.register(
        name="google",
        client_id=get_settings().google_client_id,
        client_secret=get_settings().google_client_secret,
        server_metadata_url=get_settings().google_server_metadata_url,
        client_kwargs={"scope": "openid email profile"},
    )


def _issue_session(response: Response, email: str) -> TokenResponse:
    access_token, expires_in = create_access_token(email)

    raw_refresh, refresh_hash, refresh_expires_at = generate_refresh_token()
    refresh_tokens_db.store_refresh_token(refresh_hash, email, refresh_expires_at)

    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
    )
    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, response: Response) -> TokenResponse:
    if body.password != body.password_confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="As senhas não coincidem.")
    created = users_db.create_user(body.email, hash_password(body.password))
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma conta com esse e-mail.")
    return _issue_session(response, body.email)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response) -> TokenResponse:
    password_hash = users_db.get_password_hash(body.email)
    if password_hash is None or not verify_password(body.password, password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-mail ou senha inválidos.")
    return _issue_session(response, body.email)


@router.post("/refresh", response_model=TokenResponse)
def refresh(response: Response, refresh_token: str | None = Cookie(default=None)) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada. Faça login novamente.")

    token_hash = hash_refresh_token(refresh_token)
    record = refresh_tokens_db.get_valid_refresh_token(token_hash)
    if record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada. Faça login novamente.")

    # Rotação: o token apresentado é sempre invalidado, mesmo em caso de
    # sucesso — limita o impacto de um refresh token vazado/reutilizado.
    refresh_tokens_db.revoke_refresh_token(token_hash)
    return _issue_session(response, record["user_email"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, refresh_token: str | None = Cookie(default=None)) -> None:
    if refresh_token:
        refresh_tokens_db.revoke_refresh_token(hash_refresh_token(refresh_token))
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserResponse)
def me(current_user: str = Depends(get_current_user)) -> UserResponse:
    return UserResponse(email=current_user)


@router.get("/config", response_model=AuthConfigResponse)
def auth_config() -> AuthConfigResponse:
    return AuthConfigResponse(google_oauth_enabled=get_settings().google_oauth_configured)


def _require_google_configured() -> None:
    if not get_settings().google_oauth_configured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login com Google não está configurado.")


@router.get("/google/login")
async def google_login(request: Request):
    _require_google_configured()
    return await _oauth.google.authorize_redirect(request, get_settings().google_redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request) -> RedirectResponse:
    _require_google_configured()
    try:
        token = await _oauth.google.authorize_access_token(request)
    except Exception as exc:  # OAuthError da Authlib — código inválido/expirado/revogado
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falha na autenticação com o Google.") from exc

    email = (token.get("userinfo") or {}).get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não foi possível obter o e-mail da conta Google.")

    response = RedirectResponse(url="/index.html")
    session = _issue_session(response, email)
    # Navegação de página inteira (não fetch) — o access token viaja no
    # fragmento da URL para o app.js conseguir recuperá-lo ao carregar
    # index.html (ver checkAuthSession em static/app.js). O fragmento nunca é
    # enviado ao servidor por design (RFC 3986), só fica acessível ao JS.
    response.headers["location"] = f"/index.html#access_token={quote(session.access_token)}&email={quote(email)}"
    return response
