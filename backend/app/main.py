"""
Descrição da funcionalidade
---------------------------
Ponto de entrada da API FastAPI — substitui `app.py::main()` como ponto de
entrada do processo (antes `streamlit run app.py`, agora
`uvicorn app.main:app`). Fase 1: só monta autenticação; as rotas de
análise/credenciais/IBGE/etc. entram nas Fases 2-3 (ver
C:\\Users\\TRENI\\.claude\\plans\\elegant-exploring-crescent.md).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth as auth_routes
from app.core.config import get_settings
from app.db.schema import init_db

app = FastAPI(title="Landscape Metrics Extractor API")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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
