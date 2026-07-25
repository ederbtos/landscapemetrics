"""
Rotas para integração com a API do IBGE (Localidades, Malhas Territoriais e População Estimada)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
import requests
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ibge", tags=["ibge"])


@router.get("/ufs")
def get_ufs():
    """Retorna a lista de UFs (estados) do Brasil via API do IBGE."""
    try:
        res = requests.get("https://servicodados.ibge.gov.br/api/v1/localidades/estados?ordenacao=nome", timeout=10)
        res.raise_for_status()
        ufs = res.json()
        return [{"sigla": u["sigla"], "nome": u["nome"]} for u in ufs]
    except Exception as err:
        logger.error(f"Erro ao buscar UFs no IBGE: {err}")
        raise HTTPException(status_code=502, detail=f"Erro de comunicação com a API do IBGE: {err}")


@router.get("/ufs/{uf}/municipios")
def get_municipios(uf: str):
    """Retorna os municípios de uma UF específica."""
    try:
        res = requests.get(f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf.upper()}/municipios", timeout=10)
        res.raise_for_status()
        munis = res.json()
        return [{"id": str(m["id"]), "nome": m["nome"]} for m in sorted(munis, key=lambda x: x["nome"])]
    except Exception as err:
        logger.error(f"Erro ao buscar municípios no IBGE para {uf}: {err}")
        raise HTTPException(status_code=502, detail=f"Erro de comunicação com a API do IBGE: {err}")


@router.get("/municipios/{codigo}/populacao")
def get_populacao(codigo: str):
    """Busca a população estimada do município no IBGE."""
    try:
        res = requests.get(
            f"https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324?localidades=N6[{codigo}]",
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()
        val = data[0]["resultados"][0]["series"][0]["series"]["2021"]
        return {"municipio_codigo": codigo, "populacao_estimada": int(val)}
    except Exception:
        return {"municipio_codigo": codigo, "populacao_estimada": None}
