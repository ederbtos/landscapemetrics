"""
Descrição da funcionalidade
---------------------------
Camada de apresentação e controle de acesso do app: landing page pública e
gate de login antes de liberar qualquer funcionalidade de análise. Resolve o
problema de negócio de identificar o usuário para associá-lo às suas próprias
credenciais do Earth Engine (ver db.py) — sem isso, a Fase 3 do roadmap
(credenciais por usuário) não teria uma chave de identidade estável.

Contexto técnico
-----------------
Dois modos de login coexistem, ambos usando o e-mail do usuário como chave
de identidade em db.py:

1. **E-mail/senha (sempre disponível)**: cadastro aberto, senha com hash
   bcrypt na tabela `users` de `data/app.db` (ver db.py). Sessão representada
   por um JWT (HS256, `jwt_secret_key` em `.streamlit/secrets.toml`) guardado
   em `st.session_state` — não sobrevive a um refresh (F5) da página.
2. **Google OAuth (opcional)**: só aparece quando a seção `[auth]` de
   `.streamlit/secrets.toml` está configurada com uma credencial OAuth real
   do Google Cloud Console. Usa `st.login()`/`st.user`/`st.logout()` nativos
   do Streamlit — a sessão é gerenciada pelo próprio Streamlit (cookie
   assinado) e sobrevive a um refresh, ao contrário do modo e-mail/senha.

Regras de negócio
------------------
- Sem sessão válida em nenhum dos dois modos, o usuário só pode ver a
  landing page — nenhum dado de paisagem é acessível.
- O e-mail (de qualquer um dos dois modos) é a chave primária usada para
  buscar/salvar credenciais do Earth Engine em db.py — um mesmo e-mail
  logando ora via Google ora via senha enxerga as mesmas credenciais GEE.

Pontos de atenção
------------------
- `st.user.email` (modo Google) não é validado quanto a verificação de
  e-mail pelo provedor antes de ser usado como chave; já o e-mail do
  cadastro por senha nunca é verificado (sem confirmação por e-mail) — em
  ambos os casos, o e-mail é só uma chave de conta, não uma prova de posse.
- Se `[auth]` estiver ausente/incompleta em `secrets.toml`, o botão do
  Google simplesmente não aparece (em vez de travar a aplicação) — decisão
  intencional para permitir rodar só com login por senha.
"""
import re
from datetime import datetime, timedelta, timezone

import jwt
import streamlit as st

import db

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION = timedelta(hours=24)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get_jwt_secret() -> str:
    secret = st.secrets.get("jwt_secret_key")
    if not secret:
        raise RuntimeError(
            "jwt_secret_key não configurado em .streamlit/secrets.toml. "
            "Gere um com: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return secret


def _create_token(email: str) -> str:
    payload = {
        "email": email,
        "exp": datetime.now(timezone.utc) + JWT_EXPIRATION,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload.get("email")


def _google_oauth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except FileNotFoundError:
        return False


def _google_logged_in() -> bool:
    try:
        return bool(st.user.is_logged_in)
    except AttributeError:
        return False


def is_logged_in() -> bool:
    if _google_logged_in():
        return True
    token = st.session_state.get("jwt_token")
    return bool(token) and _decode_token(token) is not None


def get_current_user_email() -> str:
    if _google_logged_in():
        return st.user.email
    email = _decode_token(st.session_state.get("jwt_token", ""))
    if email is None:
        raise RuntimeError("get_current_user_email() chamado sem sessão válida")
    return email


def _render_login_form() -> None:
    with st.form("login_form"):
        email = st.text_input("E-mail")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if not submitted:
        return
    if db.verify_user(email, password):
        st.session_state["jwt_token"] = _create_token(email)
        st.rerun()
    else:
        st.error("❌ E-mail ou senha inválidos.")


def _render_register_form() -> None:
    with st.form("register_form"):
        email = st.text_input("E-mail", key="register_email")
        password = st.text_input("Senha", type="password", key="register_password")
        password_confirm = st.text_input(
            "Confirmar senha", type="password", key="register_password_confirm"
        )
        submitted = st.form_submit_button("Criar conta", type="primary")
    if not submitted:
        return
    if not EMAIL_RE.match(email or ""):
        st.error("❌ Informe um e-mail válido.")
        return
    if len(password or "") < 8:
        st.error("❌ A senha precisa ter pelo menos 8 caracteres.")
        return
    if password != password_confirm:
        st.error("❌ As senhas não coincidem.")
        return
    if db.create_user(email, password):
        st.session_state["jwt_token"] = _create_token(email)
        st.success("✅ Conta criada!")
        st.rerun()
    else:
        st.error("❌ Já existe uma conta com esse e-mail.")


def render_landing_page() -> None:
    col1, col2 = st.columns([2, 3])

    with col1:
        st.markdown(
            '<h1 style="color:Blue">🏞️ Landscape Metrics Extractor</h1>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Powered by MapBiomas, Pylandstats, Google Earth Engine and Geemap | "
            "Developed by Pedro Higuchi ([@pe_hi](https://twitter.com/pe_hi))"
        )
        st.caption("Contato: higuchip@gmail.com")

    with col2:
        st.markdown(
            "<h4 style=' color: black; background-color:lightgreen; padding:25px; "
            "border-radius: 25px; box-shadow: 0 0 0.1em black'>Aplicativo Web para extração de "
            "métricas de paisagem de pontos de interesse a partir da base de dados do "
            "MapBiomas</h4>",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.info(
        "🔒 Cada usuário usa sua própria conta de serviço do Google Earth Engine. "
        "Faça login (ou crie uma conta) para continuar."
    )

    if _google_oauth_configured():
        if st.button("🔑 Entrar com Google", type="primary"):
            st.login()
        st.markdown("— ou entre com e-mail e senha —")

    login_tab, register_tab = st.tabs(["Entrar", "Criar conta"])
    with login_tab:
        _render_login_form()
    with register_tab:
        _render_register_form()


def render_user_badge() -> None:
    with st.sidebar:
        st.markdown(f"👤 **{get_current_user_email()}**")
        if st.button("Sair"):
            if _google_logged_in():
                st.logout()
            else:
                del st.session_state["jwt_token"]
                st.rerun()
