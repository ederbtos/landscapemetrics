"""
Atlas Nacional de Paisagem — Fase 0 (Diversidade).

Cálculo puro (sem I/O, sem Earth Engine, sem PyLandStats/raster) de índices
de diversidade e composição da paisagem a partir de área por classe já
agregada em `mapbiomas_municipio_stats` (ver `backend/app/db/mapbiomas_stats.py`).

Diferente do resto do pipeline (`landscape_core.py`), que sempre parte de um
raster real (pixels), este módulo nunca abre um GeoTIFF nem chama o Earth
Engine — os únicos insumos são área (ha) por classe MapBiomas, já 100%
carregada nacionalmente (2004-2023). Por isso cobre só os índices que
dependem exclusivamente da PROPORÇÃO de área por classe (SHDI/SHEI/SIDI/SIEI/
riqueza) — métricas de fragmentação espacial de verdade (densidade de
manchas, borda, forma) exigem o raster pixel a pixel e ficam para uma Fase 1
futura (extração via Earth Engine por município, ver ROADMAP.md).
"""
from app.services import landscape_core

# Agrupamento pragmático dos códigos MapBiomas (mesma legenda de
# `landscape_core.MAPBIOMAS_LEGEND_KEYS`) em macro-categorias — SIMPLIFICAÇÃO
# própria deste projeto, não uma hierarquia oficial baixada da API do
# MapBiomas. Documentado aqui para quem for interpretar/questionar o
# resultado do Atlas.
NATURAL_CLASS_CODES = {1, 3, 4, 5, 10, 11, 12, 13, 29, 49}
ANTROPICO_CLASS_CODES = {9, 14, 15, 18, 19, 20, 21, 36, 39, 40, 41, 46, 47, 48}
NAO_VEGETADO_CLASS_CODES = {22, 23, 24, 25, 30, 31, 32}
AGUA_CLASS_CODES = {26, 33}


def _classe_nome(codigo: int) -> str:
    if 0 <= codigo < len(landscape_core.MAPBIOMAS_LEGEND_KEYS):
        nome = landscape_core.MAPBIOMAS_LEGEND_KEYS[codigo].strip()
        return nome or f"Classe {codigo}"
    return f"Classe {codigo}"


def _pct_for_codes(area_by_class: dict, codes: set, area_total: float) -> float:
    if area_total <= 0:
        return 0.0
    soma = sum(area for classe, area in area_by_class.items() if classe in codes)
    return soma / area_total * 100


def compute_diversity_metrics(area_by_class: dict) -> dict:
    """A partir de `{classe_codigo: area_ha}` de UM município/ano, calcula os
    índices de diversidade (via `landscape_core.diversity_indices_from_proportions`,
    a mesma função usada pelo pipeline raster) e a composição por
    macro-categoria. `area_by_class` deve conter só classes com área > 0.

    Retorna `None` se não houver nenhuma área válida (evita ZeroDivisionError
    e um resultado fabricado a partir de dado vazio — mesma regra do resto
    do app: sem dado real, sem métrica)."""
    area_total = sum(area_by_class.values())
    if area_total <= 0 or not area_by_class:
        return None

    proportions = [area / area_total for area in area_by_class.values() if area > 0]
    indices = landscape_core.diversity_indices_from_proportions(proportions)

    classe_dominante_codigo, classe_dominante_area = max(area_by_class.items(), key=lambda item: item[1])

    result = {
        "area_total_ha": area_total,
        "classe_dominante_codigo": classe_dominante_codigo,
        "classe_dominante_nome": _classe_nome(classe_dominante_codigo),
        "classe_dominante_pct": classe_dominante_area / area_total * 100,
        "area_natural_pct": _pct_for_codes(area_by_class, NATURAL_CLASS_CODES, area_total),
        "area_antropizada_pct": _pct_for_codes(area_by_class, ANTROPICO_CLASS_CODES, area_total),
        "area_nao_vegetada_pct": _pct_for_codes(area_by_class, NAO_VEGETADO_CLASS_CODES, area_total),
        "area_agua_pct": _pct_for_codes(area_by_class, AGUA_CLASS_CODES, area_total),
    }
    result.update(indices)
    return result


def compute_trend(area_natural_pct_inicio: float, area_natural_pct_fim: float) -> dict:
    """Variação de área natural entre dois anos (ex.: primeiro e último ano
    carregados para um município) — ponto central da leitura "disruptiva" do
    Atlas: quem mais perdeu (ou ganhou) vegetação nativa no período. Positivo
    = ganho de área natural; negativo = perda."""
    return {
        "variacao_area_natural_pp": area_natural_pct_fim - area_natural_pct_inicio,
    }
