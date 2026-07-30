"""
Testes de `POST /api/municipio-batch/run`
(`backend/app/api/routes/municipio_batch.py`) — "Métricas por Município em
Lote (via shapefile)". Essa rota nunca existira no backend novo: a lógica
pura (`_municipio_files_to_gdf`/`_detect_municipio_columns`/etc.) só foi
movida para `landscape_core.py` sem endpoint/UI própria durante a migração
do Streamlit (ver ROADMAP.md) — esta sessão fecha essa lacuna, a pedido do
usuário.
"""
import os
import sys
import tempfile
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


def _municipios_gdf_for_test_raster():
    """Monta um GeoDataFrame (EPSG:4326) com 3 'municípios': 2 pequenos
    quadrados dentro da extensão do raster de `make_test_tif` (UTM 23S,
    canto (200000, 8200000), 50x50 px de 30m) e 1 bem fora dela — cobre
    tanto o caminho de sucesso quanto o isolamento de erro por município."""
    import geopandas as gpd
    from pyproj import Transformer
    from shapely.geometry import box

    transformer = Transformer.from_crs("EPSG:32723", "EPSG:4326", always_xy=True)
    minx, miny = transformer.transform(200200, 8198700)
    maxx, maxy = transformer.transform(201300, 8199800)

    midx = (minx + maxx) / 2
    municipio_a = box(minx, miny, midx, maxy)
    municipio_b = box(midx, miny, maxx, maxy)
    municipio_fora = box(10.0, 10.0, 10.1, 10.1)  # Golfo da Guiné — nada a ver com o raster

    return gpd.GeoDataFrame(
        {
            "CD_MUN": ["1111111", "2222222", "3333333"],
            "NM_MUN": ["Município A", "Município B", "Município Fora"],
            "SIGLA_UF": ["GO", "GO", "GO"],
        },
        geometry=[municipio_a, municipio_b, municipio_fora],
        crs="EPSG:4326",
    )


def _shapefile_components_as_files(gdf) -> list:
    """Grava `gdf` como shapefile via fiona e devolve os componentes
    (.shp/.shx/.dbf/.prj) como tuplas prontas para o parâmetro `files=` do
    httpx — simula o usuário selecionando todos os arquivos soltos de uma
    vez no seletor do navegador, sem passar pelo caminho `.zip`."""
    import fiona

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = os.path.join(tmpdir, "municipios.shp")
        schema = {
            "geometry": "Polygon",
            "properties": {col: "str" for col in gdf.columns if col != "geometry"},
        }
        with fiona.open(shp_path, "w", driver="ESRI Shapefile", schema=schema, crs=str(gdf.crs)) as dst:
            for _, row in gdf.iterrows():
                dst.write({
                    "geometry": row.geometry.__geo_interface__,
                    "properties": {col: row[col] for col in gdf.columns if col != "geometry"},
                })

        files = []
        for fname in sorted(os.listdir(tmpdir)):
            with open(os.path.join(tmpdir, fname), "rb") as f:
                files.append(("municipio_files", (fname, f.read(), "application/octet-stream")))
        return files


@pytest.mark.anyio
async def test_municipio_batch_run_real_end_to_end(test_client: AsyncClient):
    from tests.helpers import make_test_tif

    token = await _register_user(test_client)
    gdf = _municipios_gdf_for_test_raster()
    files = _shapefile_components_as_files(gdf)
    files.append(("tif_file", ("cobertura.tif", make_test_tif(fill_value=5), "image/tiff")))

    response = await test_client.post(
        "/api/municipio-batch/run",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_municipios"] == 3
    assert data["sucesso"] == 2
    assert len(data["erros"]) == 1
    assert data["erros"][0]["municipio_codigo"] == "3333333"
    assert {row["municipio_codigo"] for row in data["landscape_rows"]} == {"1111111", "2222222"}
    assert data["colunas_detectadas"] == {"codigo": "CD_MUN", "nome": "NM_MUN", "uf": "SIGLA_UF"}


@pytest.mark.anyio
async def test_municipio_batch_run_reuses_cache_on_second_run(test_client: AsyncClient):
    from tests.helpers import make_test_tif

    token = await _register_user(test_client)
    gdf = _municipios_gdf_for_test_raster()
    tif_bytes = make_test_tif(fill_value=5)

    files_1 = _shapefile_components_as_files(gdf)
    files_1.append(("tif_file", ("cobertura.tif", tif_bytes, "image/tiff")))
    response_1 = await test_client.post(
        "/api/municipio-batch/run", headers={"Authorization": f"Bearer {token}"}, files=files_1,
    )
    assert response_1.status_code == 200
    assert response_1.json()["sucesso"] == 2

    # Segunda rodada: os 2 municípios bem-sucedidos devem vir do cache
    # (mesma fingerprint) — o 3º continua fora da extensão do raster.
    files_2 = _shapefile_components_as_files(gdf)
    files_2.append(("tif_file", ("cobertura.tif", tif_bytes, "image/tiff")))
    response_2 = await test_client.post(
        "/api/municipio-batch/run", headers={"Authorization": f"Bearer {token}"}, files=files_2,
    )
    assert response_2.status_code == 200
    assert response_2.json()["sucesso"] == 2
    assert len(response_2.json()["erros"]) == 1
