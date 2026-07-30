"""
Serviço de cálculo real de métricas de paisagem para a API FastAPI.

Reaproveita as funções puras já implementadas e testadas em
`app.services.landscape_core` (extração MapBiomas/GeoTIFF, PyLandStats, malha
municipal do IBGE) em vez de duplicá-las — mesmo padrão já usado por
`api/routes/sse.py`/`supervised.py` (que reaproveitam `clustering`/
`supervised_models`, também em `app.services`).

Antes deste módulo, `POST /api/metrics/calculate` retornava sempre os mesmos
números fixos, independente do ponto/município/arquivo enviado — este
serviço substitui o stub pela extração/cálculo real, preservando a mesma
regra de negócio do app original: nenhuma métrica é gerada sem dados reais
por trás (falha explícita em vez de dado fabricado).
"""
import json
from typing import Optional

import ee
import numpy as np

from app.db import municipios as municipios_db
from app.services import landscape_core


class LandscapeAnalysisError(RuntimeError):
    """Erro de negócio com mensagem já pronta para exibir ao usuário."""


class _UploadedFileAdapter:
    """Adapta bytes de um `UploadFile` do FastAPI para a interface duck-typed
    que as funções de landscape_core.py esperam de um arquivo do Streamlit
    (`.name`, `.size`, `.getbuffer()`/`.getvalue()`) — permite reusar
    `extract_landscape_from_tif`/`validate_file_upload` sem alterá-las."""

    def __init__(self, filename: str, content: bytes):
        self.name = filename
        self._content = content
        self.size = len(content)

    def getbuffer(self):
        return self._content

    def getvalue(self):
        return self._content


def initialize_earth_engine(credentials: dict) -> None:
    """Inicializa o Earth Engine com a credencial de conta de serviço do
    usuário — levanta `LandscapeAnalysisError` (mensagem pronta para exibir)
    em vez de propagar a exceção crua do SDK."""
    try:
        service_account = credentials.get("client_email")
        ee_credentials = ee.ServiceAccountCredentials(
            service_account, key_data=json.dumps(credentials)
        )
        ee.Initialize(
            credentials=ee_credentials,
            opt_url="https://earthengine-highvolume.googleapis.com",
        )
    except Exception as ex:
        raise LandscapeAnalysisError(
            f"Falha na inicialização do Earth Engine: {ex}. Confirme que o JSON da "
            "conta de serviço está correto, que a Earth Engine API está habilitada "
            "no projeto GCP e que a conta de serviço tem permissão de acesso ao "
            "Earth Engine."
        ) from ex


def _get_municipio_geojson_cached(municipio_codigo: str) -> dict | None:
    """Checa `municipios_malha` (cache nacional pré-carregado, ver
    `scripts/seed_municipios_malha.py`) antes de cair na chamada ao vivo à
    API de malhas do IBGE (`landscape_core._ibge_get_municipio_geojson`) —
    elimina a dependência de rede em tempo real para os municípios já
    cacheados, mas nunca deixa de resolver um município só porque o cache
    ainda não rodou (segue a mesma regra de "nunca fabricar dado": cache
    miss cai no caminho antigo, não retorna vazio)."""
    cached = municipios_db.get_municipio_malha(municipio_codigo)
    if cached is not None:
        return json.loads(cached["geojson"])
    return landscape_core._ibge_get_municipio_geojson(municipio_codigo)


def _build_mapbiomas_roi(point_lonlat, buffer_dist, municipio_geojson):
    if municipio_geojson is not None:
        from shapely.geometry import mapping

        geom_shapely = landscape_core._municipio_geometry_shapely(municipio_geojson)
        return ee.Geometry(mapping(geom_shapely))
    if point_lonlat is None or buffer_dist is None:
        raise LandscapeAnalysisError(
            "É necessário um ponto + buffer ou um município para usar a fonte MapBiomas."
        )
    point = ee.Geometry.Point([point_lonlat[0], point_lonlat[1]])
    return point.buffer(buffer_dist)


def _extract_mapbiomas_pixels(roi_buffer):
    """Porta a seleção de asset (com fallback entre collections) e a
    extração de pixels (sampleRectangle -> reduceRegion) do antigo
    `app.py::main()` (Streamlit) para uma função pura, testável isoladamente da UI."""
    try:
        mapbiomas_assets = [
            "projects/mapbiomas-public/assets/brazil/lulc/collection9/mapbiomas_collection90_integration_v1",
            "projects/mapbiomas-public/assets/brazil/lulc/collection8/mapbiomas_collection80_integration_v1",
            "projects/mapbiomas-workspace/public/collection7/mapbiomas_collection70_integration_v2",
            "projects/mapbiomas-workspace/public/collection6/mapbiomas_collection60_integration_v1",
        ]

        mb = None
        collection_number = None
        for asset in mapbiomas_assets:
            try:
                test_image = ee.Image(asset)
                bands = test_image.bandNames().getInfo()
                if bands:
                    mb = test_image
                    if "collection9" in asset:
                        collection_number = 9
                    elif "collection8" in asset:
                        collection_number = 8
                    elif "collection7" in asset:
                        collection_number = 7
                    else:
                        collection_number = 6
                    break
            except Exception:
                continue

        if mb is None:
            raise ValueError("Nenhum asset MapBiomas disponível")

        bands = mb.bandNames().getInfo()
        available_years = []
        for band in bands:
            if "classification_" in band:
                year = band.replace("classification_", "")
                if year.isdigit():
                    available_years.append(int(year))

        latest_year = max(available_years) if available_years else (2023 if collection_number >= 9 else 2022)
        classification_band = f"classification_{latest_year}"
        mb_year = mb.select(classification_band)

        # Mínimo de pixels reais exigido para montar uma matriz 3x3 — abaixo
        # disso não há dado suficiente para métricas confiáveis.
        min_valid_pixels = 9

        try:
            sample_result = mb_year.sampleRectangle(region=roi_buffer, defaultValue=0)
            array_data = sample_result.get(classification_band).getInfo()
            np_arr_mb = np.array(array_data)
            if np_arr_mb.size == 0 or np.all(np_arr_mb == 0):
                raise ValueError("Dados insuficientes via sampleRectangle")
        except Exception:
            reduction = mb_year.reduceRegion(
                reducer=ee.Reducer.toList(),
                geometry=roi_buffer,
                scale=30,
                maxPixels=1e8,
                bestEffort=True,
            )
            values_list = reduction.get(classification_band).getInfo()
            valid_values = [int(v) for v in (values_list or []) if v is not None and v != 0]

            if len(valid_values) < min_valid_pixels:
                raise ValueError(
                    f"Apenas {len(valid_values)} pixel(is) válido(s) na área selecionada "
                    f"(mínimo necessário: {min_valid_pixels}). Aumente o buffer ou escolha "
                    "outro ponto/município."
                )

            side = int(np.sqrt(len(valid_values)))
            total_needed = side * side
            np_arr_mb = np.array(valid_values[:total_needed]).reshape(side, side)

        return np_arr_mb, (30.0, 30.0), latest_year
    except Exception as mb_error:
        raise LandscapeAnalysisError(
            "Não foi possível extrair dados reais do MapBiomas para esta área. Isso não "
            "gera uma análise substituta com dados de exemplo. "
            f"Detalhes: {mb_error}. Possíveis causas: buffer muito pequeno, região sem "
            "cobertura no asset MapBiomas, ou instabilidade temporária do Earth Engine."
        ) from mb_error


def run_landscape_analysis(
    *,
    data_source: str,
    point_lon: Optional[float] = None,
    point_lat: Optional[float] = None,
    buffer_dist: Optional[float] = None,
    municipio_codigo: Optional[str] = None,
    municipio_nome: Optional[str] = None,
    municipio_uf: Optional[str] = None,
    tif_filename: Optional[str] = None,
    tif_bytes: Optional[bytes] = None,
    credentials: Optional[dict] = None,
) -> dict:
    """Executa o pipeline real (área de interesse -> extração -> PyLandStats)
    e devolve tudo que a rota precisa para persistir/retornar o resultado.
    Levanta `LandscapeAnalysisError` (mensagem pronta para o usuário) em
    qualquer etapa que não puder ser concluída com dados reais."""
    point_lonlat = (
        (point_lon, point_lat) if point_lon is not None and point_lat is not None else None
    )

    municipio_geojson = None
    if municipio_codigo:
        municipio_geojson = _get_municipio_geojson_cached(municipio_codigo)
        if municipio_geojson is None:
            raise LandscapeAnalysisError(
                f"Não foi possível obter o limite territorial do município (código "
                f"{municipio_codigo}) na API de malhas do IBGE. Tente novamente."
            )

    resolution = (30.0, 30.0)
    ano = None

    if data_source == "mapbiomas":
        if point_lonlat is None and municipio_geojson is None:
            raise LandscapeAnalysisError(
                "Selecione um ponto + buffer ou um município para usar a fonte MapBiomas."
            )
        if not credentials:
            raise LandscapeAnalysisError(
                "Nenhuma credencial do Earth Engine cadastrada para este usuário. Cadastre "
                "sua credencial de conta de serviço antes de calcular métricas via MapBiomas."
            )
        initialize_earth_engine(credentials)
        roi_buffer = _build_mapbiomas_roi(point_lonlat, buffer_dist, municipio_geojson)
        np_arr, resolution, ano = _extract_mapbiomas_pixels(roi_buffer)

    elif data_source == "geotiff":
        if not tif_bytes:
            raise LandscapeAnalysisError("Envie um arquivo GeoTIFF para usar a fonte 'Meu raster'.")
        uploaded = _UploadedFileAdapter(tif_filename or "upload.tif", tif_bytes)
        try:
            if municipio_geojson is not None:
                np_arr, resolution, _reproj = landscape_core.extract_landscape_from_tif(
                    uploaded, region_geojson=municipio_geojson,
                )
            elif point_lonlat is not None and buffer_dist is not None:
                np_arr, resolution, _reproj = landscape_core.extract_landscape_from_tif(
                    uploaded, point_lonlat, buffer_dist,
                )
            else:
                np_arr, resolution, _reproj = landscape_core.extract_landscape_from_tif(uploaded)
        except Exception as tif_error:
            raise LandscapeAnalysisError(
                "Não foi possível extrair dados reais do GeoTIFF enviado. Isso não gera "
                f"uma análise substituta com dados de exemplo. Detalhes: {tif_error}. "
                "Possíveis causas: buffer/município fora da área do raster, CRS do raster "
                "inválido, raster com apenas nodata, ou arquivo corrompido."
            ) from tif_error
        ano = landscape_core._extract_year_from_filename(tif_filename) if tif_filename else None

    else:
        raise LandscapeAnalysisError(f"Fonte de dados desconhecida: {data_source!r}")

    ls, class_metrics_df = landscape_core._compute_class_metrics(np_arr, resolution)
    landscape_metrics = landscape_core._compute_landscape_metrics(ls)

    if municipio_nome:
        label = f"{municipio_nome}/{municipio_uf}" if municipio_uf else municipio_nome
    elif point_lon is not None and point_lat is not None:
        label = f"Ponto ({point_lon:.4f}, {point_lat:.4f})"
    else:
        label = tif_filename or "Análise GeoTIFF"

    fingerprint = landscape_core._compute_fingerprint(
        data_source,
        tif_bytes=tif_bytes,
        point_lonlat=point_lonlat,
        buffer_dist=buffer_dist,
        whole_raster=(data_source == "geotiff" and point_lonlat is None and municipio_geojson is None),
        municipio_codigo=municipio_codigo,
    )

    return {
        "label": label,
        "fingerprint": fingerprint,
        "point_lonlat": point_lonlat,
        "ano": ano,
        "class_metrics_df": class_metrics_df,
        "landscape_metrics": landscape_metrics,
    }
