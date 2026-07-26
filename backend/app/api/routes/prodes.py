"""
Rotas de leitura dos registros de desmatamento do PRODES/INPE
(`prodes_desmatamento`, populada por `scripts/seed_prodes.py`).
"""
import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db import prodes as prodes_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prodes", tags=["prodes"])


@router.get("/municipio/{codigo}")
def get_prodes_municipio(codigo: str, current_user: str = Depends(get_current_user)):
    """Histórico de desmatamento (por bioma e ano) já ingerido para o
    município — lista vazia se o seed ainda não cobriu essa área (nunca
    fabrica um registro)."""
    return {"municipio_codigo": codigo, "registros": prodes_db.list_prodes_by_municipio(codigo)}


@router.get("/resumo")
def get_prodes_resumo(current_user: str = Depends(get_current_user)):
    """Contagem de registros já ingeridos por bioma — útil para acompanhar o
    progresso da ingestão nacional (`scripts/seed_prodes.py` roda em
    background e pode levar horas)."""
    return prodes_db.count_by_bioma()
