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
Usa `st.login`/`st.user`/`st.logout`, a API nativa de auth do Streamlit
(OAuth/OIDC), configurada via seção `[auth]` de `.streamlit/secrets.toml`
(client_id/secret, redirect_uri, cookie_secret). app.py chama
`is_logged_in()` antes de renderizar qualquer conteúdo (gate) e
`render_user_badge()` depois do login.

Regras de negócio
------------------
- Sem sessão válida, o usuário só pode ver a landing page — nenhum dado de
  paisagem é acessível.
- O e-mail do usuário autenticado (`st.user.email`) é a chave primária usada
  para buscar/salvar credenciais do Earth Engine em db.py.

Pontos de atenção
------------------
- `st.user.email` não é validado quanto a verificação de e-mail pelo provedor
  antes de ser usado como chave em `user_credentials`; depende inteiramente da
  garantia do OAuth do Google de que o e-mail retornado é verificado.
- Login mal configurado (`[auth]` ausente) não trava a aplicação com erro —
  degrada para uma mensagem informativa, decisão intencional para permitir
  rodar localmente sem OAuth durante desenvolvimento.
"""
import streamlit as st


def is_logged_in() -> bool:
    """
    Retorna o estado de autenticação da sessão atual.

    Pontos de atenção: `st.user.is_logged_in` lança `AttributeError` (em vez
    de retornar False) quando a seção `[auth]` não existe em secrets.toml —
    esse é o único motivo do try/except aqui, não é tratamento de erro de
    autenticação em si.
    """
    try:
        return bool(st.user.is_logged_in)
    except AttributeError:
        return False


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
        "Faça login para continuar."
    )

    try:
        auth_configured = "auth" in st.secrets
    except FileNotFoundError:
        auth_configured = False

    if not auth_configured:
        st.error(
            "❌ Login com Google não está configurado. Adicione a seção `[auth]` em "
            "`.streamlit/secrets.toml` (veja `.streamlit/secrets.toml.example`)."
        )
        return

    if st.button("🔑 Entrar com Google", type="primary"):
        st.login("google")


def render_user_badge() -> None:
    with st.sidebar:
        st.markdown(f"👤 **{st.user.email}**")
        if st.button("Sair"):
            st.logout()
