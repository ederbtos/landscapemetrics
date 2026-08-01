"""
Testes do Atlas Nacional de Paisagem — Fase 0 (Diversidade):
- `app.services.diversity_atlas` (cálculo puro, valores sintéticos conhecidos)
- `scripts/build_diversity_atlas.py` (agregação de `mapbiomas_municipio_stats`
  -> `diversity_atlas_municipio`, 100% offline)
- `api/routes/atlas.py` — a ÚNICA superfície da API deliberadamente pública
  (sem login), ver docstring da rota.
"""
import importlib.util
import math
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import diversity_atlas  # noqa: E402


# --- Cálculo puro (sem DB/HTTP) ---


def test_diversity_indices_from_proportions_single_class_has_zero_shdi():
    values = diversity_atlas.landscape_core.diversity_indices_from_proportions([1.0])
    assert values["patch_richness"] == 1
    assert values["shannon_diversity_index"] == 0.0
    assert values["shannon_evenness_index"] is None  # ln(1) = 0 no denominador -> None


def test_diversity_indices_from_proportions_two_equal_classes_matches_ln2():
    values = diversity_atlas.landscape_core.diversity_indices_from_proportions([0.5, 0.5])
    assert values["shannon_diversity_index"] == pytest.approx(math.log(2), rel=1e-9)
    assert values["shannon_evenness_index"] == pytest.approx(1.0, rel=1e-9)  # uniforme -> SHEI=1
    assert values["simpson_diversity_index"] == pytest.approx(0.5, rel=1e-9)


def test_compute_diversity_metrics_empty_area_returns_none():
    assert diversity_atlas.compute_diversity_metrics({}) is None
    assert diversity_atlas.compute_diversity_metrics({15: 0.0}) is None


def test_compute_diversity_metrics_classifies_dominant_and_macro_categories():
    # 3=Formação florestal (natural), 15=Pastagem (antrópico), 33=Rio/lago/oceano (água)
    metrics = diversity_atlas.compute_diversity_metrics({3: 70.0, 15: 20.0, 33: 10.0})
    assert metrics["classe_dominante_codigo"] == 3
    assert metrics["classe_dominante_pct"] == pytest.approx(70.0)
    assert metrics["area_natural_pct"] == pytest.approx(70.0)
    assert metrics["area_antropizada_pct"] == pytest.approx(20.0)
    assert metrics["area_agua_pct"] == pytest.approx(10.0)
    assert metrics["patch_richness"] == 3


def test_compute_trend_negative_means_loss_of_natural_area():
    trend = diversity_atlas.compute_trend(area_natural_pct_inicio=80.0, area_natural_pct_fim=50.0)
    assert trend["variacao_area_natural_pp"] == pytest.approx(-30.0)


# --- Fixture de app/DB (mesmo padrão de test_backend_api_metrics_shapefile_roi.py) ---


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


def _municipio_geojson(codigo: str, lon: float, lat: float) -> str:
    import json

    delta = 0.05
    ring = [
        [lon - delta, lat - delta], [lon + delta, lat - delta],
        [lon + delta, lat + delta], [lon - delta, lat + delta],
        [lon - delta, lat - delta],
    ]
    return json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"codigo_ibge": codigo},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }],
    })


def _load_build_diversity_atlas_module():
    """Carrega `scripts/build_diversity_atlas.py` como módulo novo a cada
    chamada (em vez de `import scripts.build_diversity_atlas`), para que seu
    `from app.db.diversity_atlas import ...` de topo resolva sempre contra o
    `app.*` fresco do `test_client` da vez (que reimporta `app.*` a cada
    teste, ligado ao `DB_PATH` daquele teste) — um import com cache normal
    prenderia a função num `app.db.diversity_atlas` (e portanto num
    `DB_PATH`) de um teste anterior."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_diversity_atlas.py"
    spec = importlib.util.spec_from_file_location("build_diversity_atlas_under_test", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_atlas_fixture_data():
    """Dois municípios sintéticos em SC, cobertura em 2004 e 2023 — um perde
    metade da floresta para pastagem, o outro fica estável. Usa os módulos
    de DB já existentes (mesmo padrão de scripts/seed_mapbiomas_stats.py)."""
    from app.db import mapbiomas_stats as mapbiomas_stats_db
    from app.db import municipios as municipios_db

    municipios_db.save_municipio_malha("9999999", "Município Desmatado", "SC", _municipio_geojson("9999999", -49.0, -27.0))
    municipios_db.save_municipio_malha("8888888", "Município Estável", "SC", _municipio_geojson("8888888", -49.5, -27.5))

    # 3 = Formação florestal (natural), 15 = Pastagem (antrópico) — ver
    # app.services.diversity_atlas.NATURAL_CLASS_CODES/ANTROPICO_CLASS_CODES.
    dados = [
        ("9999999", 2004, 3, 800.0), ("9999999", 2004, 15, 200.0),
        ("9999999", 2023, 3, 400.0), ("9999999", 2023, 15, 600.0),  # perdeu floresta
        ("8888888", 2004, 3, 500.0), ("8888888", 2004, 15, 500.0),
        ("8888888", 2023, 3, 500.0), ("8888888", 2023, 15, 500.0),  # estável
    ]
    for codigo, ano, classe, area in dados:
        mapbiomas_stats_db.save_mapbiomas_stat(codigo, ano, classe, None, area, "teste")


# --- Rotas públicas (sem Authorization em nenhuma chamada abaixo — de propósito) ---


@pytest.mark.anyio
async def test_atlas_ranking_and_mapa_are_public_and_reflect_seeded_data(test_client: AsyncClient):
    _seed_atlas_fixture_data()
    module = _load_build_diversity_atlas_module()
    gravadas = module.build_diversity_atlas()
    assert gravadas == 4  # 2 municípios x 2 anos

    anos_resp = await test_client.get("/api/atlas/anos-disponiveis")
    assert anos_resp.status_code == 200
    assert anos_resp.json()["anos"] == [2004, 2023]

    ranking_resp = await test_client.get(
        "/api/atlas/ranking", params={"ano": 2023, "metrica": "area_natural_pct", "ordem": "desc"}
    )
    assert ranking_resp.status_code == 200
    municipios = ranking_resp.json()["municipios"]
    assert [m["municipio_codigo"] for m in municipios] == ["8888888", "9999999"]
    assert municipios[0]["municipio_nome"] == "Município Estável"

    mapa_resp = await test_client.get("/api/atlas/mapa", params={"ano": 2023, "metrica": "shannon_diversity_index"})
    assert mapa_resp.status_code == 200
    geojson = mapa_resp.json()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 2
    assert {f["properties"]["codigo_ibge"] for f in geojson["features"]} == {"9999999", "8888888"}


@pytest.mark.anyio
async def test_atlas_ranking_tendencia_ranks_biggest_natural_area_loss_first(test_client: AsyncClient):
    _seed_atlas_fixture_data()
    _load_build_diversity_atlas_module().build_diversity_atlas()

    resp = await test_client.get(
        "/api/atlas/ranking-tendencia", params={"ano_inicio": 2004, "ano_fim": 2023}
    )
    assert resp.status_code == 200
    municipios = resp.json()["municipios"]
    assert municipios[0]["municipio_codigo"] == "9999999"
    assert municipios[0]["variacao_area_natural_pp"] == pytest.approx(-40.0)
    assert municipios[1]["variacao_area_natural_pp"] == pytest.approx(0.0)


@pytest.mark.anyio
async def test_atlas_municipio_profile_includes_series_and_trend(test_client: AsyncClient):
    _seed_atlas_fixture_data()
    _load_build_diversity_atlas_module().build_diversity_atlas()

    resp = await test_client.get("/api/atlas/municipio/9999999")
    assert resp.status_code == 200
    data = resp.json()
    assert [row["ano"] for row in data["serie"]] == [2004, 2023]
    assert data["tendencia"]["variacao_area_natural_pp"] == pytest.approx(-40.0)


@pytest.mark.anyio
async def test_atlas_municipio_profile_404_when_not_yet_computed(test_client: AsyncClient):
    resp = await test_client.get("/api/atlas/municipio/0000000")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_atlas_ranking_rejects_unknown_metrica(test_client: AsyncClient):
    resp = await test_client.get("/api/atlas/ranking", params={"ano": 2023, "metrica": "nao_existe"})
    assert resp.status_code == 400
