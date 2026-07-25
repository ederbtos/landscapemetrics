"""
Descrição da funcionalidade
---------------------------
Ponto de entrada da API FastAPI — substitui `app.py::main()` como ponto de
entrada do processo (antes `streamlit run app.py`, agora
`uvicorn app.main:app`). Fase 1: só monta autenticação; as rotas de
análise/credenciais/IBGE/etc. entram nas Fases 2-3 (ver
C:\\Users\\TRENI\\.claude\\plans\\elegant-exploring-crescent.md).
"""
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.routes import auth as auth_routes
from app.api.routes import credentials as credentials_routes
from app.api.routes import ibge as ibge_routes
from app.api.routes import lgpd as lgpd_routes
from app.api.routes import metrics as metrics_routes
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

static_dir = os.path.join(ROOT_DIR, "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


