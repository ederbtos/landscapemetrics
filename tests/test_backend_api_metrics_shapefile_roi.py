"""
Testes de `POST /api/metrics/calculate` com a 3ª opção de área de interesse:
um shapefile próprio enviado pelo usuário (`shp_files`), alternativa ao
ponto+buffer e ao município do IBGE — ver `landscape_core
.uploaded_shapefile_to_region_geojson` e `landscape_service
.run_landscape_analysis`.
"""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import fiona
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


def _polygon_shapefile_zip_bytes() -> bytes:
    """Polígono (WGS84) que cobre a extensão do raster sintético de
    `make_test_tif` (UTM 23S, canto (200000, 8200000), 50x50px de 30m) —
    mesmas coordenadas convertidas usadas em
    tests/test_backend_api_municipio_batch.py."""
    from pyproj import Transformer
    from shapely.geometry import box, mapping

    transformer = Transformer.from_crs("EPSG:32723", "EPSG:4326", always_xy=True)
    minx, miny = transformer.transform(200200, 8198700)
    maxx, maxy = transformer.transform(201300, 8199800)
    polygon = box(minx, miny, maxx, maxy)

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = os.path.join(tmpdir, "area.shp")
        schema = {"geometry": "Polygon", "properties": {}}
        with fiona.open(shp_path, "w", driver="ESRI Shapefile", schema=schema, crs="EPSG:4326") as dst:
            dst.write({"geometry": mapping(polygon), "properties": {}})

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for fname in os.listdir(tmpdir):
                zf.write(os.path.join(tmpdir, fname), arcname=fname)
        return buf.getvalue()


@pytest.mark.anyio
async def test_calculate_metrics_with_custom_shapefile_roi(test_client: AsyncClient):
    from tests.helpers import make_test_tif

    token = await _register_user(test_client)

    response = await test_client.post(
        "/api/metrics/calculate",
        headers={"Authorization": f"Bearer {token}"},
        data={"data_source": "geotiff"},
        files=[
            ("shp_files", ("area.zip", _polygon_shapefile_zip_bytes(), "application/zip")),
            ("tif_file", ("cobertura.tif", make_test_tif(fill_value=5), "image/tiff")),
        ],
    )

    assert response.status_code == 200
    data = response.json()
    assert "Área personalizada" in data["label"]
    assert data["class_metrics"]
    assert data["landscape_metrics"]
    assert data["step"] == "metrics_calculated"


@pytest.mark.anyio
async def test_calculate_metrics_with_shapefile_roi_reuses_cache(test_client: AsyncClient):
    from tests.helpers import make_test_tif

    token = await _register_user(test_client)
    shp_bytes = _polygon_shapefile_zip_bytes()
    tif_bytes = make_test_tif(fill_value=5)

    response_1 = await test_client.post(
        "/api/metrics/calculate",
        headers={"Authorization": f"Bearer {token}"},
        data={"data_source": "geotiff"},
        files=[
            ("shp_files", ("area.zip", shp_bytes, "application/zip")),
            ("tif_file", ("cobertura.tif", tif_bytes, "image/tiff")),
        ],
    )
    response_2 = await test_client.post(
        "/api/metrics/calculate",
        headers={"Authorization": f"Bearer {token}"},
        data={"data_source": "geotiff"},
        files=[
            ("shp_files", ("area.zip", shp_bytes, "application/zip")),
            ("tif_file", ("cobertura.tif", tif_bytes, "image/tiff")),
        ],
    )

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert response_1.json()["fingerprint"] == response_2.json()["fingerprint"]


@pytest.mark.anyio
async def test_calculate_metrics_shapefile_roi_without_files_falls_back_to_point_error(test_client: AsyncClient):
    """Sem shp_files nem ponto/município, a fonte GeoTIFF calcula o raster
    inteiro (comportamento pré-existente, inalterado) — só confirma que
    adicionar o parâmetro `shp_files` opcional não quebrou esse caminho."""
    from tests.helpers import make_test_tif

    token = await _register_user(test_client)

    response = await test_client.post(
        "/api/metrics/calculate",
        headers={"Authorization": f"Bearer {token}"},
        data={"data_source": "geotiff"},
        files=[("tif_file", ("cobertura.tif", make_test_tif(fill_value=5), "image/tiff"))],
    )

    assert response.status_code == 200
    assert response.json()["class_metrics"]
