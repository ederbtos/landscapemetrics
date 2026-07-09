"""
Testes dos helpers de integração com a API do IBGE (localidades/malhas/
agregados) e da área de interesse municipal em extract_landscape_from_tif —
ver "Área de interesse por município (IBGE)" no ROADMAP.md.

Nota sobre cache: os helpers `_ibge_get_*` são decorados com @st.cache_data
(mesmo motivo de uploaded_file_to_gdf, ver test_app_validation.py) — os
testes chamam `.__wrapped__` para acessar a função original sem cache.
"""
import numpy as np
import pytest
import requests

import app
from tests.helpers import FakeUploadedFile, make_test_tif


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def test_ibge_get_ufs_returns_parsed_list(monkeypatch):
    fake_ufs = [{"id": 52, "sigla": "GO", "nome": "Goiás"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(fake_ufs))

    result = app._ibge_get_ufs.__wrapped__()

    assert result == fake_ufs


def test_ibge_get_municipios_returns_parsed_list(monkeypatch):
    fake_municipios = [{"id": 5208707, "nome": "Goiânia"}]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(fake_municipios))

    result = app._ibge_get_municipios.__wrapped__("GO")

    assert result == fake_municipios


def _municipio_polygon_geojson():
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-49.3, -16.75], [-49.2, -16.75], [-49.2, -16.6],
                    [-49.3, -16.6], [-49.3, -16.75],
                ]],
            },
        }],
    }


def test_ibge_get_municipio_geojson_returns_feature_collection(monkeypatch):
    fake_geojson = _municipio_polygon_geojson()
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(fake_geojson))

    result = app._ibge_get_municipio_geojson.__wrapped__("5208707")

    assert result == fake_geojson


def test_ibge_get_municipio_geojson_returns_none_on_request_failure(monkeypatch):
    def _raise(*a, **k):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(requests, "get", _raise)

    assert app._ibge_get_municipio_geojson.__wrapped__("5208707") is None


def test_ibge_get_municipio_geojson_returns_none_when_no_features(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse({"type": "FeatureCollection", "features": []}))

    assert app._ibge_get_municipio_geojson.__wrapped__("0000000") is None


def test_ibge_get_populacao_estimada_parses_sidra_response(monkeypatch):
    fake_sidra = [{
        "resultados": [{
            "series": [{
                "serie": {"2024": "1536097"},
            }],
        }],
    }]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(fake_sidra))

    assert app._ibge_get_populacao_estimada.__wrapped__("5208707") == 1536097


def test_ibge_get_populacao_estimada_returns_none_on_unexpected_format(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse({"unexpected": "shape"}))

    assert app._ibge_get_populacao_estimada.__wrapped__("5208707") is None


def test_ibge_get_populacao_estimada_returns_none_on_request_failure(monkeypatch):
    def _raise(*a, **k):
        raise requests.Timeout("demorou demais")

    monkeypatch.setattr(requests, "get", _raise)

    assert app._ibge_get_populacao_estimada.__wrapped__("5208707") is None


def test_municipio_geometry_shapely_extracts_single_feature_geometry():
    geojson = _municipio_polygon_geojson()
    geom = app._municipio_geometry_shapely(geojson)

    assert geom.geom_type == "Polygon"
    minx, miny, maxx, maxy = geom.bounds
    assert minx == pytest.approx(-49.3)
    assert maxx == pytest.approx(-49.2)


def test_extract_landscape_from_tif_crops_by_region_geojson():
    # Raster de teste em UTM 23S cobrindo 1500x1500m a partir de (200000, 8200000).
    tif_bytes = make_test_tif(fill_value=5, width=50, height=50)
    fake = FakeUploadedFile("municipio.tif", tif_bytes)

    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:32723", "EPSG:4326", always_xy=True)
    # Um pequeno polígono bem dentro da extensão do raster de teste.
    lon1, lat1 = transformer.transform(200400, 8199600)
    lon2, lat2 = transformer.transform(201100, 8199600)
    lon3, lat3 = transformer.transform(201100, 8198900)
    lon4, lat4 = transformer.transform(200400, 8198900)
    region_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[lon1, lat1], [lon2, lat2], [lon3, lat3], [lon4, lat4], [lon1, lat1]]],
            },
        }],
    }

    array, resolution, reprojected_bytes = app.extract_landscape_from_tif(
        fake, region_geojson=region_geojson,
    )

    assert resolution == (30.0, 30.0)
    assert array.size > 0
    assert set(np.unique(array)) <= {0, 5}
    assert 5 in np.unique(array)
    assert reprojected_bytes is None  # já estava projetado
    # A janela recortada é bem menor que o raster inteiro (50x50).
    assert array.shape[0] < 50 and array.shape[1] < 50


def test_extract_landscape_from_tif_region_geojson_geographic_crs_is_reprojected():
    tif_bytes = make_test_tif(
        crs="EPSG:4326", pixel_size=0.001, width=50, height=50,
        origin_x=-48.0, origin_y=-15.0, fill_value=3,
    )
    fake = FakeUploadedFile("municipio_graus.tif", tif_bytes)
    region_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-47.99, -15.01], [-47.97, -15.01], [-47.97, -14.99],
                    [-47.99, -14.99], [-47.99, -15.01],
                ]],
            },
        }],
    }

    array, resolution, reprojected_bytes = app.extract_landscape_from_tif(
        fake, region_geojson=region_geojson,
    )

    assert array.size > 0
    assert 3 in np.unique(array)
    assert resolution[0] > 1  # reprojetado de graus para metros
    assert reprojected_bytes is not None
    with app.rasterio.io.MemoryFile(reprojected_bytes).open() as ds:
        assert ds.crs.is_projected


def test_extract_landscape_from_tif_region_outside_raster_raises():
    tif_bytes = make_test_tif(width=50, height=50)
    fake = FakeUploadedFile("municipio.tif", tif_bytes)
    # Polígono bem longe da extensão do raster de teste (que cobre só 1500x1500m
    # a partir de 200000/8200000 em UTM 23S) — em graus, a ~5 graus de distância.
    region_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-40.0, -10.0], [-39.9, -10.0], [-39.9, -9.9],
                    [-40.0, -9.9], [-40.0, -10.0],
                ]],
            },
        }],
    }

    with pytest.raises(ValueError):
        app.extract_landscape_from_tif(fake, region_geojson=region_geojson)
