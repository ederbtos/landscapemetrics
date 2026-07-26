"""
Descrição da funcionalidade
---------------------------
Popula `prodes_desmatamento` (backend/app/db/prodes.py) com os registros de
desmatamento do PRODES/INPE via WFS do GeoServer do TerraBrasilis, para
todos os biomas monitorados (Amazônia, Cerrado, Caatinga, Mata Atlântica,
Pampa, Pantanal — 6 camadas confirmadas ao vivo nesta sessão, ver
`GetCapabilities` em `https://terrabrasilis.dpi.inpe.br/geoserver/ows`).
Deliberadamente NÃO inclui `prodes-legal-amz` (delimitação política da
Amazônia Legal, não um bioma — incluiria junto com `prodes-amazon-nb`
contaria a mesma área desmatada duas vezes).

Contexto técnico
-----------------
Volume real confirmado ao vivo: só a camada da Amazônia tem ~835 mil
features (`totalFeatures` no GetFeature) — a ingestão completa dos 6 biomas
provavelmente passa de 1-2 milhões de registros e leva várias horas. Por
isso o script:
- Pagina via `startIndex`/`count` até a página vir vazia.
- Grava um checkpoint em disco (`scripts/.checkpoints/prodes.json`) com o
  último `startIndex` concluído por camada, para retomar sem re-baixar
  páginas já processadas (a tabela em si já é idempotente via
  `UNIQUE(bioma, feature_id)`, o checkpoint só evita tráfego de rede
  redundante).
- Isola erro por feature (loga e segue, nunca fabrica dado) e por página
  (se uma página inteira falhar, tenta de novo até `--max-retries` antes de
  desistir da camada).

Campos confirmados ao vivo na resposta GeoJSON (iguais nas 3 camadas
testadas: Legal Amazon, Cerrado, Pantanal): `year` (ano de detecção),
`area_km` (área já em km², oficial do INPE — não recalculamos a partir da
geometria), `main_class` (só `'DESMATAMENTO'` conta como registro real; as
camadas também trazem outras classes de fundo, ex. hidrografia/não-floresta,
que não são desmatamento).

O município é atribuído por junção espacial (centroide da feature dentro do
polígono do município, via `shapely.strtree.STRtree` — muito mais rápido
que varredura linear contra os ~5.570 municípios) — requer
`scripts/seed_municipios_malha.py` já ter rodado. Sem junção espacial
resolvida, o campo fica `NULL` (nunca um palpite).

Uso:
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\seed_prodes.py [--bioma cerrado] [--page-size 2000] [--limit 5000]
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.db.municipios import all_municipio_codes, get_municipio_malha  # noqa: E402
from app.db.prodes import count_by_bioma, save_prodes_feature  # noqa: E402
from app.db.schema import init_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WFS_BASE = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
WFS_TIMEOUT = 60

# bioma -> layer WFS (confirmado via GetCapabilities nesta sessão)
LAYERS = {
    "amazonia": "prodes-amazon-nb:yearly_deforestation_biome",
    "cerrado": "prodes-cerrado-nb:yearly_deforestation",
    "caatinga": "prodes-caatinga-nb:yearly_deforestation",
    "mata_atlantica": "prodes-mata-atlantica-nb:yearly_deforestation",
    "pampa": "prodes-pampa-nb:yearly_deforestation",
    "pantanal": "prodes-pantanal-nb:yearly_deforestation",
}

CHECKPOINT_PATH = Path(__file__).resolve().parent / ".checkpoints" / "prodes.json"


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {}


def save_checkpoint(checkpoint: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def build_municipio_index():
    """STRtree dos polígonos de município (shapely, EPSG:4326/SIRGAS2000 —
    compatíveis o suficiente para point-in-polygon nesta escala) + lista
    paralela de códigos IBGE, para resolver `feature.centroid -> município`
    sem varrer os ~5.570 municípios um a um por feature do PRODES."""
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    codigos = all_municipio_codes()
    if not codigos:
        logger.warning("municipios_malha está vazia — rode seed_municipios_malha.py antes para ter o join espacial.")
        return None, [], []

    geoms = []
    codigos_validos = []
    for codigo in codigos:
        row = get_municipio_malha(codigo)
        try:
            feature = json.loads(row["geojson"])["features"][0]
            geoms.append(shape(feature["geometry"]))
            codigos_validos.append(codigo)
        except Exception as err:
            logger.warning("Geometria inválida para município %s, ignorado no join espacial: %s", codigo, err)

    logger.info("Índice espacial construído com %d municípios.", len(geoms))
    return STRtree(geoms), geoms, codigos_validos


def resolver_municipio(tree, geoms, codigos, centroid) -> str | None:
    if tree is None:
        return None
    for idx in tree.query(centroid):
        if geoms[idx].contains(centroid):
            return codigos[idx]
    return None


def fetch_page(layer: str, start_index: int, page_size: int) -> dict:
    resp = requests.get(
        WFS_BASE,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": layer,
            "outputFormat": "application/json",
            "startIndex": start_index,
            "count": page_size,
        },
        timeout=WFS_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def processar_bioma(bioma: str, layer: str, page_size: int, limit: int | None, max_retries: int, tree, geoms, codigos) -> None:
    from shapely.geometry import shape

    checkpoint = load_checkpoint()
    start_index = checkpoint.get(bioma, 0)
    total_processadas = 0
    total_erros = 0

    logger.info("Bioma %s (%s): retomando a partir do índice %d", bioma, layer, start_index)

    while True:
        if limit is not None and total_processadas >= limit:
            logger.info("Limite de %d features atingido para %s — parando (uso de --limit).", limit, bioma)
            break

        tentativa = 0
        while True:
            try:
                pagina = fetch_page(layer, start_index, page_size)
                break
            except requests.RequestException as err:
                tentativa += 1
                logger.error("Falha ao buscar página (bioma=%s, startIndex=%d, tentativa %d): %s", bioma, start_index, tentativa, err)
                if tentativa >= max_retries:
                    logger.error("Desistindo do bioma %s após %d tentativas na mesma página.", bioma, max_retries)
                    return
                time.sleep(2 * tentativa)

        features = pagina.get("features", [])
        if not features:
            logger.info("Bioma %s concluído — nenhuma feature restante a partir do índice %d.", bioma, start_index)
            break

        for feature in features:
            try:
                props = feature.get("properties", {}) or {}
                if props.get("main_class") and props["main_class"] != "DESMATAMENTO":
                    continue  # classes de fundo (ex.: hidrografia/não-floresta) não são desmatamento

                feature_id = feature.get("id")
                if not feature_id:
                    continue
                ano = props.get("year")
                area_km2 = props.get("area_km")

                municipio_codigo = None
                if tree is not None and feature.get("geometry"):
                    centroid = shape(feature["geometry"]).centroid
                    municipio_codigo = resolver_municipio(tree, geoms, codigos, centroid)

                save_prodes_feature(
                    bioma=bioma,
                    feature_id=feature_id,
                    municipio_codigo=municipio_codigo,
                    ano_deteccao=ano,
                    area_km2=area_km2,
                    geojson_str=json.dumps(feature.get("geometry")),
                )
                total_processadas += 1
            except Exception as feature_err:
                total_erros += 1
                logger.warning("Erro ao processar feature %s do bioma %s: %s", feature.get("id"), bioma, feature_err)

        start_index += len(features)
        checkpoint[bioma] = start_index
        save_checkpoint(checkpoint)

        if total_processadas % (page_size * 10) < page_size:
            logger.info("Bioma %s: %d features processadas até agora (índice atual %d).", bioma, total_processadas, start_index)

    logger.info("Bioma %s: %d processadas, %d erros nesta execução.", bioma, total_processadas, total_erros)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bioma", choices=list(LAYERS.keys()), help="Processa só um bioma (default: todos).")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=None, help="Máximo de features por bioma nesta execução (para testes/piloto).")
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    init_db()
    tree, geoms, codigos = build_municipio_index()

    biomas = {args.bioma: LAYERS[args.bioma]} if args.bioma else LAYERS
    for bioma, layer in biomas.items():
        processar_bioma(bioma, layer, args.page_size, args.limit, args.max_retries, tree, geoms, codigos)

    logger.info("Resumo final por bioma no banco: %s", count_by_bioma())


if __name__ == "__main__":
    main()
