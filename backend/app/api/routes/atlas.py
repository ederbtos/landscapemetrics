"""
Atlas Nacional de Paisagem — Fase 0 (Diversidade).

Rotas de LEITURA sobre `diversity_atlas_municipio` (pré-computada por
`scripts/build_diversity_atlas.py` a partir de `mapbiomas_municipio_stats`,
sem Earth Engine). Diferente de toda outra rota deste backend, estas são
PÚBLICAS — sem `Depends(get_current_user)` — de propósito: o Atlas é a
vitrine nacional pensada para ser navegada e citada sem exigir cadastro.
"""
import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.db import diversity_atlas as diversity_atlas_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/atlas", tags=["atlas"])

METRICA_PADRAO = "shannon_diversity_index"


def _validar_metrica(metrica: str) -> str:
    if metrica not in diversity_atlas_db.RANKING_METRIC_COLUMNS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Métrica {metrica!r} inválida. Use uma de: "
                f"{sorted(diversity_atlas_db.RANKING_METRIC_COLUMNS)}"
            ),
        )
    return metrica


@router.get("/anos-disponiveis")
def get_anos_disponiveis():
    return {"anos": diversity_atlas_db.get_anos_disponiveis()}


@router.get("/ranking")
def get_ranking(
    ano: int,
    metrica: str = Query(METRICA_PADRAO),
    ordem: str = Query("desc", pattern="^(asc|desc)$"),
    uf: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _validar_metrica(metrica)
    return {
        "ano": ano, "metrica": metrica, "ordem": ordem, "uf": uf,
        "municipios": diversity_atlas_db.get_ranking(
            ano=ano, metrica=metrica, ordem=ordem, uf=uf, limit=limit, offset=offset,
        ),
    }


@router.get("/ranking-tendencia")
def get_ranking_tendencia(
    ano_inicio: int,
    ano_fim: int,
    uf: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Municípios ordenados pela maior PERDA de área natural entre
    `ano_inicio` e `ano_fim` (perda primeiro) — o indicador mais
    "disruptivo" do Atlas: um ranking nacional de degradação da paisagem que
    nenhuma ferramenta desktop como o FRAGSTATS calcula de forma pronta."""
    if ano_fim <= ano_inicio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ano_fim deve ser maior que ano_inicio.",
        )
    return {
        "ano_inicio": ano_inicio, "ano_fim": ano_fim, "uf": uf,
        "municipios": diversity_atlas_db.get_ranking_trend(
            ano_inicio=ano_inicio, ano_fim=ano_fim, uf=uf, limit=limit,
        ),
    }


@router.get("/municipio/{codigo}")
def get_municipio_atlas(codigo: str):
    serie = diversity_atlas_db.get_municipio_series(codigo)
    if not serie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum dado do Atlas para o município {codigo!r} — rode scripts/build_diversity_atlas.py.",
        )
    primeiro, ultimo = serie[0], serie[-1]
    tendencia = None
    if primeiro["ano"] != ultimo["ano"]:
        tendencia = {
            "ano_inicio": primeiro["ano"], "ano_fim": ultimo["ano"],
            "variacao_area_natural_pp": ultimo["area_natural_pct"] - primeiro["area_natural_pct"],
        }
    return {"municipio_codigo": codigo, "serie": serie, "tendencia": tendencia}


@router.get("/mapa")
def get_mapa(
    ano: int,
    metrica: str = Query(METRICA_PADRAO),
    uf: str | None = None,
):
    _validar_metrica(metrica)
    return diversity_atlas_db.get_mapa_geojson(ano=ano, metrica=metrica, uf=uf)
