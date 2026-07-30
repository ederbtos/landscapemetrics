"""
Testes de `_detect_municipio_columns` em
`backend/app/services/landscape_core.py` — detecção heurística de colunas
código/nome/UF em shapefiles de municípios de fontes variadas.

Portadas de tests/test_app_municipio_batch.py (app.py Streamlit, removido).
Esse arquivo também testava `_municipio_files_to_gdf`/`_run_municipio_batch`/
`_build_municipio_batch_workbook` — o restante do recurso "Métricas por
município em lote via shapefile" (ver ROADMAP.md). Diferente de
`_detect_municipio_columns` (pura, sem dependências), essas três têm
dependências reais que as tornam um esforço de port separado, maior:
`_municipio_files_to_gdf` chama `uploaded_file_to_gdf` (nunca extraída para
landscape_core.py, sem uso em lugar nenhum do backend hoje) e
`_run_municipio_batch` chama `db.get_metric_result`/`save_metric_result` (o
`db.py` legado, removido — precisaria ser religado a
`backend/app/db/metric_results.py`). Nenhuma rota do backend expõe esse
recurso hoje — fica descoberto por este refactor, não é escopo dele
reconstruir. Ver ROADMAP.md.
"""
import sys
from pathlib import Path

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import landscape_core


def test_detect_municipio_columns_ibge_standard_names():
    df = pd.DataFrame(columns=["CD_MUN", "NM_MUN", "SIGLA_UF", "geometry"])

    detected = landscape_core._detect_municipio_columns(df)

    assert detected == {"codigo": "CD_MUN", "nome": "NM_MUN", "uf": "SIGLA_UF"}


def test_detect_municipio_columns_case_insensitive():
    df = pd.DataFrame(columns=["cd_mun", "nm_mun", "sigla_uf"])

    detected = landscape_core._detect_municipio_columns(df)

    assert detected == {"codigo": "cd_mun", "nome": "nm_mun", "uf": "sigla_uf"}


def test_detect_municipio_columns_no_match_returns_none():
    df = pd.DataFrame(columns=["foo", "bar"])

    detected = landscape_core._detect_municipio_columns(df)

    assert detected == {"codigo": None, "nome": None, "uf": None}
