"""
Descrição da funcionalidade
---------------------------
Reprocessa o `municipio_codigo` de registros de `prodes_desmatamento` que
ficaram `NULL` — normalmente porque `seed_prodes.py` rodou antes de
`municipios_malha` estar completa (a malha municipal é preenchida
progressivamente por `seed_municipios_malha.py`, UF por UF, enquanto o PRODES
pode estar processando em paralelo). Não faz nenhuma chamada de rede: só
relê a geometria já salva em `geojson` e refaz a junção espacial contra o
estado ATUAL de `municipios_malha` — rápido o suficiente para rodar de novo
sempre que a malha ganhar mais UFs.

Uso:
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\reresolve_prodes_municipios.py
"""
import json
import logging
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.db.municipios import all_municipio_codes, get_municipio_malha  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_municipio_index():
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    codigos = all_municipio_codes()
    geoms = []
    codigos_validos = []
    for codigo in codigos:
        row = get_municipio_malha(codigo)
        try:
            feature = json.loads(row["geojson"])["features"][0]
            geoms.append(shape(feature["geometry"]))
            codigos_validos.append(codigo)
        except Exception as err:
            logger.warning("Geometria inválida para município %s, ignorado: %s", codigo, err)

    logger.info("Índice espacial construído com %d municípios.", len(geoms))
    return STRtree(geoms), geoms, codigos_validos


def resolver_municipio(tree, geoms, codigos, centroid) -> str | None:
    for idx in tree.query(centroid):
        if geoms[idx].contains(centroid):
            return codigos[idx]
    return None


def main() -> None:
    from shapely.geometry import shape

    tree, geoms, codigos = build_municipio_index()
    if not codigos:
        logger.error("municipios_malha está vazia — nada a fazer ainda.")
        return

    db_path = get_settings().db_path
    with closing(sqlite3.connect(db_path)) as conn:
        pendentes = conn.execute(
            "SELECT id, geojson FROM prodes_desmatamento WHERE municipio_codigo IS NULL AND geojson IS NOT NULL"
        ).fetchall()
        logger.info("%d registros do PRODES sem município resolvido.", len(pendentes))

        resolvidos = 0
        for row_id, geojson_str in pendentes:
            try:
                centroid = shape(json.loads(geojson_str)).centroid
                codigo = resolver_municipio(tree, geoms, codigos, centroid)
            except Exception as err:
                logger.warning("Falha ao reprocessar feature id=%s: %s", row_id, err)
                continue
            if codigo:
                conn.execute(
                    "UPDATE prodes_desmatamento SET municipio_codigo = ? WHERE id = ?", (codigo, row_id)
                )
                resolvidos += 1
        conn.commit()

    logger.info("Concluído: %d de %d registros pendentes ganharam município nesta passada.", resolvidos, len(pendentes))


if __name__ == "__main__":
    main()
