"""
Rotas de leitura das estações e séries hidroclimáticas da ANA
(`ana_estacoes`/`ana_serie_historica`). Só retornam dado real depois que
`scripts/seed_ana_hidroclimatica.py` rodar de fato — hoje bloqueado por
falta de credencial de API da ANA (ver docstring do script de seed). As
rotas já ficam prontas para não exigir mais uma alteração de código quando a
credencial existir.
"""
import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db import ana_hidroclimatica as ana_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ana", tags=["ana"])


@router.get("/estacoes")
def listar_estacoes(municipio_codigo: str, current_user: str = Depends(get_current_user)):
    """Estações hidroclimáticas de um município — lista vazia enquanto o
    seed da ANA estiver bloqueado por credencial."""
    return ana_db.list_estacoes_by_municipio(municipio_codigo)


@router.get("/serie/{codigo}")
def get_serie_estacao(codigo: str, current_user: str = Depends(get_current_user)):
    """Série histórica (vazão/nível/chuva) de uma estação — lista vazia
    enquanto o seed da ANA estiver bloqueado por credencial."""
    return {"estacao_codigo": codigo, "serie": ana_db.get_serie_estacao(codigo)}
