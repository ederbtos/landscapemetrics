"""
Testes de validate_file_upload e uploaded_file_to_gdf (app.py).

Nota sobre uploaded_file_to_gdf: é decorada com @st.cache_data, cujo hashing
não reconhece o dublê de upload usado aqui (só reconhece a classe real
streamlit.runtime.uploaded_file_manager.UploadedFile) — chamamos
`.__wrapped__` para acessar a função original sem cache, evitando depender
de uma instância real do Streamlit rodando. Isso testa a lógica de
conversão em si, não o comportamento de cache (irrelevante para corretude).
"""
import json

import pytest

import app
from tests.helpers import FakeUploadedFile


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
        is_valid, message = app.validate_file_upload(None)
        assert is_valid is False

    def test_rejects_file_larger_than_max_size(self):
        fake = FakeUploadedFile("area.geojson", b"x" * 100)
        is_valid, message = app.validate_file_upload(fake, max_size=50)
        assert is_valid is False
        assert "grande" in message.lower()

    def test_rejects_disallowed_extension(self):
        fake = FakeUploadedFile("area.shp", b"conteudo")
        is_valid, message = app.validate_file_upload(fake)
        assert is_valid is False
        assert "extens" in message.lower()

    def test_rejects_path_traversal_in_filename(self):
        fake = FakeUploadedFile("../../etc/passwd.geojson", b"conteudo")
        is_valid, message = app.validate_file_upload(fake)
        assert is_valid is False

    def test_accepts_valid_geojson(self):
        fake = FakeUploadedFile("area.geojson", VALID_GEOJSON_ONE_POINT)
        is_valid, message = app.validate_file_upload(fake)
        assert is_valid is True

    def test_accepts_custom_extensions_and_size(self):
        fake = FakeUploadedFile("area.tif", b"x" * 1000)
        is_valid, _ = app.validate_file_upload(fake, allowed_extensions={".tif"}, max_size=2000)
        assert is_valid is True


class TestUploadedFileToGdf:
    def test_converts_valid_geojson_with_one_point(self):
        fake = FakeUploadedFile("area.geojson", VALID_GEOJSON_ONE_POINT)
        gdf = app.uploaded_file_to_gdf.__wrapped__(fake)
        assert len(gdf) == 1
        assert gdf.crs is not None

    def test_rejects_geojson_without_features(self):
        empty = json.dumps({"type": "FeatureCollection", "features": []}).encode("utf-8")
        fake = FakeUploadedFile("vazio.geojson", empty)
        with pytest.raises(Exception):
            app.uploaded_file_to_gdf.__wrapped__(fake)

    def test_rejects_file_too_large(self):
        fake = FakeUploadedFile("area.geojson", VALID_GEOJSON_ONE_POINT)
        fake.size = app.MAX_FILE_SIZE + 1
        with pytest.raises(Exception):
            app.uploaded_file_to_gdf.__wrapped__(fake)
