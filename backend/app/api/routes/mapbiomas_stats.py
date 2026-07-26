"""
Rotas de leitura das estatísticas de uso e cobertura da terra do MapBiomas
agregadas por município/ano/classe (`mapbiomas_municipio_stats`, populada
por `scripts/seed_mapbiomas_stats.py`).
"""
import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db import mapbiomas_stats as mapbiomas_stats_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mapbiomas", tags=["mapbiomas"])


@router.get("/serie/{municipio_codigo}")
def get_serie_municipio(municipio_codigo: str, current_user: str = Depends(get_current_user)):
    """Série completa (ano x classe x área em hectares) já ingerida para o
    município — lista vazia se o seed ainda não cobriu essa área/anos. Serve
    de base real para a predição de Markov já existente no app (hoje
    limitada a upload manual de múltiplos GeoTIFFs)."""
    return {
        "municipio_codigo": municipio_codigo,
        "anos_disponiveis": mapbiomas_stats_db.anos_disponiveis(municipio_codigo),
        "serie": mapbiomas_stats_db.get_serie_municipio(municipio_codigo),
    }
