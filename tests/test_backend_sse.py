"""
Testes de `_build_sse_matrix` em `backend/app/api/routes/sse.py` — agrega o
histórico salvo em `backend/app/db/metric_results.py` numa matriz
multivariada (uma linha por análise). Ver "Matriz socioecológica (SSE)" no
ROADMAP.md.

Portadas de tests/test_app_sse.py (app.py Streamlit, removido) — diferente
de Markov/município-em-lote, essa feature JÁ tinha sido propriamente
reimplementada no backend (`sse.py::_build_sse_matrix`, usada pelas rotas
`/api/sse/matrix` e `/cluster/*`), só sem teste unitário direto até agora
(só indiretamente via `import app`). Escrever este teste revelou uma
regressão real: `_build_sse_matrix` tinha reimplementado o pivô por classe
errado (iterava nomes de MÉTRICA e pegava só `.iloc[0]`, descartando toda
classe além da primeira) — corrigido nesta sessão para pivotar
`proportion_of_landscape` em colunas `pct_{classe}`, igual à versão antiga.
Métricas de paisagem continuam com prefixo `landscape_` (mudança de estilo
deliberada em relação ao `SHDI`/`short label` antigo, não um bug).

`_render_sse_matrix_section` (renderização Streamlit da matriz + heatmap de
correlação) não tem equivalente no backend — o frontend novo renderiza isso
no cliente — não portada.
"""
import math
import sys
from pathlib import Path

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.routes import sse as sse_routes
from app.db import metric_results as metric_results_db


class _FakeSettings:
    def __init__(self, db_path: str):
        self.db_path = db_path


@pytest.fixture
def sse_db(tmp_path, monkeypatch):
    fake_settings = _FakeSettings(str(tmp_path / "test_sse.db"))
    monkeypatch.setattr(metric_results_db, "get_settings", lambda: fake_settings)

    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(fake_settings.db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE metric_results (
                user_email TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                label TEXT NOT NULL,
                data_source TEXT NOT NULL,
                point_lon REAL,
                point_lat REAL,
                buffer_dist REAL,
                class_metrics_json TEXT NOT NULL,
                landscape_metrics_json TEXT NOT NULL,
                metric_names_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                municipio_codigo TEXT,
                municipio_nome TEXT,
                municipio_uf TEXT,
                ano INTEGER,
                PRIMARY KEY (user_email, fingerprint)
            )
            """
        )
        conn.commit()
    return fake_settings


def _class_metrics_df(class_props: dict) -> pd.DataFrame:
    return pd.DataFrame(
        {"proportion_of_landscape": list(class_props.values())},
        index=list(class_props.keys()),
    )


def test_build_sse_matrix_empty_when_no_history(sse_db):
    assert sse_routes._build_sse_matrix("user@example.com").empty


def test_build_sse_matrix_one_row_per_saved_analysis(sse_db):
    df = _class_metrics_df({"Floresta": 60.0, "Pastagem": 40.0})
    metric_results_db.save_metric_result(
        "user@example.com", "fp1", "Goiânia/GO", "MapBiomas (Google Earth Engine)",
        None, None, df, {"shannon_diversity_index": 0.9},
        municipio_codigo="5208707", municipio_nome="Goiânia", municipio_uf="GO", ano=2020,
    )

    matrix = sse_routes._build_sse_matrix("user@example.com")

    assert len(matrix) == 1
    row = matrix.iloc[0]
    assert row["pct_Floresta"] == pytest.approx(60.0)
    assert row["pct_Pastagem"] == pytest.approx(40.0)
    assert row["municipio_nome"] == "Goiânia"
    assert row["municipio_codigo"] == "5208707"
    assert row["ano"] == 2020
    assert row["landscape_shannon_diversity_index"] == pytest.approx(0.9)


def test_build_sse_matrix_fills_missing_class_columns_with_zero(sse_db):
    df1 = _class_metrics_df({"Floresta": 100.0})
    df2 = _class_metrics_df({"Pastagem": 100.0})
    metric_results_db.save_metric_result(
        "user@example.com", "fp1", "a", "MapBiomas (Google Earth Engine)", None, None, df1, {},
    )
    metric_results_db.save_metric_result(
        "user@example.com", "fp2", "b", "MapBiomas (Google Earth Engine)", None, None, df2, {},
    )

    matrix = sse_routes._build_sse_matrix("user@example.com")

    assert len(matrix) == 2
    assert "pct_Floresta" in matrix.columns and "pct_Pastagem" in matrix.columns
    assert set(matrix["pct_Floresta"]) == {0.0, 100.0}
    assert set(matrix["pct_Pastagem"]) == {0.0, 100.0}
    assert not matrix["pct_Floresta"].isna().any()


def test_build_sse_matrix_scoped_per_user(sse_db):
    df = _class_metrics_df({"Floresta": 100.0})
    metric_results_db.save_metric_result(
        "user1@example.com", "fp1", "a", "MapBiomas (Google Earth Engine)", None, None, df, {},
    )

    assert sse_routes._build_sse_matrix("user1@example.com").shape[0] == 1
    assert sse_routes._build_sse_matrix("user2@example.com").empty


# --- Teste de regressão HTTP: NaN em landscape_metrics quebrava GET
# /api/sse/matrix com 500 "Out of range float values are not JSON compliant"
# (JSONResponse do Starlette usa allow_nan=False) — mesmo bug já corrigido
# em /api/metrics/calculate e /api/municipio-batch/run (sanitize_for_json),
# mas até agora não replicado em sse.py. Município pequeno/paisagem com
# poucas classes gera NaN real no contágio (PyLandStats), então isso não é
# um caso sintético raro — é o que o usuário viu em produção.


@pytest.fixture
async def sse_http_client(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DB_PATH", str(tmp_path / "sse_http_test.db"))
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-change-me")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())

    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]

    from app.main import app  # type: ignore
    from app.db.schema import init_db

    init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=True) as client:
        yield client


@pytest.mark.anyio
async def test_sse_matrix_route_survives_nan_landscape_metric(sse_http_client: AsyncClient):
    from app.db import metric_results as live_metric_results_db

    payload = {"email": "sse-nan@example.com", "password": "secret123", "password_confirm": "secret123"}
    register = await sse_http_client.post("/api/auth/register", json=payload)
    assert register.status_code == 200
    token = register.json()["access_token"]

    df = _class_metrics_df({"Floresta": 100.0})
    live_metric_results_db.save_metric_result(
        "sse-nan@example.com", "fp-nan", "Município pequeno/GO",
        "MapBiomas (Google Earth Engine)", None, None, df,
        {"shannon_diversity_index": 0.0, "contagion_index": math.nan},
    )

    response = await sse_http_client.get(
        "/api/sse/matrix", headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    record = response.json()["records"][0]
    assert record["landscape_contagion_index"] is None
    assert record["landscape_shannon_diversity_index"] == pytest.approx(0.0)
