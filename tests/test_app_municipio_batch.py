"""
Testes do modo de lote por município (shapefile de municípios do IBGE + um
GeoTIFF próprio -> planilha com métricas de fragmentação de todos os
municípios) — ver "Métricas por município (lote via shapefile)" no
ROADMAP.md. Cobre `_detect_municipio_columns`, `_municipio_files_to_gdf`,
`_run_municipio_batch` e `_build_municipio_batch_workbook` (app.py).
"""
import io
import os
import tempfile

import geopandas as gpd
import pandas as pd
import pytest
from pyproj import Transformer
from shapely.geometry import box

import app
from tests.helpers import FakeUploadedFile, make_test_tif


def test_detect_municipio_columns_ibge_standard_names():
    df = pd.DataFrame(columns=["CD_MUN", "NM_MUN", "SIGLA_UF", "geometry"])

    detected = app._detect_municipio_columns(df)

    assert detected == {"codigo": "CD_MUN", "nome": "NM_MUN", "uf": "SIGLA_UF"}


def test_detect_municipio_columns_case_insensitive():
    df = pd.DataFrame(columns=["cd_mun", "nm_mun", "sigla_uf"])

    detected = app._detect_municipio_columns(df)

    assert detected == {"codigo": "cd_mun", "nome": "nm_mun", "uf": "sigla_uf"}


def test_detect_municipio_columns_no_match_returns_none():
    df = pd.DataFrame(columns=["foo", "bar"])

    detected = app._detect_municipio_columns(df)

    assert detected == {"codigo": None, "nome": None, "uf": None}


def _municipios_gdf_for_test_raster():
    """Monta um GeoDataFrame (EPSG:4326) com 3 'municípios': 2 pequenos
    quadrados dentro da extensão do raster de `make_test_tif` (UTM 23S,
    canto (200000, 8200000), 50x50 px de 30m) e 1 bem fora dela — usado para
    cobrir tanto o caminho de sucesso quanto o isolamento de erro por
    município em `_run_municipio_batch`."""
    # Extensão do raster de teste em EPSG:32723: x em [200000, 201500],
    # y em [8198500, 8200000] (origem é o canto NW).
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


def _shapefile_components_as_uploaded_files(gdf) -> list:
    """Grava `gdf` como shapefile (via fiona direto — `GeoDataFrame.to_file`
    quebra nesta combinação de geopandas 0.14.3 + numpy 2.x, ver
    `make_point_shapefile_zip` em tests/helpers.py para o mesmo contorno)
    num diretório temporário e devolve os componentes (.shp/.shx/.dbf/.prj)
    como uma lista de `FakeUploadedFile` — simula o usuário selecionando
    todos os arquivos soltos de uma vez no seletor do navegador (ver
    `_municipio_files_to_gdf`), sem passar pelo caminho `.zip`."""
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
                files.append(FakeUploadedFile(fname, f.read()))
        return files


def test_municipio_files_to_gdf_reads_loose_shapefile_components():
    original = _municipios_gdf_for_test_raster()
    components = _shapefile_components_as_uploaded_files(original)
    assert any(f.name.endswith(".shp") for f in components)
    assert any(f.name.endswith(".dbf") for f in components)

    gdf = app._municipio_files_to_gdf(components)

    assert len(gdf) == 3
    assert set(gdf["CD_MUN"]) == {"1111111", "2222222", "3333333"}


def test_municipio_files_to_gdf_missing_component_raises_clear_error():
    original = _municipios_gdf_for_test_raster()
    components = _shapefile_components_as_uploaded_files(original)
    components_without_dbf = [f for f in components if not f.name.endswith(".dbf")]

    with pytest.raises(ValueError, match="dbf"):
        app._municipio_files_to_gdf(components_without_dbf)


def test_run_municipio_batch_processes_each_municipio_and_isolates_errors(temp_db):
    municipios_gdf = _municipios_gdf_for_test_raster()
    tif_file = FakeUploadedFile("cobertura.tif", make_test_tif())
    progress_calls = []

    landscape_rows, class_rows, errors = app._run_municipio_batch(
        tif_file, municipios_gdf, "CD_MUN", "NM_MUN", "SIGLA_UF",
        "user@example.com", on_progress=lambda i, total, label: progress_calls.append((i, total, label)),
    )

    assert {row["municipio_codigo"] for row in landscape_rows} == {"1111111", "2222222"}
    assert len(class_rows) >= 2  # ao menos 1 linha de classe por município bem-sucedido
    assert {row["municipio_codigo"] for row in class_rows} <= {"1111111", "2222222"}

    assert len(errors) == 1
    assert errors[0]["municipio_codigo"] == "3333333"
    assert "erro" in errors[0]

    assert progress_calls  # callback foi chamado
    assert progress_calls[0][1] == 3  # total de municípios


def test_run_municipio_batch_reuses_cache_on_second_run(temp_db, monkeypatch):
    municipios_gdf = _municipios_gdf_for_test_raster()[:2]  # só os 2 que intersectam o raster
    tif_bytes = make_test_tif()

    landscape_rows_1, _, errors_1 = app._run_municipio_batch(
        FakeUploadedFile("cobertura.tif", tif_bytes), municipios_gdf, "CD_MUN", "NM_MUN", "SIGLA_UF",
        "user@example.com",
    )
    assert not errors_1
    assert len(landscape_rows_1) == 2

    # Na segunda rodada, força _clip_raster_at_path a explodir se for chamada —
    # só passa se o resultado vier do cache (db.get_metric_result), sem
    # recortar o raster de novo.
    def _boom(*args, **kwargs):
        raise AssertionError("_clip_raster_at_path não deveria ser chamada em cache hit")

    monkeypatch.setattr(app, "_clip_raster_at_path", _boom)

    landscape_rows_2, _, errors_2 = app._run_municipio_batch(
        FakeUploadedFile("cobertura.tif", tif_bytes), municipios_gdf, "CD_MUN", "NM_MUN", "SIGLA_UF",
        "user@example.com",
    )

    assert not errors_2
    assert {row["municipio_codigo"] for row in landscape_rows_2} == {row["municipio_codigo"] for row in landscape_rows_1}


def test_build_municipio_batch_workbook_has_both_sheets():
    landscape_df = pd.DataFrame([{"municipio_codigo": "1111111", "municipio_nome": "A", "shannon_diversity_index": 0.5}])
    class_df = pd.DataFrame([{"municipio_codigo": "1111111", "classe": "Floresta", "total_area": 10.0}])

    workbook_bytes = app._build_municipio_batch_workbook(landscape_df, class_df)

    sheets = pd.read_excel(io.BytesIO(workbook_bytes), sheet_name=None)
    assert set(sheets.keys()) == {"paisagem", "classe"}
    assert list(sheets["paisagem"]["municipio_codigo"].astype(str)) == ["1111111"]
    assert list(sheets["classe"]["classe"]) == ["Floresta"]
