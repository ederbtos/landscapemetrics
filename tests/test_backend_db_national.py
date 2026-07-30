"""
Testes dos módulos novos de dados de referência nacionais do backend
(`backend/app/db/municipios.py`, `mapbiomas_stats.py`, `prodes.py`,
`ana_hidroclimatica.py`) — malha municipal, MapBiomas agregado, PRODES e ANA
(ver ROADMAP.md, seção de pré-carga de dados nacionais). Cada teste usa um
SQLite isolado em `tmp_path` (nunca toca em `data/app.db` real), mesmo
espírito de `tests/test_backend_db_auth.py`.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.db import ana_hidroclimatica, mapbiomas_stats, municipios, prodes

MODULES_COM_DB_PATH = (municipios, mapbiomas_stats, prodes, ana_hidroclimatica)


class _FakeSettings:
    def __init__(self, db_path: str):
        self.db_path = db_path


@pytest.fixture
def national_db(tmp_path, monkeypatch):
    """Aponta os 4 módulos novos para um SQLite isolado e cria as tabelas."""
    fake_settings = _FakeSettings(str(tmp_path / "test_national.db"))
    for module in MODULES_COM_DB_PATH:
        monkeypatch.setattr(module, "get_settings", lambda: fake_settings)

    municipios.init_municipios_table()
    mapbiomas_stats.init_mapbiomas_stats_table()
    prodes.init_prodes_table()
    ana_hidroclimatica.init_ana_hidroclimatica_tables()
    return fake_settings


def _sample_geojson():
    return (
        '{"type": "FeatureCollection", "features": [{"type": "Feature", '
        '"properties": {"codarea": "4205407"}, "geometry": {"type": "Polygon", '
        '"coordinates": [[[-48.6, -27.6], [-48.5, -27.6], [-48.5, -27.5], [-48.6, -27.5], [-48.6, -27.6]]]}}]}'
    )


# --- municipios.py ---------------------------------------------------------

def test_save_and_get_municipio_malha_roundtrip(national_db):
    municipios.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson(), populacao_estimada=500973)

    result = municipios.get_municipio_malha("4205407")

    assert result["nome"] == "Florianópolis"
    assert result["uf"] == "SC"
    assert result["populacao_estimada"] == 500973
    assert "FeatureCollection" in result["geojson"]


def test_get_municipio_malha_returns_none_when_absent(national_db):
    assert municipios.get_municipio_malha("0000000") is None


def test_save_municipio_malha_upsert_updates_existing(national_db):
    municipios.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson(), populacao_estimada=500973)
    municipios.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson(), populacao_estimada=510000)

    assert municipios.count_municipios() == 1
    assert municipios.get_municipio_malha("4205407")["populacao_estimada"] == 510000


def test_list_municipios_by_uf_filters_correctly(national_db):
    municipios.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson())
    municipios.save_municipio_malha("3550308", "São Paulo", "SP", _sample_geojson())

    resultado = municipios.list_municipios_by_uf("SC")

    assert [m["codigo_ibge"] for m in resultado] == ["4205407"]


def test_all_municipio_codes_returns_every_code(national_db):
    municipios.save_municipio_malha("4205407", "Florianópolis", "SC", _sample_geojson())
    municipios.save_municipio_malha("3550308", "São Paulo", "SP", _sample_geojson())

    assert set(municipios.all_municipio_codes()) == {"4205407", "3550308"}


# --- mapbiomas_stats.py -----------------------------------------------------

def test_save_and_get_serie_municipio(national_db):
    mapbiomas_stats.save_mapbiomas_stat("4205407", 2020, 3, "Formacao florestal", 1200.5, "gee_reduceregions")
    mapbiomas_stats.save_mapbiomas_stat("4205407", 2020, 15, "Pastagem", 800.0, "gee_reduceregions")
    mapbiomas_stats.save_mapbiomas_stat("4205407", 2021, 3, "Formacao florestal", 1150.0, "gee_reduceregions")

    serie = mapbiomas_stats.get_serie_municipio("4205407")

    assert len(serie) == 3
    assert mapbiomas_stats.anos_disponiveis("4205407") == [2020, 2021]


def test_save_mapbiomas_stat_upsert_on_same_municipio_ano_classe(national_db):
    mapbiomas_stats.save_mapbiomas_stat("4205407", 2020, 3, "Formacao florestal", 1200.5, "gee_reduceregions")
    mapbiomas_stats.save_mapbiomas_stat("4205407", 2020, 3, "Formacao florestal", 1300.0, "excel_import")

    serie = mapbiomas_stats.get_serie_municipio("4205407")

    assert len(serie) == 1
    assert serie[0]["area_ha"] == 1300.0


def test_get_serie_municipio_empty_when_not_ingested(national_db):
    assert mapbiomas_stats.get_serie_municipio("9999999") == []


# --- prodes.py ---------------------------------------------------------------

def test_save_and_list_prodes_by_municipio(national_db):
    prodes.save_prodes_feature("cerrado", "feat-1", "4205407", 2020, 1.5, '{"type": "Point"}')
    prodes.save_prodes_feature("amazonia", "feat-2", "4205407", 2021, 2.5, None)

    registros = prodes.list_prodes_by_municipio("4205407")

    assert len(registros) == 2
    assert {r["bioma"] for r in registros} == {"cerrado", "amazonia"}


def test_save_prodes_feature_upsert_by_bioma_and_feature_id(national_db):
    prodes.save_prodes_feature("cerrado", "feat-1", "4205407", 2020, 1.5, None)
    prodes.save_prodes_feature("cerrado", "feat-1", "4205407", 2020, 9.9, None)

    registros = prodes.list_prodes_by_municipio("4205407")

    assert len(registros) == 1
    assert registros[0]["area_km2"] == 9.9


def test_prodes_municipio_codigo_nullable_when_join_fails(national_db):
    prodes.save_prodes_feature("pantanal", "feat-3", None, 2022, 3.0, None)

    assert prodes.count_by_bioma() == {"pantanal": 1}
    assert prodes.list_prodes_by_municipio("4205407") == []


def test_count_by_bioma_groups_correctly(national_db):
    prodes.save_prodes_feature("cerrado", "feat-1", "4205407", 2020, 1.0, None)
    prodes.save_prodes_feature("cerrado", "feat-2", "4205407", 2021, 1.0, None)
    prodes.save_prodes_feature("pampa", "feat-3", None, 2020, 1.0, None)

    assert prodes.count_by_bioma() == {"cerrado": 2, "pampa": 1}


# --- ana_hidroclimatica.py ---------------------------------------------------

def test_save_estacao_and_list_by_municipio(national_db):
    ana_hidroclimatica.save_estacao("87382000", "Rio Itajaí", -27.1, -48.9, "SC", "4205407", "fluviometrica")

    estacoes = ana_hidroclimatica.list_estacoes_by_municipio("4205407")

    assert len(estacoes) == 1
    assert estacoes[0]["nome"] == "Rio Itajaí"


def test_save_serie_ponto_and_get_serie_estacao(national_db):
    ana_hidroclimatica.save_estacao("87382000", "Rio Itajaí", -27.1, -48.9, "SC", "4205407", "fluviometrica")
    ana_hidroclimatica.save_serie_ponto("87382000", "2020-01-01", 120.5, 350.0, 15.2, "consistido")
    ana_hidroclimatica.save_serie_ponto("87382000", "2020-01-02", 118.0, 348.0, 0.0, "consistido")

    serie = ana_hidroclimatica.get_serie_estacao("87382000")

    assert len(serie) == 2
    assert serie[0]["data"] == "2020-01-01"


def test_save_serie_ponto_upsert_by_estacao_and_data(national_db):
    ana_hidroclimatica.save_serie_ponto("87382000", "2020-01-01", 120.5, 350.0, 15.2, "bruto")
    ana_hidroclimatica.save_serie_ponto("87382000", "2020-01-01", 121.0, 351.0, 15.2, "consistido")

    serie = ana_hidroclimatica.get_serie_estacao("87382000")

    assert len(serie) == 1
    assert serie[0]["consistencia"] == "consistido"


def test_list_estacoes_by_municipio_empty_when_none(national_db):
    assert ana_hidroclimatica.list_estacoes_by_municipio("0000000") == []
