"""
Testes de `validate_file_upload` em `backend/app/services/landscape_core.py`
— usada internamente por `extract_landscape_from_tif` para validar o .tif
enviado (extensão, tamanho, path traversal).

Portadas de tests/test_app_validation.py (app.py Streamlit, removido). Esse
arquivo também testava `uploaded_file_to_gdf` (conversão de GeoJSON/shapefile
.zip enviado como ponto de interesse) — essa função nunca foi extraída para
landscape_core.py e não tem nenhuma referência em backend/ hoje:
`POST /api/metrics/calculate` recebe o ponto de interesse como `point_lon`/
`point_lat` (form fields simples, vindos de um clique no mapa Leaflet do
frontend novo) ou como código de município (dropdown IBGE) — não há mais um
caminho de upload de GeoJSON/shapefile para o ponto. Confirmado deliberado
(simplificação de UX do frontend novo), não uma perda acidental — ver
ROADMAP.md.
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import landscape_core
from tests.helpers import FakeUploadedFile, make_point_shapefile_zip


VALID_GEOJSON_ONE_POINT = json.dumps(
    {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-47.9292, -15.7801]},
                "properties": {},
            }
        ],
    }
).encode("utf-8")


class TestValidateFileUpload:
    def test_rejects_missing_file(self):
        is_valid, message = landscape_core.validate_file_upload(None)
        assert is_valid is False

    def test_rejects_file_larger_than_max_size(self):
        fake = FakeUploadedFile("area.geojson", b"x" * 100)
        is_valid, message = landscape_core.validate_file_upload(fake, max_size=50)
        assert is_valid is False
        assert "grande" in message.lower()

    def test_rejects_disallowed_extension(self):
        fake = FakeUploadedFile("area.shp", b"conteudo")
        is_valid, message = landscape_core.validate_file_upload(fake)
        assert is_valid is False
        assert "extens" in message.lower()

    def test_rejects_path_traversal_in_filename(self):
        fake = FakeUploadedFile("../../etc/passwd.geojson", b"conteudo")
        is_valid, message = landscape_core.validate_file_upload(fake)
        assert is_valid is False

    def test_accepts_valid_geojson(self):
        fake = FakeUploadedFile("area.geojson", VALID_GEOJSON_ONE_POINT)
        is_valid, message = landscape_core.validate_file_upload(fake)
        assert is_valid is True

    def test_accepts_custom_extensions_and_size(self):
        fake = FakeUploadedFile("area.tif", b"x" * 1000)
        is_valid, _ = landscape_core.validate_file_upload(fake, allowed_extensions={".tif"}, max_size=2000)
        assert is_valid is True

    def test_accepts_zip_shapefile_extension(self):
        fake = FakeUploadedFile("ponto.zip", make_point_shapefile_zip())
        is_valid, _ = landscape_core.validate_file_upload(fake)
        assert is_valid is True
