"""
Descrição da funcionalidade
---------------------------
Ponto de entrada da API FastAPI — substitui `app.py::main()` como ponto de
entrada do processo (antes `streamlit run app.py`, agora
`uvicorn app.main:app`). Monta autenticação, análise/credenciais/IBGE/SSE/
LGPD/supervisionado, além dos dados de referência nacionais (malha
municipal, MapBiomas agregado, PRODES, ANA — ver `scripts/seed_*.py`).
"""
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

ROOT_DIR = Path(__file__).resolve().parents[1]  # backend/ — para `import app.api.routes...`
PROJECT_ROOT = ROOT_DIR.parent  # raiz do repo — onde vive static/
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.routes import ana_hidroclimatica as ana_routes
from app.api.routes import auth as auth_routes
from app.api.routes import credentials as credentials_routes
from app.api.routes import ibge as ibge_routes
from app.api.routes import lgpd as lgpd_routes
from app.api.routes import mapbiomas_stats as mapbiomas_stats_routes
from app.api.routes import markov as markov_routes
from app.api.routes import metrics as metrics_routes
from app.api.routes import municipio_batch as municipio_batch_routes
from app.api.routes import prodes as prodes_routes
from app.api.routes import sse as sse_routes
from app.api.routes import supervised as supervised_routes
from app.api.routes import user as user_routes
from app.core.config import get_settings
from app.db.schema import init_db

app = FastAPI(title="Landscape Metrics Extractor API")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Guarda o "state"/nonce do fluxo OAuth do Google entre /api/auth/google/login
# e /api/auth/google/callback (authlib.integrations.starlette_client precisa
# de request.session) — não é a sessão do usuário em si, essa continua sendo
# o JWT + refresh token de app/core/security.py.
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth_routes.router)
app.include_router(credentials_routes.router)
app.include_router(sse_routes.router)
app.include_router(ibge_routes.router)
app.include_router(metrics_routes.router)
app.include_router(lgpd_routes.router)
app.include_router(user_routes.router)
app.include_router(supervised_routes.router)
app.include_router(prodes_routes.router)
app.include_router(mapbiomas_stats_routes.router)
app.include_router(ana_routes.router)
app.include_router(markov_routes.router)
app.include_router(municipio_batch_routes.router)

static_dir = os.path.join(PROJECT_ROOT, "static")

# A raiz do site é a landing page (marketing/explicação, sem exigir login) —
# StaticFiles(html=True) serviria index.html (a ferramenta) por padrão em
# "/", pulando a landing inteiramente, então uma rota explícita para "/"
# precisa vir ANTES do mount abaixo para ter prioridade. "Explorar o
# sistema"/"Abrir a plataforma" na landing levam para /index.html, que aí
# sim pede login para calcular métricas e usar o resto da ferramenta.
@app.get("/", include_in_schema=False)
def serve_landing_page():
    return FileResponse(os.path.join(static_dir, "landing.html"))


if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


