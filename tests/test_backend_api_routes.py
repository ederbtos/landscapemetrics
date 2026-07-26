import os
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _sample_geojson():
    return (
        '{"type": "FeatureCollection", "features": [{"type": "Feature", '
        '"properties": {"codarea": "4205407"}, "geometry": {"type": "Polygon", '
        '"coordinates": [[[-48.6, -27.6], [-48.5, -27.6], [-48.5, -27.5], [-48.6, -27.5], [-48.6, -27.6]]]}}]}'
    )


@pytest.fixture
async def test_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "backend_test.db"))
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-change-me")
    monkeypatch.setenv(
        "APP_ENCRYPTION_KEY",
        "dGVzdF9rZXlfZGV2X29ubHlfZm9yX2xvY2FsX3VzZV8xMjM0NQ==",
    )

    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]

    from app.main import app  # type: ignore
    from app.db.schema import init_db

    init_db()

    async with AsyncClient(app=app, base_url="http://testserver", follow_redirects=True) as client:
        yield client


async def _register_user(client: AsyncClient) -> str:
    payload = {
        "email": "test@example.com",
        "password": "secret123",
        "password_confirm": "secret123",
    }
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    return data["access_token"]


@pytest.mark.anyio
def test_health_route(test_client: AsyncClient):
    response = await test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
def test_ibge_ufs_route(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ibge as ibge_routes

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"sigla": "SC", "nome": "Santa Catarina"},
                {"sigla": "SP", "nome": "São Paulo"},
            ]

    monkeypatch.setattr(ibge_routes.requests, "get", lambda *args, **kwargs: FakeResponse())

    response = await test_client.get("/api/ibge/ufs")
    assert response.status_code == 200
    assert response.json() == [
        {"sigla": "SC", "nome": "Santa Catarina"},
        {"sigla": "SP", "nome": "São Paulo"},
    ]


@pytest.mark.anyio
def test_ibge_malha_route_uses_cache(test_client: AsyncClient):
    import app.db.municipios as municipios_db

    municipios_db.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson())

    response = await test_client.get("/api/ibge/municipios/4205407/malha")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert payload["features"][0]["properties"]["codarea"] == "4205407"


@pytest.mark.anyio
def test_prodes_route_requires_auth(test_client: AsyncClient):
    response = await test_client.get("/api/prodes/municipio/4205407")
    assert response.status_code == 401


@pytest.mark.anyio
def test_prodes_route_returns_data_with_valid_token(monkeypatch, test_client: AsyncClient):
    import app.api.routes.prodes as prodes_routes

    token = _register_user(test_client)

    monkeypatch.setattr(
        prodes_routes.prodes_db,
        "list_prodes_by_municipio",
        lambda codigo: [{"bioma": "cerrado", "ano_deteccao": 2020, "area_km2": 1.5}],
    )

    response = test_client.get(
        "/api/prodes/municipio/4205407",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "municipio_codigo": "4205407",
        "registros": [{"bioma": "cerrado", "ano_deteccao": 2020, "area_km2": 1.5}],
    }


@pytest.mark.anyio
def test_mapbiomas_route_requires_auth(test_client: AsyncClient):
    response = await test_client.get("/api/mapbiomas/serie/4205407")
    assert response.status_code == 401


@pytest.mark.anyio
def test_mapbiomas_route_returns_data_with_valid_token(monkeypatch, test_client: AsyncClient):
    import app.api.routes.mapbiomas_stats as mapbiomas_routes

    token = _register_user(test_client)

    monkeypatch.setattr(
        mapbiomas_routes.mapbiomas_stats_db,
        "anos_disponiveis",
        lambda codigo: [2020, 2021],
    )
    monkeypatch.setattr(
        mapbiomas_routes.mapbiomas_stats_db,
        "get_serie_municipio",
        lambda codigo: [
            {"ano": 2020, "classe_codigo": 3, "classe_nome": "Floresta", "area_ha": 1200.5}
        ],
    )

    response = test_client.get(
        "/api/mapbiomas/serie/4205407",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "municipio_codigo": "4205407",
        "anos_disponiveis": [2020, 2021],
        "serie": [
            {"ano": 2020, "classe_codigo": 3, "classe_nome": "Floresta", "area_ha": 1200.5}
        ],
    }


@pytest.mark.anyio
def test_ana_route_requires_auth(test_client: AsyncClient):
    response = await test_client.get("/api/ana/estacoes", params={"municipio_codigo": "4205407"})
    assert response.status_code == 401


@pytest.mark.anyio
def test_ana_routes_return_data_with_valid_token(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ana_hidroclimatica as ana_routes

    token = _register_user(test_client)

    monkeypatch.setattr(
        ana_routes.ana_db,
        "list_estacoes_by_municipio",
        lambda codigo: [{"codigo": "87382000", "nome": "Rio Teste", "lat": -27.1, "lon": -48.9, "tipo": "fluviometrica"}],
    )
    monkeypatch.setattr(
        ana_routes.ana_db,
        "get_serie_estacao",
        lambda codigo: [
            {"data": "2020-01-01", "vazao_m3s": 120.5, "nivel_cm": 350.0, "chuva_mm": 15.2, "consistencia": "consistido"}
        ],
    )

    response = test_client.get(
        "/api/ana/estacoes",
        params={"municipio_codigo": "4205407"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "codigo": "87382000",
            "nome": "Rio Teste",
            "lat": -27.1,
            "lon": -48.9,
            "tipo": "fluviometrica",
        }
    ]

    response = test_client.get(
        "/api/ana/serie/87382000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "estacao_codigo": "87382000",
        "serie": [
            {
                "data": "2020-01-01",
                "vazao_m3s": 120.5,
                "nivel_cm": 350.0,
                "chuva_mm": 15.2,
                "consistencia": "consistido",
            }
        ],
    }
