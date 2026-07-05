"""
Testes de extract_landscape_from_tif (app.py) — fonte de dados alternativa
ao MapBiomas/Earth Engine (upload de GeoTIFF próprio). Ver regras em
documentation/09_business_rules.md.
"""
import numpy as np
import pytest
from pyproj import Transformer

import app
from tests.helpers import FakeUploadedFile, make_test_tif


def _lonlat_for_utm23s(x: float, y: float) -> tuple:
    transformer = Transformer.from_crs("EPSG:32723", "EPSG:4326", always_xy=True)
    return transformer.transform(x, y)


def test_extracts_valid_area_from_projected_geotiff():
    tif_bytes = make_test_tif(fill_value=3)
    point = _lonlat_for_utm23s(200750, 8199250)  # centro do raster de teste
    fake = FakeUploadedFile("area.tif", tif_bytes)

    array, resolution = app.extract_landscape_from_tif(fake, point, buffer_dist=300)

    assert resolution == (30.0, 30.0)
    assert array.size > 0
    assert set(np.unique(array)) <= {0, 3}  # 0 = nodata nas bordas do buffer circular


def test_rejects_geographic_crs():
    tif_bytes = make_test_tif(crs="EPSG:4326", pixel_size=0.001, origin_x=-48.0, origin_y=-15.0)
    fake = FakeUploadedFile("area_graus.tif", tif_bytes)

    with pytest.raises(ValueError, match="projeção métrica"):
        app.extract_landscape_from_tif(fake, (-48.0, -15.0), buffer_dist=300)


def test_rejects_buffer_outside_raster_extent():
    tif_bytes = make_test_tif()
    far_away_point = _lonlat_for_utm23s(200750, 8199250)
    # ponto bem longe da extensão do raster de teste (que cobre só 1500x1500m)
    fake = FakeUploadedFile("area.tif", tif_bytes)

    with pytest.raises(ValueError):
        app.extract_landscape_from_tif(fake, (far_away_point[0] + 5, far_away_point[1] + 5), buffer_dist=300)


def test_rejects_area_with_only_nodata_pixels():
    tif_bytes = make_test_tif(fill_value=0, nodata=0)
    point = _lonlat_for_utm23s(200750, 8199250)
    fake = FakeUploadedFile("area_vazia.tif", tif_bytes)

    with pytest.raises(ValueError, match="[Nn]enhum pixel válido"):
        app.extract_landscape_from_tif(fake, point, buffer_dist=300)


def test_temp_file_is_removed_after_extraction(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    tif_bytes = make_test_tif()
    point = _lonlat_for_utm23s(200750, 8199250)
    fake = FakeUploadedFile("area.tif", tif_bytes)

    app.extract_landscape_from_tif(fake, point, buffer_dist=300)

    assert list(tmp_path.iterdir()) == []
