"""
Descrição da funcionalidade
---------------------------
Pré-computa `diversity_atlas_municipio` (backend/app/db/diversity_atlas.py) a
partir de `mapbiomas_municipio_stats`, já 100% carregada nacionalmente (ver
scripts/seed_mapbiomas_stats.py) — Atlas Nacional de Paisagem, Fase 0
(diversidade). 100% OFFLINE: não chama o Earth Engine, não abre nenhum
raster — só agrega área por classe já salva no banco e aplica
`app.services.diversity_atlas.compute_diversity_metrics`.

Idempotente (upsert por `municipio_codigo, ano`) — pode ser reexecutado a
qualquer momento (ex.: depois de `seed_mapbiomas_stats.py` carregar um ano
novo) sem duplicar nada.

Uso:
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\build_diversity_atlas.py
    ..\\.venv\\Scripts\\python.exe ..\\scripts\\build_diversity_atlas.py --uf SC
"""
import argparse
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.db.diversity_atlas import upsert_diversity_atlas_row  # noqa: E402
from app.db.schema import init_db  # noqa: E402
from app.services.diversity_atlas import compute_diversity_metrics  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_diversity_atlas(uf: str | None = None) -> int:
    """Agrega `mapbiomas_municipio_stats` por (município, ano) e faz upsert
    em `diversity_atlas_municipio`. Retorna o número de linhas
    (município x ano) gravadas. Função importável (não só CLI) para ser
    reaproveitada pelos testes."""
    query = """
        SELECT s.municipio_codigo, s.ano, s.classe_codigo, s.area_ha
        FROM mapbiomas_municipio_stats s
    """
    params: list = []
    if uf:
        query += """
            JOIN municipios_malha m ON m.codigo_ibge = s.municipio_codigo
            WHERE m.uf = ?
        """
        params.append(uf.upper())

    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(query, params).fetchall()

    por_municipio_ano: dict = defaultdict(dict)
    for municipio_codigo, ano, classe_codigo, area_ha in rows:
        if area_ha and area_ha > 0:
            por_municipio_ano[(municipio_codigo, ano)][classe_codigo] = area_ha

    total_gravado = 0
    for (municipio_codigo, ano), area_by_class in por_municipio_ano.items():
        metrics = compute_diversity_metrics(area_by_class)
        if metrics is None:
            continue
        upsert_diversity_atlas_row(municipio_codigo, ano, metrics)
        total_gravado += 1

    logger.info(
        "Atlas de diversidade: %d linhas (município x ano) gravadas%s.",
        total_gravado, f" para UF={uf.upper()}" if uf else "",
    )
    return total_gravado


def main() -> None:
    # cwd só é forçado para backend/ na execução direta como script (CLI) —
    # nunca ao importar este módulo (ver tests/test_backend_atlas.py, que
    # carrega esta função via importlib): um os.chdir() a nível de módulo
    # mudaria o cwd do processo inteiro do pytest, vazando para qualquer
    # teste rodado depois e quebrando a resolução de backend/.env
    # (Settings.env_file=".env", relativo ao cwd) de outros testes que não
    # mockam explicitamente cada variável (achado real: derrubava
    # dev_auth_bypass_email para "ligado" em testes que não esperavam isso).
    os.chdir(BACKEND_DIR)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uf", help="Processa só uma UF (default: Brasil inteiro).")
    args = parser.parse_args()

    init_db()
    build_diversity_atlas(uf=args.uf)


if __name__ == "__main__":
    main()
