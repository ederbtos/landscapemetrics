import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

@pytest.fixture(params=["asyncio"])
def anyio_backend():
    return "asyncio"

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
    payload = {
        "email": "test@example.com",
        "password": "secret123",
        "password_confirm": "secret123",
    }
    await client.post("/api/auth/register", json=payload)
    login_res = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "secret123"})
    return login_res.json()["access_token"]

@pytest.mark.anyio
async def test_markov_predict_missing_files(test_client):
    token = await _register_user(test_client)
    headers = {"Authorization": f"Bearer {token}"}
    files = [
        ("tif_files", ("raster_2010.tif", b"dummy content", "image/tiff"))
    ]
    response = await test_client.post("/api/markov/predict", headers=headers, files=files, data={"target_years": "2030"})
    assert response.status_code == 400
    assert "pelo menos dois arquivos" in response.json()["detail"]

@pytest.mark.anyio
async def test_markov_predict_invalid_target_years(test_client):
    token = await _register_user(test_client)
    headers = {"Authorization": f"Bearer {token}"}
    files = [
        ("tif_files", ("raster_2010.tif", b"dummy content", "image/tiff")),
        ("tif_files", ("raster_2020.tif", b"dummy content", "image/tiff"))
    ]
    response = await test_client.post("/api/markov/predict", headers=headers, files=files, data={"target_years": "abc"})
    assert response.status_code == 400
    assert "Nenhum ano alvo" in response.json()["detail"]

@pytest.mark.anyio
async def test_markov_predict_invalid_filenames(test_client):
    token = await _register_user(test_client)
    headers = {"Authorization": f"Bearer {token}"}
    files = [
        ("tif_files", ("raster_abc.tif", b"dummy content", "image/tiff")),
        ("tif_files", ("raster_xyz.tif", b"dummy content", "image/tiff"))
    ]
    response = await test_client.post("/api/markov/predict", headers=headers, files=files, data={"target_years": "2030"})
    assert response.status_code == 400
    assert "Não foi possível identificar o ano" in response.json()["detail"]


@pytest.mark.anyio
async def test_markov_predict_real_files_end_to_end(test_client):
    """Regressão: as 3 verificações acima só cobrem validação de entrada
    (erro 400) — nenhuma delas chegava no caminho real de extração/predição,
    que tinha um `NameError: name 'np' is not defined` (numpy nunca era
    importado neste arquivo, só usado via `np.unique`) e só apareceria com
    2+ GeoTIFFs válidos de anos distintos, o uso real do endpoint."""
    from tests.helpers import make_test_tif

    token = await _register_user(test_client)
    headers = {"Authorization": f"Bearer {token}"}
    tif_2010 = make_test_tif(fill_value=3, width=20, height=20)
    tif_2020 = make_test_tif(fill_value=15, width=20, height=20)
    files = [
        ("tif_files", ("raster_2010.tif", tif_2010, "image/tiff")),
        ("tif_files", ("raster_2020.tif", tif_2020, "image/tiff")),
    ]
    response = await test_client.post(
        "/api/markov/predict", headers=headers, files=files, data={"target_years": "2030"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ultimo_ano_observado"] == 2020
    assert data["anos_alvo"] == [2030]
    assert len(data["historico"]) == 2
    assert "2030" in data["predicoes"] or 2030 in data["predicoes"]


@pytest.mark.anyio
async def test_markov_predict_with_custom_shapefile_roi(test_client):
    """Área de interesse alternativa a ponto+buffer/município: shapefile
    próprio (`shp_files`), mesma opção adicionada em /api/metrics/calculate
    (ver landscape_core.uploaded_shapefile_to_region_geojson) — cada GeoTIFF
    do lote é recortado pela mesma área antes de entrar na matriz de
    transição."""
    from tests.helpers import make_test_tif
    from tests.test_backend_api_metrics_shapefile_roi import _polygon_shapefile_zip_bytes

    token = await _register_user(test_client)
    headers = {"Authorization": f"Bearer {token}"}
    shp_bytes = _polygon_shapefile_zip_bytes()
    files = [
        ("tif_files", ("raster_2010.tif", make_test_tif(fill_value=3), "image/tiff")),
        ("tif_files", ("raster_2020.tif", make_test_tif(fill_value=15), "image/tiff")),
        ("shp_files", ("area.zip", shp_bytes, "application/zip")),
    ]
    response = await test_client.post(
        "/api/markov/predict", headers=headers, files=files,
        data={"target_years": "2030"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ultimo_ano_observado"] == 2020
    assert len(data["historico"]) == 2
