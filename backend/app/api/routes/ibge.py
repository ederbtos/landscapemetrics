"""
Rotas para integração com a API do IBGE (Localidades, Malhas Territoriais e População Estimada)
"""
import json
from fastapi import APIRouter, HTTPException
import requests
import logging

from app.db import municipios as municipios_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ibge", tags=["ibge"])

# Nomes das 27 UFs — dado estático (divisão federativa do Brasil não muda),
# usado só para completar `list_ufs()` (que só tem as siglas presentes na
# malha cacheada) sem precisar de uma chamada ao vivo.
_UF_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia",
    "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}


@router.get("/ufs")
def get_ufs():
    """Lista de UFs (estados) do Brasil — checa o cache nacional
    (`municipios_malha`, ver `scripts/seed_municipios_malha.py`) primeiro; só
    cai na chamada ao vivo à API do IBGE se o cache ainda estiver vazio."""
    cached_ufs = municipios_db.list_ufs()
    if cached_ufs:
        return [{"sigla": uf, "nome": _UF_NAMES.get(uf, uf)} for uf in cached_ufs]

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
    """Municípios de uma UF — checa o cache nacional (`municipios_malha`)
    primeiro; só cai na chamada ao vivo à API do IBGE se essa UF ainda não
    estiver cacheada."""
    cached = municipios_db.list_municipios_by_uf(uf)
    if cached:
        return [{"id": m["codigo_ibge"], "nome": m["nome"]} for m in cached]

    try:
        res = requests.get(f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf.upper()}/municipios", timeout=10)
        res.raise_for_status()
        munis = res.json()
        return [{"id": str(m["id"]), "nome": m["nome"]} for m in sorted(munis, key=lambda x: x["nome"])]
    except Exception as err:
        logger.error(f"Erro ao buscar municípios no IBGE para {uf}: {err}")
        raise HTTPException(status_code=502, detail=f"Erro de comunicação com a API do IBGE: {err}")


@router.get("/municipios/{codigo}/malha")
def get_municipio_malha(codigo: str):
    """Limite territorial (GeoJSON) do município — checa o cache nacional
    (`municipios_malha`, ver `scripts/seed_municipios_malha.py`) primeiro;
    se ainda não estiver cacheado, cai na chamada ao vivo à API de malhas do
    IBGE (mesma função usada pelo pipeline de análise em
    `services/landscape.py`), nunca retorna vazio silenciosamente."""
    cached = municipios_db.get_municipio_malha(codigo)
    if cached is not None:
        return json.loads(cached["geojson"])

    try:
        res = requests.get(
            f"https://servicodados.ibge.gov.br/api/v3/malhas/municipios/{codigo}",
            params={"formato": "application/vnd.geo+json", "qualidade": "minima"},
            timeout=15,
        )
        res.raise_for_status()
        return res.json()
    except Exception as err:
        logger.error(f"Erro ao buscar malha do município {codigo} no IBGE: {err}")
        raise HTTPException(status_code=502, detail=f"Erro de comunicação com a API do IBGE: {err}")


@router.get("/municipios/{codigo}/populacao")
def get_populacao(codigo: str):
    """População estimada do município — `municipios_malha.populacao_estimada`
    já vem preenchida pelo mesmo `scripts/seed_municipios_malha.py` que
    cacheia a malha (mesma consulta SIDRA feita aqui embaixo, só que em lote
    no momento do seed). Só cai na chamada ao vivo se o município não estiver
    cacheado, ou se a coluna ficou `NULL` (ex.: seed rodado com
    `--skip-populacao`, ou aquele município específico falhou na consulta
    SIDRA durante o seed)."""
    cached = municipios_db.get_municipio_malha(codigo)
    if cached is not None and cached["populacao_estimada"] is not None:
        return {"municipio_codigo": codigo, "populacao_estimada": cached["populacao_estimada"]}

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
