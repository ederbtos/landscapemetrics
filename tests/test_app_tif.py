"""
Testes de extract_landscape_from_tif (app.py) — fonte de dados alternativa
ao MapBiomas/Earth Engine (upload de GeoTIFF próprio). Ver regras em
documentation/09_business_rules.md.
"""
import os
from pathlib import Path

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

    array, resolution, reprojected_bytes = app.extract_landscape_from_tif(fake, point, buffer_dist=300)

    assert resolution == (30.0, 30.0)
    assert array.size > 0
    assert set(np.unique(array)) <= {0, 3}  # 0 = nodata nas bordas do buffer circular
    assert reprojected_bytes is None  # já estava projetado — nada foi convertido


def test_utm_epsg_for_lonlat_matches_known_zones():
    # Brasília — zona 23S
    assert app._utm_epsg_for_lonlat(-47.9292, -15.78) == 32723
    # Hemisfério norte (Alemanha) — zona 32N
    assert app._utm_epsg_for_lonlat(10.0, 50.0) == 32632


def test_geographic_crs_is_auto_reprojected_with_point():
    tif_bytes = make_test_tif(crs="EPSG:4326", pixel_size=0.001, width=50, height=50,
                               origin_x=-48.0, origin_y=-15.0, fill_value=3)
    # Ponto no centro do raster de teste (evita ambiguidade de borda no recorte da janela)
    point = (-47.975, -15.025)
    fake = FakeUploadedFile("area_graus.tif", tif_bytes)

    array, resolution, reprojected_bytes = app.extract_landscape_from_tif(fake, point, buffer_dist=300)

    assert array.size > 0
    assert set(np.unique(array)) <= {0, 3}
    # Reprojetado para a zona UTM que contém o ponto (23S) — resolução em metros, não graus
    assert resolution[0] > 1  # pixel_size original era 0.001 (graus); em metros é bem maior
    assert reprojected_bytes is not None
    with app.rasterio.io.MemoryFile(reprojected_bytes).open() as ds:
        assert ds.crs.is_projected
        assert ds.crs.to_epsg() == 32723


def test_whole_raster_mode_reads_full_extent_without_point():
    tif_bytes = make_test_tif(fill_value=3, width=50, height=50)
    fake = FakeUploadedFile("area.tif", tif_bytes)

    array, resolution, reprojected_bytes = app.extract_landscape_from_tif(fake)

    assert resolution == (30.0, 30.0)
    assert array.shape == (50, 50)
    assert set(np.unique(array)) == {3}
    assert reprojected_bytes is None


def test_whole_raster_mode_rejects_all_nodata():
    tif_bytes = make_test_tif(fill_value=0, nodata=0)
    fake = FakeUploadedFile("area_vazia.tif", tif_bytes)

    with pytest.raises(ValueError, match="[Nn]enhum pixel válido"):
        app.extract_landscape_from_tif(fake)


def test_whole_raster_mode_geographic_crs_is_auto_reprojected_to_epsg5880():
    tif_bytes = make_test_tif(crs="EPSG:4326", pixel_size=0.001, width=50, height=50,
                               origin_x=-48.0, origin_y=-15.0, fill_value=3)
    fake = FakeUploadedFile("area_graus.tif", tif_bytes)

    array, resolution, reprojected_bytes = app.extract_landscape_from_tif(fake)

    assert array.size > 0
    # 0 = nodata pode aparecer nas bordas — a grade reprojetada não alinha
    # perfeitamente com a original, mas a classe real (3) precisa estar presente.
    assert set(np.unique(array)) <= {0, 3}
    assert 3 in np.unique(array)
    assert reprojected_bytes is not None
    with app.rasterio.io.MemoryFile(reprojected_bytes).open() as ds:
        assert ds.crs.is_projected
        assert ds.crs.to_epsg() == 5880


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


def test_cleanup_false_defers_removal_and_reports_path(tmp_path, monkeypatch):
    # Modo multi-arquivo: o chamador (loop em app.main) pede cleanup=False pra
    # manter os temporários de todos os arquivos do lote em disco até que as
    # métricas de todos eles tenham sido calculadas, não só extraídas.
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    tif_bytes = make_test_tif()
    point = _lonlat_for_utm23s(200750, 8199250)
    fake = FakeUploadedFile("area.tif", tif_bytes)
    temp_paths = []

    app.extract_landscape_from_tif(
        fake, point, buffer_dist=300, cleanup=False, temp_path_out=temp_paths,
    )

    assert len(temp_paths) == 1
    assert Path(temp_paths[0]).exists()  # ainda não foi removido

    os.remove(temp_paths[0])  # limpeza que o chamador faria ao fim do lote
