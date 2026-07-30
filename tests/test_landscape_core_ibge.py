"""
Testes de `_ibge_get_municipio_geojson`/`_municipio_geometry_shapely`/
`extract_landscape_from_tif` (recorte por região municipal) em
`backend/app/services/landscape_core.py` — ver "Área de interesse por
município (IBGE)" no ROADMAP.md.

Portadas de `tests/test_app_ibge.py` (app.py Streamlit, removido). As demais
funções que esse arquivo testava (`_ibge_get_ufs`/`_ibge_get_municipios`/
`_ibge_get_populacao_estimada`) só existiam no app.py e já tinham sido
superadas por `backend/app/api/routes/ibge.py` (implementação própria, sem
reaproveitar essas funções) — cobertas agora em
`tests/test_backend_api_routes.py` (`test_ibge_municipios_route`,
`test_ibge_populacao_route_*`).
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import requests

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import landscape_core
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

    result = landscape_core._ibge_get_municipio_geojson.__wrapped__("5208707")

    assert result == fake_geojson


def test_ibge_get_municipio_geojson_returns_none_on_request_failure(monkeypatch):
    def _raise(*a, **k):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(requests, "get", _raise)

    assert landscape_core._ibge_get_municipio_geojson.__wrapped__("5208707") is None


def test_ibge_get_municipio_geojson_returns_none_when_no_features(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse({"type": "FeatureCollection", "features": []}))

    assert landscape_core._ibge_get_municipio_geojson.__wrapped__("0000000") is None


def test_municipio_geometry_shapely_extracts_single_feature_geometry():
    geojson = _municipio_polygon_geojson()
    geom = landscape_core._municipio_geometry_shapely(geojson)

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

    array, resolution, reprojected_bytes = landscape_core.extract_landscape_from_tif(
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

    array, resolution, reprojected_bytes = landscape_core.extract_landscape_from_tif(
        fake, region_geojson=region_geojson,
    )

    assert array.size > 0
    assert 3 in np.unique(array)
    assert resolution[0] > 1  # reprojetado de graus para metros
    assert reprojected_bytes is not None
    with landscape_core.rasterio.io.MemoryFile(reprojected_bytes).open() as ds:
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
        landscape_core.extract_landscape_from_tif(fake, region_geojson=region_geojson)
