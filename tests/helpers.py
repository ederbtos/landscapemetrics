"""
Utilitários de teste: um dublê de streamlit.runtime.uploaded_file_manager.UploadedFile,
um gerador de GeoTIFF sintético em memória e um gerador de shapefile de ponto
compactado em .zip, usados por test_app_validation.py e test_app_tif.py.
"""
import io
import os
import tempfile
import zipfile

import fiona
import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin


class FakeUploadedFile:
    """Expõe só o que app.py de fato usa de um upload do Streamlit: .name,
    .size e .getbuffer(). Suficiente para validate_file_upload,
    uploaded_file_to_gdf (via .__wrapped__, ver test_app_validation.py) e
    extract_landscape_from_tif — sem precisar de uma instância real do
    Streamlit rodando."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data
        self.size = len(data)

    def getbuffer(self) -> bytes:
        return self._data


def make_test_tif(
    crs: str = "EPSG:32723",
    width: int = 50,
    height: int = 50,
    pixel_size: float = 30.0,
    origin_x: float = 200000.0,
    origin_y: float = 8200000.0,
    fill_value: int = 1,
    nodata: int = 0,
) -> bytes:
    """Gera os bytes de um GeoTIFF de 1 banda, uint8, sem tocar em disco —
    equivalente sintético ao que extract_landscape_from_tif espera receber
    via uploaded_tif.getbuffer(). Por padrão usa UTM 23S (métrico), classe
    fixa `fill_value` em toda a extensão, cobrindo 1500x1500 m a partir de
    (origin_x, origin_y)."""
    transform = from_origin(origin_x, origin_y, pixel_size, pixel_size)
    data = np.full((height, width), fill_value, dtype=np.uint8)
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype=data.dtype,
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as dataset:
            dataset.write(data, 1)
        return bytes(memfile.read())


def make_point_shapefile_zip(lon: float = -47.9292, lat: float = -15.7801, crs: str = "EPSG:4326") -> bytes:
    """Gera os bytes de um .zip contendo um shapefile de 1 ponto (.shp/.shx/.dbf/.prj) —
    equivalente sintético ao que uploaded_file_to_gdf espera para a fonte de ponto
    alternativa ao GeoJSON (ver app.py, seção 2 do fluxo principal)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shp_path = os.path.join(tmpdir, "ponto.shp")
        schema = {"geometry": "Point", "properties": {}}
        with fiona.open(shp_path, "w", driver="ESRI Shapefile", schema=schema, crs=crs) as dst:
            dst.write({"geometry": {"type": "Point", "coordinates": (lon, lat)}, "properties": {}})

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for fname in os.listdir(tmpdir):
                zf.write(os.path.join(tmpdir, fname), arcname=fname)
        return buf.getvalue()
