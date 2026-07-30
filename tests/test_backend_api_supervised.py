"""
Testes de `POST /api/supervised/train`
(`backend/app/api/routes/supervised.py`) — nenhum teste existia contra a
rota em si (só contra `supervised_models.py`, o serviço, via
`tests/test_supervised.py`). Escrever este teste revelou uma regressão
real: a rota chamava `_build_sse_matrix(current_user)` sem importar essa
função de `app.api.routes.sse` — quebrava com `NameError` em toda e
qualquer chamada, não só num caso de borda.
"""
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
async def test_client(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DB_PATH", str(tmp_path / "backend_test.db"))
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


async def _register_user(client: AsyncClient) -> str:
    payload = {"email": "test@example.com", "password": "secret123", "password_confirm": "secret123"}
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 200
    return response.json()["access_token"]


def _class_metrics_df(class_props: dict):
    import pandas as pd

    return pd.DataFrame(
        {"proportion_of_landscape": list(class_props.values())},
        index=list(class_props.keys()),
    )


@pytest.mark.anyio
async def test_supervised_train_requires_at_least_4_saved_analyses(test_client: AsyncClient):
    token = await _register_user(test_client)
    response = await test_client.post(
        "/api/supervised/train",
        headers={"Authorization": f"Bearer {token}"},
        json={"feature_cols": ["pct_Floresta"], "target_col": "landscape_shannon_diversity_index"},
    )
    assert response.status_code == 400
    assert "pelo menos 4 análises" in response.json()["detail"]


@pytest.mark.anyio
async def test_supervised_train_real_end_to_end(test_client: AsyncClient):
    from app.db import metric_results as metric_results_db

    token = await _register_user(test_client)
    samples = [
        ({"Floresta": 90.0, "Pastagem": 10.0}, 0.3),
        ({"Floresta": 80.0, "Pastagem": 20.0}, 0.4),
        ({"Floresta": 20.0, "Pastagem": 80.0}, 0.9),
        ({"Floresta": 10.0, "Pastagem": 90.0}, 1.0),
    ]
    for i, (props, shdi) in enumerate(samples):
        metric_results_db.save_metric_result(
            "test@example.com", f"fp{i}", f"analise {i}", "MapBiomas (Google Earth Engine)",
            None, None, _class_metrics_df(props), {"shannon_diversity_index": shdi},
        )

    response = await test_client.post(
        "/api/supervised/train",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "feature_cols": ["pct_Floresta", "pct_Pastagem"],
            "target_col": "landscape_shannon_diversity_index",
            "model_name": "random_forest",
            "n_splits": 2,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "f1_score" in data
    assert "confusion_matrix" in data
    assert "permutation_importance" in data
