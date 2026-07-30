import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

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
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DB_PATH", str(tmp_path / "backend_test.db"))
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-change-me")
    # Precisa ser uma chave Fernet válida de verdade (32 bytes raw, base64
    # url-safe) — o valor legível usado aqui antes NÃO era válido e derrubava
    # qualquer teste que de fato chamasse save/get_credentials com
    # ValueError("Fernet key must be 32 url-safe base64-encoded bytes.").
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
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    return data["access_token"]


@pytest.mark.anyio
async def test_health_route(test_client: AsyncClient):
    response = await test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_ibge_ufs_route(monkeypatch, test_client: AsyncClient):
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
async def test_ibge_municipios_route(monkeypatch, test_client: AsyncClient):
    """Regressão: até esta sessão só `/api/ibge/ufs` e `/malha` tinham teste
    próprio — `/ufs/{uf}/municipios` e `/populacao` (abaixo) nunca tinham sido
    testados diretamente (a cobertura equivalente vivia só em `test_app_ibge.py`,
    que testava as funções homônimas do `app.py` Streamlit, já superadas por
    este router e removidas nesta migração)."""
    import app.api.routes.ibge as ibge_routes

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"id": 5208707, "nome": "Goiânia"},
                {"id": 5201108, "nome": "Abadia de Goiás"},
            ]

    monkeypatch.setattr(ibge_routes.requests, "get", lambda *args, **kwargs: FakeResponse())

    response = await test_client.get("/api/ibge/ufs/GO/municipios")
    assert response.status_code == 200
    # Ordenado por nome, não pela ordem retornada pela API.
    assert response.json() == [
        {"id": "5201108", "nome": "Abadia de Goiás"},
        {"id": "5208707", "nome": "Goiânia"},
    ]


@pytest.mark.anyio
async def test_ibge_populacao_route_returns_parsed_value(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ibge as ibge_routes

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"resultados": [{"series": [{"series": {"2021": "1536097"}}]}]}]

    monkeypatch.setattr(ibge_routes.requests, "get", lambda *args, **kwargs: FakeResponse())

    response = await test_client.get("/api/ibge/municipios/5208707/populacao")
    assert response.status_code == 200
    assert response.json() == {"municipio_codigo": "5208707", "populacao_estimada": 1536097}


@pytest.mark.anyio
async def test_ibge_populacao_route_returns_none_on_failure(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ibge as ibge_routes

    def _raise(*args, **kwargs):
        raise ConnectionError("sem rede")

    monkeypatch.setattr(ibge_routes.requests, "get", _raise)

    response = await test_client.get("/api/ibge/municipios/5208707/populacao")
    assert response.status_code == 200
    assert response.json() == {"municipio_codigo": "5208707", "populacao_estimada": None}


@pytest.mark.anyio
async def test_ibge_populacao_route_uses_cache_and_skips_live_call(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ibge as ibge_routes
    import app.db.municipios as municipios_db

    municipios_db.save_municipio_malha(
        "5208707", "Goiânia", "GO", _sample_geojson(), populacao_estimada=1536097
    )

    def _fail(*args, **kwargs):
        raise AssertionError("não deveria chamar a API ao vivo do IBGE com o cache preenchido")

    monkeypatch.setattr(ibge_routes.requests, "get", _fail)

    response = await test_client.get("/api/ibge/municipios/5208707/populacao")
    assert response.status_code == 200
    assert response.json() == {"municipio_codigo": "5208707", "populacao_estimada": 1536097}


@pytest.mark.anyio
async def test_ibge_populacao_route_falls_back_live_when_cached_value_is_null(
    monkeypatch, test_client: AsyncClient
):
    """Município cacheado (malha existe), mas sem população (ex.: seed rodado
    com --skip-populacao, ou aquele município falhou na consulta SIDRA
    durante o seed) — não deve retornar None sem tentar a chamada ao vivo."""
    import app.api.routes.ibge as ibge_routes
    import app.db.municipios as municipios_db

    municipios_db.save_municipio_malha("5208707", "Goiânia", "GO", _sample_geojson())

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"resultados": [{"series": [{"series": {"2021": "1536097"}}]}]}]

    monkeypatch.setattr(ibge_routes.requests, "get", lambda *args, **kwargs: FakeResponse())

    response = await test_client.get("/api/ibge/municipios/5208707/populacao")
    assert response.status_code == 200
    assert response.json() == {"municipio_codigo": "5208707", "populacao_estimada": 1536097}


@pytest.mark.anyio
async def test_ibge_malha_route_uses_cache(test_client: AsyncClient):
    import app.db.municipios as municipios_db

    municipios_db.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson())

    response = await test_client.get("/api/ibge/municipios/4205407/malha")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert payload["features"][0]["properties"]["codarea"] == "4205407"


@pytest.mark.anyio
async def test_ibge_ufs_route_uses_cache_and_skips_live_call(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ibge as ibge_routes
    import app.db.municipios as municipios_db

    municipios_db.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson())
    municipios_db.save_municipio_malha("5208707", "Goiânia", "GO", _sample_geojson())

    def _fail(*args, **kwargs):
        raise AssertionError("não deveria chamar a API ao vivo do IBGE com o cache preenchido")

    monkeypatch.setattr(ibge_routes.requests, "get", _fail)

    response = await test_client.get("/api/ibge/ufs")
    assert response.status_code == 200
    assert response.json() == [
        {"sigla": "GO", "nome": "Goiás"},
        {"sigla": "SC", "nome": "Santa Catarina"},
    ]


@pytest.mark.anyio
async def test_ibge_municipios_route_uses_cache_and_skips_live_call(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ibge as ibge_routes
    import app.db.municipios as municipios_db

    municipios_db.save_municipio_malha("5208707", "Goiânia", "GO", _sample_geojson())
    municipios_db.save_municipio_malha("5201108", "Abadia de Goiás", "GO", _sample_geojson())

    def _fail(*args, **kwargs):
        raise AssertionError("não deveria chamar a API ao vivo do IBGE com o cache preenchido")

    monkeypatch.setattr(ibge_routes.requests, "get", _fail)

    response = await test_client.get("/api/ibge/ufs/GO/municipios")
    assert response.status_code == 200
    assert response.json() == [
        {"id": "5201108", "nome": "Abadia de Goiás"},
        {"id": "5208707", "nome": "Goiânia"},
    ]


@pytest.mark.anyio
async def test_prodes_route_requires_auth(test_client: AsyncClient):
    response = await test_client.get("/api/prodes/municipio/4205407")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_prodes_route_returns_data_with_valid_token(monkeypatch, test_client: AsyncClient):
    import app.api.routes.prodes as prodes_routes

    token = await _register_user(test_client)

    monkeypatch.setattr(
        prodes_routes.prodes_db,
        "list_prodes_by_municipio",
        lambda codigo: [{"bioma": "cerrado", "ano_deteccao": 2020, "area_km2": 1.5}],
    )

    response = await test_client.get(
        "/api/prodes/municipio/4205407",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "municipio_codigo": "4205407",
        "registros": [{"bioma": "cerrado", "ano_deteccao": 2020, "area_km2": 1.5}],
    }


@pytest.mark.anyio
async def test_mapbiomas_route_requires_auth(test_client: AsyncClient):
    response = await test_client.get("/api/mapbiomas/serie/4205407")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_mapbiomas_route_returns_data_with_valid_token(monkeypatch, test_client: AsyncClient):
    import app.api.routes.mapbiomas_stats as mapbiomas_routes

    token = await _register_user(test_client)

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

    response = await test_client.get(
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
async def test_ana_route_requires_auth(test_client: AsyncClient):
    response = await test_client.get("/api/ana/estacoes", params={"municipio_codigo": "4205407"})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_ana_routes_return_data_with_valid_token(monkeypatch, test_client: AsyncClient):
    import app.api.routes.ana_hidroclimatica as ana_routes

    token = await _register_user(test_client)

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

    response = await test_client.get(
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

    response = await test_client.get(
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


@pytest.mark.anyio
async def test_lgpd_delete_account_removes_all_user_data(test_client: AsyncClient):
    """Regressão: `DELETE /api/lgpd/account` chamava `credentials_db.delete_credentials`
    e `users_db.delete_user`, nenhuma das quais existia — quebrava com
    `AttributeError`/500 em qualquer tentativa real de exclusão de conta (Art.
    18, VI da LGPD). Também cobre as duas lacunas que só apareceram depois de
    corrigir isso: refresh token não revogado e `user_settings` não limpo."""
    from app.db import credentials as credentials_db
    from app.db import user_settings as user_settings_db
    from app.db import users as users_db

    email = "delete-me@example.com"
    token = (
        await test_client.post(
            "/api/auth/register",
            json={"email": email, "password": "secret123", "password_confirm": "secret123"},
        )
    ).json()["access_token"]

    credentials_db.save_credentials(email, {"client_email": "svc@example.com"})
    user_settings_db.save_user_settings(email, {"default_uf": "SC"})
    assert users_db.user_exists(email) is True

    response = await test_client.delete("/api/lgpd/account", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["protocolo_exclusao"].startswith("LGPD-DEL-")

    assert users_db.user_exists(email) is False
    assert credentials_db.get_credentials(email) is None
    # Sem uma linha própria, get_user_settings recai nos defaults de fábrica.
    assert user_settings_db.get_user_settings(email)["default_uf"] == "GO"

    # Refresh token revogado — a sessão não sobrevive à exclusão via F5.
    refresh_response = await test_client.post("/api/auth/refresh")
    assert refresh_response.status_code == 401

    # Conta realmente eliminada, não só desconectada.
    login_response = await test_client.post(
        "/api/auth/login", json={"email": email, "password": "secret123"}
    )
    assert login_response.status_code == 401
