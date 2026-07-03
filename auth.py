"""Landing page e controles de login/logout com Google (via st.login nativo do Streamlit)."""
import streamlit as st


def is_logged_in() -> bool:
    """True se o usuário está logado. False também quando [auth] não está configurado
    (st.user.is_logged_in lança AttributeError nesse caso, em vez de retornar False)."""
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
