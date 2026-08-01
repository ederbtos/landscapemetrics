"""
Núcleo de domínio, sem dependência do Streamlit, para extração/cálculo de
métricas de paisagem (GeoTIFF + MapBiomas + PyLandStats + malha municipal do
IBGE) — compartilhado por `app.py` (Streamlit) e `backend/app/services/
landscape.py` (FastAPI), no mesmo espírito de `clustering.py`/
`supervised_models.py` (já reaproveitados pelo backend via importlib).

Extraído de `app.py` porque esse módulo faz `import streamlit` no topo e
`backend/requirements.txt`/`Dockerfile` deliberadamente NÃO incluem Streamlit
(a UI virou o frontend `static/`) — importar `app.py` diretamente do backend
funciona no ambiente de desenvolvimento local (venv único, com tudo
instalado), mas quebraria em produção (`ModuleNotFoundError: streamlit`) na
imagem Docker do backend, que só copia `backend/` e `static/`.

Todas as funções aqui são puras (sem `st.*`) — progresso/mensagens, quando
aplicável, são repassados via callbacks opcionais (`on_progress`, `notify`,
`on_metric_progress`), nunca chamadas diretas de UI.
"""
import functools
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pylandstats as pls
import rasterio
import requests
from affine import Affine
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.mask import mask as rio_mask
from rasterio.warp import calculate_default_transform, reproject
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform
from scipy.linalg import fractional_matrix_power
from scipy.ndimage import zoom as ndimage_zoom
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as shapely_transform

# Correção de ambiente (Windows): se houver uma variável de ambiente PROJ_LIB
# global (comum em máquinas com PostgreSQL/PostGIS instalado — o instalador
# registra seu próprio proj.db como padrão do sistema), o rasterio tenta abrir
# esse proj.db com sua própria libproj interna, de versão incompatível, e
# qualquer operação de CRS falha com "Error creating Transformer from CRS".
# Força aqui o proj_data que vem empacotado dentro do próprio rasterio, em
# vez de depender de como o sistema operacional está configurado — mesmo
# contorno usado por app.py/tests/conftest.py, replicado aqui para que este
# módulo seja correto mesmo quando importado sozinho (sem app.py), como no
# backend FastAPI.
os.environ["PROJ_LIB"] = str(Path(rasterio.__file__).parent / "proj_data")
os.environ["PROJ_DATA"] = os.environ["PROJ_LIB"]

logger = logging.getLogger(__name__)

# Configurações de segurança (upload de arquivos)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'.geojson', '.zip'}  # .zip = shapefile compactado (.shp+.shx+.dbf+.prj)
MAX_TIF_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
ALLOWED_TIF_EXTENSIONS = {'.tif', '.tiff'}
WHOLE_RASTER_MAX_PIXELS = 50_000_000  # acima disso, reamostra por moda antes de reprojetar (cabe na memória do processo)
MAX_MUNICIPIOS_SHP_SIZE = 50 * 1024 * 1024  # 50MB — malha municipal de uma UF inteira pode passar dos 10MB do MAX_FILE_SIZE padrão

IBGE_MALHAS_BASE = "https://servicodados.ibge.gov.br/api/v3/malhas"
IBGE_REQUEST_TIMEOUT = 15  # segundos — evita travar indefinidamente se a API do IBGE ficar lenta/indisponível

# Nome interno (usado em pls.Landscape.compute_class_metrics_df), ícone e
# tradução de cada métrica de CLASSE — fonte única reaproveitada tanto pelo
# app Streamlit (revelação progressiva + expander "Detalhamento das
# métricas") quanto pelo backend FastAPI.
#
# ORDEM DELIBERADA (ver `_compute_class_metrics`/`SLOW_METRIC_NAME`): métricas
# sem dependência de outros patches vêm primeiro (quase instantâneas),
# seguidas pelas métricas de área central (custo próprio moderado), e por
# último a métrica que depende da posição de TODOS os patches da classe entre
# si (euclidean_nearest_neighbor_mn — de longe a mais cara, ~97% do tempo
# total num benchmark com patches realistas).
METRICS_INFO = [
    # --- Área, Densidade e Forma (sem dependência entre patches) ---
    ('total_area', '📐', 'Área Total (ha)'),
    ('proportion_of_landscape', '📊', 'Proporção da paisagem (%)'),
    ('number_of_patches', '🧩', 'Número de Manchas'),
    ('patch_density', '📌', 'Densidade de manchas (manchas/100ha)'),
    ('largest_patch_index', '🏆', 'Índice de maior mancha'),
    ('total_edge', '📏', 'Total de Bordas (m)'),
    ('edge_density', '📏', 'Densidade de borda (m/ha)'),
    ('landscape_shape_index', '🔷', 'Índice de forma da paisagem'),
    ('area_mn', '📐', 'Área média (ha)'),
    ('perimeter_mn', '📏', 'Perímetro médio (m)'),
    ('perimeter_area_ratio_mn', '⚖️', 'Razão de perímetro/área média'),
    ('shape_index_mn', '🔷', 'Média de índice de forma'),
    ('fractal_dimension_mn', '🌀', 'Dimensão fractal média'),
    # --- Área Central (Core Area) — custo próprio moderado (erosão de
    # borda; ver `edge_depth` em pls.Landscape, padrão 0) ---
    ('total_core_area', '🌳', 'Área central total (ha)'),
    ('core_area_proportion_of_landscape', '🌳', 'Proporção de área central na paisagem (%)'),
    ('core_area_mn', '🌳', 'Área central média por mancha (ha)'),
    ('core_area_index_mn', '🌳', 'Índice médio de área central (%)'),
    ('number_of_disjunct_core_areas', '🌳', 'Número de áreas centrais disjuntas'),
    ('disjunct_core_area_mn', '🌳', 'Área central disjunta média (ha)'),
    # --- Isolamento — EM STANDBY: desativada a pedido do usuário para
    # validar o restante do pipeline sem esperar pela métrica mais lenta a
    # cada rodada. Reativar removendo o comentário abaixo.
    # ('euclidean_nearest_neighbor_mn', '📍', 'Distância média ao vizinho mais próximo (m)'),
]

# Métrica isoladamente responsável por ~97% do tempo de cálculo em testes
# (12,3s de 12,7s para um raster 3000x3000 com patches realistas): calcula
# distância entre TODAS as manchas da mesma classe. Usado para avisar o
# usuário nesse ponto específico em vez de deixá-lo "parado" numa % sem
# explicação.
SLOW_METRIC_NAME = "euclidean_nearest_neighbor_mn"

# Métricas de nível de PAISAGEM (um único valor global, não por classe).
# `shannon_diversity_index`/`contagion`/`effective_mesh_size`/`patch_density`/
# `edge_density`/`landscape_shape_index` vêm do PyLandStats
# (`compute_landscape_metrics_df`); as demais são calculadas manualmente em
# `_compute_landscape_metrics` (fórmulas padrão do FRAGSTATS), sem método
# dedicado equivalente no PyLandStats 3.1.0 usado neste projeto.
LANDSCAPE_METRICS_INFO = [
    ('shannon_diversity_index', '🌈', 'SHDI', 'Índice de Diversidade de Shannon'),
    ('shannon_evenness_index', '⚖️', 'SHEI', 'Uniformidade de Shannon'),
    ('simpson_diversity_index', '🎲', 'SIDI', 'Índice de Diversidade de Simpson'),
    ('simpson_evenness_index', '⚖️', 'SIEI', 'Uniformidade de Simpson'),
    ('patch_richness', '🔢', 'PR', 'Riqueza de Manchas (nº de classes presentes)'),
    ('contagion', '🧲', 'CONTAG', 'Contágio (%)'),
    ('effective_mesh_size', '🕸️', 'MESH', 'Tamanho Efetivo de Malha (ha)'),
    ('patch_density', '📌', 'PD', 'Densidade de Manchas (manchas/100ha)'),
    ('edge_density', '📏', 'ED', 'Densidade de Borda (m/ha)'),
    ('landscape_shape_index', '🔷', 'LSI', 'Índice de Forma da Paisagem'),
]

# Nomes das classes MapBiomas por código (índice = código da classe).
MAPBIOMAS_LEGEND_KEYS = [
    ' ',  # 0
    'Floresta',  # 1
    ' ',  # 2
    'Formacao florestal',  # 3
    'Savana',  # 4
    'Mangue',  # 5
    ' ', ' ', ' ',  # 6-8
    'Silvicultura',  # 9
    'Formação natural nao-florestal',  # 10
    'Campo Alagado e Área Pantanosa',  # 11
    'Campos',  # 12
    'Outras formacoes nao-florestais',  # 13
    'Agropecuaria',  # 14
    'Pastagem',  # 15
    ' ', ' ',  # 16-17
    'Agricultura',  # 18
    'Agricultura temporarias',  # 19
    'Cana',  # 20
    'Mosaico de Agricultura e Pastagem',  # 21
    'Area nao Vegetada',  # 22
    'Dunas',  # 23
    'Area Urbanizada',  # 24
    'Outras areas nao vegetadas',  # 25
    'Agua',  # 26
    'Nao Observado',  # 27
    ' ',  # 28
    'Afloramento rochoso',  # 29
    'Mineracao',  # 30
    'Aquicultura',  # 31
    'Sal',  # 32
    'Rio, lago e oceano',  # 33
    ' ', ' ',  # 34-35
    'Lavoura Perene',  # 36
    ' ', ' ',  # 37-38
    'Soja',  # 39
    'Arroz',  # 40
    'Outras culturas temporarias',  # 41
    ' ', ' ', ' ', ' ',  # 42-45
    'Cafe',  # 46
    'Citrus',  # 47
    'Outras lavouras perenes',  # 48
    'Restinga arborea',  # 49
]


def validate_file_upload(uploaded_file, allowed_extensions=None, max_size=None):
    """Valida o arquivo enviado pelo usuário"""
    allowed_extensions = allowed_extensions or ALLOWED_EXTENSIONS
    max_size = max_size or MAX_FILE_SIZE

    if not uploaded_file:
        return False, "Nenhum arquivo enviado"

    if uploaded_file.size > max_size:
        return False, f"Arquivo muito grande. Máximo: {max_size // (1024*1024)}MB"

    file_extension = Path(uploaded_file.name).suffix.lower()
    if file_extension not in allowed_extensions:
        return False, f"Extensão não permitida. Permitido: {allowed_extensions}"

    # Bloqueia path traversal (".." + separadores) e caracteres inválidos em
    # nomes de arquivo do Windows; o nome original do upload nunca é usado
    # como caminho de disco (o caminho salvo em disco é gerado via uuid4),
    # mas a validação fica como defesa em profundidade caso isso mude.
    if any(char in uploaded_file.name for char in ['..', '/', '\\', '<', '>', '|', '*', '?']):
        return False, "Nome do arquivo contém caracteres não permitidos"

    return True, "Arquivo válido"


def uploaded_file_to_gdf(data, max_size=None):
    """Converte arquivo enviado (GeoJSON ou shapefile compactado em .zip)
    para GeoDataFrame, com validações de segurança. `max_size`, se
    informado, sobrepõe o limite padrão (`MAX_FILE_SIZE`) — usado pelo
    upload do shapefile de municípios (Métricas por município em lote), que
    pode ser bem maior que um GeoJSON/shapefile de um único ponto (ver
    `MAX_MUNICIPIOS_SHP_SIZE`)."""
    try:
        is_valid, message = validate_file_upload(data, max_size=max_size)
        if not is_valid:
            raise ValueError(f"Arquivo inválido: {message}")

        file_extension = Path(data.name).suffix.lower()
        file_id = str(uuid.uuid4())
        safe_filename = f"{file_id}{file_extension}"
        file_path = os.path.join(tempfile.gettempdir(), safe_filename)

        temp_dir = Path(tempfile.gettempdir()).resolve()
        file_path_resolved = Path(file_path).resolve()
        if not str(file_path_resolved).startswith(str(temp_dir)):
            raise ValueError("Caminho de arquivo inseguro")

        try:
            with open(file_path, "wb") as file:
                file.write(data.getbuffer())

            try:
                if file_extension == ".zip":
                    # Shapefile compactado (.shp+.shx+.dbf+.prj dentro do .zip):
                    # lido direto de dentro do arquivo via VSI do GDAL (prefixo
                    # "zip://"), sem precisar extrair os componentes em disco antes.
                    gdf = gpd.read_file(f"zip://{file_path}")
                else:
                    gdf = gpd.read_file(file_path)
            except Exception as read_error:
                if file_extension == ".zip":
                    raise ValueError(
                        f"Não foi possível ler o shapefile enviado: {read_error}. "
                        "Confirme que o .zip contém .shp, .shx, .dbf (e .prj, se possível) "
                        "na raiz do arquivo."
                    ) from read_error

                # Fallback: tenta ler como JSON puro e converter (cobre GeoJSONs
                # que o driver padrão do GDAL rejeita por algum motivo).
                logger.warning(f"Erro na leitura padrão: {read_error}. Tentando método alternativo...")

                with open(file_path, 'r', encoding='utf-8') as f:
                    geojson_data = json.load(f)

                from shapely.geometry import Point as _Point

                features = geojson_data.get('features', [])
                if not features:
                    raise ValueError("Nenhuma feature encontrada no GeoJSON")

                geometries = []
                properties_list = []
                for feature in features:
                    geom_data = feature.get('geometry', {})
                    if geom_data.get('type') == 'Point':
                        coords = geom_data.get('coordinates', [])
                        if len(coords) >= 2:
                            geometries.append(_Point(coords[0], coords[1]))
                            properties_list.append(feature.get('properties', {}))

                if not geometries:
                    raise ValueError("Nenhuma geometria válida encontrada")

                gdf = gpd.GeoDataFrame(properties_list, geometry=geometries, crs='EPSG:4326')

            if gdf.empty:
                raise ValueError("Arquivo GeoJSON vazio")

            if gdf.crs is None:
                gdf = gdf.set_crs('EPSG:4326')

            logger.info(f"Arquivo processado com sucesso: {len(gdf)} geometrias")
            return gdf
        finally:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as cleanup_error:
                    logger.warning(f"Erro ao limpar arquivo temporário: {cleanup_error}")
    except Exception as e:
        logger.error(f"Erro ao processar arquivo: {e}")
        raise


MUNICIPIO_SHP_COMPONENT_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".xml"}


def _municipio_files_to_gdf(uploaded_files, max_size=None):
    """Lê o(s) arquivo(s) enviados para a área de estudo do lote por
    município (Métricas por município em lote) como um GeoDataFrame. Aceita
    dois formatos, porque muitos usuários não conseguem zipar um shapefile
    do jeito que o driver `zip://` do GDAL espera — ferramentas de
    compressão comuns colocam os componentes dentro de uma subpasta em vez
    de na raiz do .zip, e o GDAL falha com "não reconhecido como um formato
    de arquivo suportado" mesmo com .shp/.shx/.dbf corretos:

    - Um único arquivo `.zip` ou `.geojson`: delega para
      `uploaded_file_to_gdf` (caminho já existente, inalterado).
    - Vários arquivos soltos (.shp + .shx + .dbf, .prj/.cpg opcionais etc.,
      selecionados juntos no seletor do navegador — equivalente a "apontar
      a pasta"): salva todos com o nome original num diretório temporário
      próprio (os componentes precisam do mesmo nome-base lado a lado) e
      abre o .shp diretamente via `gpd.read_file`, sem passar pelo driver
      de zip."""
    max_size = max_size or MAX_MUNICIPIOS_SHP_SIZE

    if len(uploaded_files) == 1 and Path(uploaded_files[0].name).suffix.lower() in (".zip", ".geojson"):
        return uploaded_file_to_gdf(uploaded_files[0], max_size=max_size)

    total_size = sum(f.size for f in uploaded_files)
    if total_size > max_size:
        raise ValueError(f"Arquivos muito grandes juntos. Máximo: {max_size // (1024 * 1024)}MB")

    shp_files = [f for f in uploaded_files if Path(f.name).suffix.lower() == ".shp"]
    if not shp_files:
        raise ValueError(
            "Nenhum arquivo .shp encontrado — selecione todos os componentes do shapefile "
            "juntos (.shp, .shx, .dbf e, se possível, .prj)."
        )
    if len(shp_files) > 1:
        raise ValueError("Envie os componentes de um único shapefile por vez (encontrado mais de um .shp).")

    tmp_dir = Path(tempfile.gettempdir()) / f"municipios_{uuid.uuid4()}"
    tmp_dir.mkdir(parents=True)
    try:
        for uploaded in uploaded_files:
            safe_name = Path(uploaded.name).name  # descarta qualquer componente de diretório
            if safe_name != uploaded.name or ".." in uploaded.name:
                raise ValueError(f"Nome de arquivo inválido: {uploaded.name}")
            ext = Path(safe_name).suffix.lower()
            if ext not in MUNICIPIO_SHP_COMPONENT_EXTENSIONS:
                raise ValueError(f"Extensão não permitida entre os componentes do shapefile: {safe_name}")
            with open(tmp_dir / safe_name, "wb") as out:
                out.write(uploaded.getbuffer())

        shp_path = tmp_dir / Path(shp_files[0].name).name
        missing = [ext for ext in (".shx", ".dbf") if not (tmp_dir / (shp_path.stem + ext)).exists()]
        if missing:
            raise ValueError(f"Faltam componentes obrigatórios do shapefile: {', '.join(missing)}")

        gdf = gpd.read_file(shp_path)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        return gdf
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def uploaded_shapefile_to_region_geojson(uploaded_files, max_size=None) -> dict:
    """Converte um shapefile próprio enviado pelo usuário (área de interesse
    alternativa ao ponto+buffer/município do IBGE, ver api/routes/metrics.py)
    num GeoJSON no mesmo formato que `municipio_geojson` (`{"features": [...]}`,
    EPSG:4326) — reaproveitado por `_build_mapbiomas_roi`/
    `extract_landscape_from_tif` sem precisar diferenciar a origem do
    polígono. Se o arquivo tiver mais de uma geometria (ex.: várias
    feições/talhões), todas são unidas (`unary_union`) numa única região —
    a análise de paisagem trata a área de interesse como um polígono só."""
    from shapely.ops import unary_union

    gdf = _municipio_files_to_gdf(uploaded_files, max_size=max_size)
    if gdf.empty:
        raise ValueError("O shapefile enviado não contém nenhuma geometria.")
    if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    geoms = list(gdf.geometry)
    region_geom = geoms[0] if len(geoms) == 1 else unary_union(geoms)
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": mapping(region_geom)}],
    }


def _utm_epsg_for_lonlat(lon: float, lat: float) -> int:
    """EPSG da zona UTM (WGS84) que contém o ponto — usado para reprojetar
    automaticamente um GeoTIFF geográfico quando há um ponto de interesse
    (recorte pequeno ao redor de um ponto, então uma única zona UTM é
    localmente precisa)."""
    zone = int((lon + 180) / 6) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


def _array_to_geotiff_bytes(array, transform, crs, nodata) -> bytes:
    """Serializa um array 2D (uint8) + transform/crs/nodata como bytes de um
    GeoTIFF de 1 banda — usado para oferecer o download do raster que
    efetivamente alimentou o cálculo (após reprojeção automática, se houve)."""
    profile = {
        "driver": "GTiff",
        "height": array.shape[0],
        "width": array.shape[1],
        "count": 1,
        "dtype": "uint8",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "lzw",
    }
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dataset:
            dataset.write(array.astype("uint8"), 1)
        return bytes(memfile.read())


def _crop_and_mask_array(array, transform, geometry, nodata):
    """Recorta `array` para a bounding box de `geometry` e aplica `nodata`
    fora dela — equivalente a `rasterio.mask.mask(..., crop=True)`, mas
    operando direto sobre um array já em memória (sem precisar reabrir um
    dataset), usado depois da reprojeção automática de um GeoTIFF
    geográfico."""
    mask = geometry_mask([mapping(geometry)], out_shape=array.shape, transform=transform, invert=True)
    if not mask.any():
        raise ValueError("A área do buffer não intersecta o raster enviado.")

    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    rmin, rmax = rows[0], rows[-1]
    cmin, cmax = cols[0], cols[-1]

    cropped = array[rmin:rmax + 1, cmin:cmax + 1].copy()
    cropped_mask = mask[rmin:rmax + 1, cmin:cmax + 1]
    cropped[~cropped_mask] = nodata
    new_transform = transform * Affine.translation(cmin, rmin)
    return cropped, new_transform


def _save_uploaded_tif_to_temp(uploaded_tif, on_progress=None, temp_path_out=None):
    """Valida e salva o GeoTIFF enviado num arquivo temporário seguro,
    escrevendo em blocos (em vez de um único write) para poder reportar
    progresso real, proporcional aos bytes já gravados — relevante para
    arquivos de até 5GB (MAX_TIF_SIZE).

    Retorna o caminho do arquivo salvo. Se temp_path_out for informado, o
    caminho também é anexado a essa lista (permite que o chamador adie a
    limpeza — ver `extract_landscape_from_tif`)."""
    def _report(fraction, label):
        if on_progress:
            on_progress(fraction, label)

    is_valid, message = validate_file_upload(uploaded_tif, ALLOWED_TIF_EXTENSIONS, MAX_TIF_SIZE)
    if not is_valid:
        raise ValueError(f"Arquivo inválido: {message}")

    file_extension = Path(uploaded_tif.name).suffix.lower()
    safe_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(tempfile.gettempdir(), safe_filename)

    temp_dir = Path(tempfile.gettempdir()).resolve()
    file_path_resolved = Path(file_path).resolve()
    if not str(file_path_resolved).startswith(str(temp_dir)):
        raise ValueError("Caminho de arquivo inseguro")

    if temp_path_out is not None:
        temp_path_out.append(file_path)

    _report(0.0, "Salvando arquivo enviado...")
    raw_buffer = uploaded_tif.getbuffer()
    total_bytes = len(raw_buffer) or 1
    chunk_size = 8 * 1024 * 1024  # 8MB
    with open(file_path, "wb") as f:
        for offset in range(0, total_bytes, chunk_size):
            f.write(raw_buffer[offset:offset + chunk_size])
            written = min(offset + chunk_size, total_bytes)
            _report(0.5 * written / total_bytes, "Salvando arquivo enviado...")

    return file_path


def extract_landscape_from_tif(
    uploaded_tif, point_lonlat=None, buffer_dist=None, on_progress=None,
    cleanup=True, temp_path_out=None, region_geojson=None,
):
    """
    Extrai as classes de cobertura do solo do GeoTIFF enviado pelo usuário —
    alternativa a extrair os mesmos dados via MapBiomas/Earth Engine. Três
    modos, conforme os argumentos:

    - `point_lonlat` e `buffer_dist` informados: recorta apenas a área do
      buffer (ponto + raio em metros) ao redor do ponto de interesse.
    - `region_geojson` informado (GeoJSON EPSG:4326, ver
      `_ibge_get_municipio_geojson`): recorta pela geometria exata (ex.:
      limite municipal), em vez de um buffer circular. Mutuamente exclusivo
      com `point_lonlat`/`buffer_dist`.
    - Nenhum dos dois informado: lê o raster inteiro, sem recorte.

    Se o GeoTIFF estiver em CRS geográfico (graus), é reprojetado
    automaticamente antes da extração:
    - Com ponto de interesse: recorta uma janela (com margem) ao redor do
      ponto ainda em graus e reprojeta só essa janela para a zona UTM que
      contém o ponto.
    - Sem ponto (modo raster inteiro): reprojeta para SIRGAS 2000/Brazil
      Polyconic (EPSG:5880). Se o raster tiver mais de
      `WHOLE_RASTER_MAX_PIXELS`, é reamostrado por moda (nunca interpolado —
      dado é categórico) antes da reprojeção, para caber na memória do
      processo.

    Retorna `(array, resolution, reprojected_tif_bytes)` — o terceiro item é
    `None` se o raster já estava projetado, ou os bytes do GeoTIFF final
    (já recortado/reprojetado) se houve conversão automática.

    Por padrão (`cleanup=True`), o arquivo temporário em disco é sempre
    removido no `finally`. O chamador pode passar `cleanup=False` para adiar
    a remoção (ex.: lote de múltiplos arquivos) — nesse caso, o caminho do
    arquivo é anexado a `temp_path_out` (se informada) para que o chamador
    possa limpá-lo depois."""
    file_path = _save_uploaded_tif_to_temp(uploaded_tif, on_progress=on_progress, temp_path_out=temp_path_out)
    try:
        return _clip_raster_at_path(
            file_path, point_lonlat=point_lonlat, buffer_dist=buffer_dist,
            region_geojson=region_geojson, on_progress=on_progress,
        )
    finally:
        if cleanup and os.path.exists(file_path):
            try:
                os.remove(file_path)
                if on_progress:
                    on_progress(1.0, "Arquivo temporário descartado")
            except Exception as cleanup_error:
                logger.warning(f"Erro ao limpar arquivo temporário: {cleanup_error}")


def _clip_raster_at_path(
    file_path, point_lonlat=None, buffer_dist=None, region_geojson=None,
    on_progress=None, want_reprojected_bytes=True,
):
    """Abre o GeoTIFF já salvo em `file_path` e extrai as classes de
    cobertura do solo — núcleo de `extract_landscape_from_tif`, extraído
    para poder ser chamado repetidamente sobre o MESMO arquivo em disco sem
    reescrevê-lo a cada vez (usado pelo lote por município, que recorta o
    mesmo raster uma vez por município do shapefile enviado). Aceita os
    mesmos `point_lonlat`/`buffer_dist`/`region_geojson` de
    `extract_landscape_from_tif` e retorna o mesmo formato
    `(array, resolution, reprojected_tif_bytes)` — exceto que
    `reprojected_tif_bytes` fica sempre `None` se `want_reprojected_bytes`
    for `False`."""
    def _report(fraction, label):
        if on_progress:
            on_progress(fraction, label)

    has_point_region = point_lonlat is not None and buffer_dist is not None
    has_municipio_region = region_geojson is not None
    municipio_geom_wgs84 = _municipio_geometry_shapely(region_geojson) if has_municipio_region else None

    _report(0.55, "Abrindo raster e validando projeção...")
    reprojected = False
    with rasterio.open(file_path) as src:
        if src.crs is None:
            raise ValueError("O GeoTIFF não tem CRS (sistema de referência) definido.")

        src_nodata = src.nodata if src.nodata is not None else 0

        if src.crs.is_geographic:
            reprojected = True

            if has_point_region:
                _report(0.60, "CRS geográfico detectado — recortando janela ao redor do ponto...")
                lon, lat = point_lonlat
                margin_m = buffer_dist * 3 + 1000
                lat_margin_deg = margin_m / 111_320
                lon_margin_deg = margin_m / (111_320 * max(np.cos(np.radians(lat)), 0.1))
                window = from_bounds(
                    lon - lon_margin_deg, lat - lat_margin_deg,
                    lon + lon_margin_deg, lat + lat_margin_deg,
                    transform=src.transform,
                ).round_lengths().round_offsets()
                window = window.intersection(Window(0, 0, src.width, src.height))
                if window.width <= 0 or window.height <= 0:
                    raise ValueError("O ponto selecionado está fora da extensão do raster enviado.")

                src_array = src.read(1, window=window)
                src_transform = window_transform(window, src.transform)
                dst_crs = f"EPSG:{_utm_epsg_for_lonlat(lon, lat)}"
            elif has_municipio_region:
                _report(0.60, "CRS geográfico detectado — recortando janela ao redor do município...")
                min_lon, min_lat, max_lon, max_lat = municipio_geom_wgs84.bounds
                margin_deg = 0.02
                window = from_bounds(
                    min_lon - margin_deg, min_lat - margin_deg,
                    max_lon + margin_deg, max_lat + margin_deg,
                    transform=src.transform,
                ).round_lengths().round_offsets()
                window = window.intersection(Window(0, 0, src.width, src.height))
                if window.width <= 0 or window.height <= 0:
                    raise ValueError("O município selecionado está fora da extensão do raster enviado.")

                src_array = src.read(1, window=window)
                src_transform = window_transform(window, src.transform)
                centroid = municipio_geom_wgs84.centroid
                dst_crs = f"EPSG:{_utm_epsg_for_lonlat(centroid.x, centroid.y)}"
            else:
                total_pixels = src.width * src.height
                if total_pixels > WHOLE_RASTER_MAX_PIXELS:
                    scale = int(np.ceil(np.sqrt(total_pixels / WHOLE_RASTER_MAX_PIXELS)))
                    out_height = max(src.height // scale, 1)
                    out_width = max(src.width // scale, 1)
                    _report(
                        0.60,
                        f"CRS geográfico detectado — raster grande demais "
                        f"({total_pixels:,} pixels), reamostrando por moda "
                        f"(fator {scale}x) antes de reprojetar...",
                    )
                    src_array = src.read(1, out_shape=(out_height, out_width), resampling=Resampling.mode)
                    src_transform = src.transform * src.transform.scale(
                        src.width / out_width, src.height / out_height
                    )
                else:
                    _report(0.60, "CRS geográfico detectado — preparando reprojeção do raster inteiro...")
                    src_array = src.read(1)
                    src_transform = src.transform
                dst_crs = "EPSG:5880"

            src_crs = src.crs
            _report(0.70, f"Reprojetando para {dst_crs} (dado categórico — sem interpolação)...")
            dst_transform, dst_width, dst_height = calculate_default_transform(
                src_crs, dst_crs, src_array.shape[1], src_array.shape[0],
                left=src_transform.c,
                top=src_transform.f,
                right=src_transform.c + src_array.shape[1] * src_transform.a,
                bottom=src_transform.f + src_array.shape[0] * src_transform.e,
            )
            dst_array = np.zeros((dst_height, dst_width), dtype=np.uint8)
            reproject(
                source=src_array,
                destination=dst_array,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.nearest,
                src_nodata=src_nodata,
                dst_nodata=0,
            )

            array = dst_array
            out_transform = dst_transform
            out_crs = dst_crs
            nodata_value = 0
            resolution = (abs(dst_transform.a), abs(dst_transform.e))

            if has_point_region:
                _report(0.85, "Recortando a área do buffer (pós-reprojeção)...")
                transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
                x, y = transformer.transform(lon, lat)
                buffer_geom = Point(x, y).buffer(buffer_dist)
                array, out_transform = _crop_and_mask_array(array, out_transform, buffer_geom, nodata_value)
            elif has_municipio_region:
                _report(0.85, "Recortando o limite municipal (pós-reprojeção)...")
                transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
                municipio_geom_dst = shapely_transform(transformer.transform, municipio_geom_wgs84)
                array, out_transform = _crop_and_mask_array(array, out_transform, municipio_geom_dst, nodata_value)
        else:
            nodata_value = src_nodata
            out_crs = src.crs
            resolution = (abs(src.res[0]), abs(src.res[1]))

            if has_point_region:
                transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                x, y = transformer.transform(point_lonlat[0], point_lonlat[1])
                buffer_geom = Point(x, y).buffer(buffer_dist)

                _report(0.8, "Recortando a área do buffer...")
                try:
                    out_image, out_transform = rio_mask(src, [mapping(buffer_geom)], crop=True, nodata=nodata_value)
                except ValueError as mask_error:
                    raise ValueError("A área do buffer não intersecta o raster enviado.") from mask_error
                array = out_image[0]
            elif has_municipio_region:
                transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                municipio_geom_dst = shapely_transform(transformer.transform, municipio_geom_wgs84)

                _report(0.8, "Recortando o limite municipal...")
                try:
                    out_image, out_transform = rio_mask(
                        src, [mapping(municipio_geom_dst)], crop=True, nodata=nodata_value
                    )
                except ValueError as mask_error:
                    raise ValueError("O limite municipal não intersecta o raster enviado.") from mask_error
                array = out_image[0]
            else:
                _report(0.8, "Lendo o raster completo...")
                array = src.read(1)
                out_transform = src.transform

    if array.size == 0 or np.all(array == nodata_value):
        raise ValueError(
            "Nenhum pixel válido encontrado no raster enviado "
            + ("dentro da área do buffer. Aumente o buffer, escolha outro ponto, ou "
               "confirme que o raster cobre essa área."
               if has_point_region else
               "dentro do limite municipal. Confirme que o raster cobre essa região."
               if has_municipio_region else
               "— o arquivo parece conter apenas valores nodata.")
        )

    reprojected_tif_bytes = None
    if reprojected and want_reprojected_bytes:
        _report(0.95, "Gerando arquivo reprojetado para download...")
        reprojected_tif_bytes = _array_to_geotiff_bytes(array, out_transform, out_crs, nodata_value)

    _report(0.98, "Extração concluída")
    return array, resolution, reprojected_tif_bytes


def _compute_class_metrics(np_arr_mb, resolution, notify=None, on_metric_progress=None):
    """Instancia pls.Landscape e calcula a tabela de métricas por classe
    (filtrada a >10% de proporção da paisagem, com nomes de classe do
    MapBiomas) — etapa compartilhada entre a fonte MapBiomas/GEE e o(s)
    GeoTIFF(s) próprio(s) enviado(s) pelo usuário. Levanta RuntimeError com
    contexto se o array for inválido para o PyLandStats ou se o cálculo de
    métricas falhar — nunca retorna uma métrica parcial/fabricada.

    Calcula uma métrica por vez (em vez de todas numa única chamada) para
    poder reportar progresso real via `on_metric_progress(i, total, label)`
    antes de cada uma — medido empiricamente sem custo adicional relevante
    (o PyLandStats reaproveita internamente os cálculos de patch já feitos
    no mesmo objeto `Landscape` entre chamadas).

    `notify`, se informado, recebe mensagens de progresso (ex.: `st.write`
    no app Streamlit) — opcional, pode ser omitido pelo backend FastAPI."""
    def _notify(msg):
        if notify:
            notify(msg)

    if np_arr_mb.shape[0] < 3 or np_arr_mb.shape[1] < 3:
        _notify("⚠️ Área pequena, expandindo para análise...")
        np_arr_mb = np.pad(np_arr_mb, ((1, 1), (1, 1)), mode='constant', constant_values=0)

    try:
        ls = pls.Landscape(np_arr_mb, res=resolution)
    except Exception as pls_error:
        logger.error(f"Erro no PyLandStats: {pls_error}")
        raise RuntimeError(
            f"Erro ao processar métricas da paisagem: {pls_error}. Forma do "
            f"array: {np_arr_mb.shape}. Valores únicos: {np.unique(np_arr_mb)}"
        ) from pls_error

    try:
        total_metrics = len(METRICS_INFO)
        per_metric_dfs = []
        for i, (metric_name, _icon, metric_label) in enumerate(METRICS_INFO):
            if on_metric_progress:
                on_metric_progress(i, total_metrics, metric_label)
            if metric_name == SLOW_METRIC_NAME:
                _notify(
                    f"⏳ Calculando '{metric_label}' — mede a distância entre todas as "
                    "manchas da mesma classe, então demora mais em áreas com muitas "
                    "manchas pequenas. As outras métricas já estão prontas."
                )
            per_metric_dfs.append(ls.compute_class_metrics_df(metrics=[metric_name]))

        class_metrics_df = pd.concat(per_metric_dfs, axis=1)
        classes_index = list(map(int, class_metrics_df.index))
        legend_dict = {i: name for i, name in enumerate(MAPBIOMAS_LEGEND_KEYS)}
        class_metrics_df.index = [legend_dict.get(x, f'Classe {x}') for x in classes_index]

        class_metrics_df_sub = class_metrics_df[class_metrics_df['proportion_of_landscape'] > 10]
        class_metrics_df_sub = class_metrics_df_sub.sort_values(by=['total_area'], ascending=False)

        if class_metrics_df_sub.empty:
            _notify("⚠️ Nenhuma classe com proporção > 10% encontrada. Mostrando todas as classes.")
            class_metrics_df_sub = class_metrics_df.sort_values(by=['total_area'], ascending=False)
    except Exception as metrics_error:
        logger.error(f"Erro ao calcular métricas: {metrics_error}")
        raise RuntimeError(f"Erro ao calcular métricas da paisagem: {metrics_error}") from metrics_error

    return ls, class_metrics_df_sub


def sanitize_for_json(value):
    """Substitui NaN/±Infinity por `None`, recursivamente, em dicts/listas —
    `float('nan')` é um valor Python válido (e comum em métricas do
    PyLandStats com poucas classes/manchas), mas o `JSONResponse` do
    FastAPI/Starlette serializa com `allow_nan=False` (JSON estrito),
    levantando `ValueError: Out of range float values are not JSON
    compliant` para qualquer resposta que contenha um. Usar em qualquer
    dict/lista de métricas antes de devolver como resposta HTTP."""
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_json(v) for v in value]
    return value


def diversity_indices_from_proportions(proportions) -> dict:
    """Calcula SHDI/SHEI/SIDI/SIEI/riqueza de manchas a partir de uma série
    de proporções de área por classe (soma ~1.0) — fórmulas padrão do
    FRAGSTATS, sem método dedicado equivalente no PyLandStats 3.1.0 usado
    neste projeto. Função pura (sem `pls.Landscape`), reaproveitada tanto por
    `_compute_landscape_metrics` (que já tem os patches calculados via
    PyLandStats) quanto por `app.services.diversity_atlas` (que parte direto
    de área por classe agregada em `mapbiomas_municipio_stats`, sem nunca
    abrir um raster — ver Atlas Nacional de Paisagem).

    `proportions` é qualquer sequência de proporções (ex.: `pd.Series`) já
    normalizada para somar ~1.0 entre as classes presentes."""
    richness = len(proportions)
    values: dict = {"patch_richness": richness}

    shdi = -float(sum(p * np.log(p) for p in proportions if p > 0)) if richness > 0 else None
    values["shannon_diversity_index"] = shdi
    values["shannon_evenness_index"] = shdi / np.log(richness) if shdi is not None and richness > 1 else None

    sidi = 1 - float(sum(p ** 2 for p in proportions)) if richness > 0 else None
    values["simpson_diversity_index"] = sidi
    values["simpson_evenness_index"] = sidi / (1 - 1 / richness) if sidi is not None and richness > 1 else None

    return values


def _compute_landscape_metrics(ls) -> dict:
    """Calcula métricas de nível de PAISAGEM (um único valor global, não
    por classe) — diversidade e agregação da paisagem como um todo,
    complementando as métricas por classe de `_compute_class_metrics`. Não
    levanta exceção: se o PyLandStats falhar num valor específico (raro,
    mas pode ocorrer com só 1 classe presente), essa entrada fica `None`
    em vez de derrubar o cálculo inteiro."""
    try:
        df = ls.compute_landscape_metrics_df(
            metrics=[
                'shannon_diversity_index', 'contagion', 'effective_mesh_size',
                'patch_density', 'edge_density', 'landscape_shape_index',
            ]
        )
        values = df.iloc[0].to_dict()
    except Exception as landscape_error:
        logger.warning(f"Erro ao calcular métricas de paisagem (PyLandStats): {landscape_error}")
        values = {}

    # SHEI/SIDI/SIEI/PR: recalculados aqui (não reaproveita o
    # 'shannon_diversity_index' do PyLandStats acima) para que os quatro
    # índices venham da mesma fonte (proporções por classe) e fiquem
    # mutuamente consistentes — ver `diversity_indices_from_proportions`.
    try:
        proportions = ls.compute_class_metrics_df(
            metrics=['proportion_of_landscape']
        )['proportion_of_landscape'] / 100
        values.update(diversity_indices_from_proportions(proportions))
    except Exception as diversity_error:
        logger.warning(f"Erro ao calcular índices de diversidade manuais: {diversity_error}")

    # Métricas vindas direto do PyLandStats (contagion, effective_mesh_size
    # etc.) podem vir NaN com poucas classes/manchas (ex.: só 1 classe
    # presente) — diferente das fórmulas manuais acima, que já usam `None`
    # nesse caso. `FastAPI`/Starlette serializam a resposta com
    # `allow_nan=False` (JSON estrito), então um NaN cru aqui quebra a
    # request inteira com "Out of range float values are not JSON
    # compliant" — normalizado para `None` (sempre serializável).
    return sanitize_for_json(values)


def _extract_year_from_filename(filename: str):
    """Extrai um ano plausível (19xx/20xx) do nome do arquivo, para ordenar
    e rotular a comparação temporal entre múltiplos GeoTIFFs (ex.:
    'Corte_255_2010.tif' -> 2010). Usa o último padrão encontrado. Retorna
    `None` se não encontrar nenhum."""
    matches = re.findall(r'(?:19|20)\d{2}', filename)
    return int(matches[-1]) if matches else None


def _compute_fingerprint(data_source, tif_bytes=None, point_lonlat=None,
                          buffer_dist=None, whole_raster=False, municipio_codigo=None,
                          custom_region_bytes=None) -> str:
    """Identifica de forma estável 'esta mesma submissão', para o cache de
    resultados (db.metric_results) — uma resubmissão com a mesma
    fingerprint reaproveita o resultado já calculado em vez de refazer a
    extração (Earth Engine/GeoTIFF) e o PyLandStats.

    - GeoTIFF (com ou sem ponto/município): hash dos bytes do arquivo
      enviado. `whole_raster` entra na fingerprint para não colidir o mesmo
      arquivo submetido com ponto numa vez e sem ponto em outra.
    - MapBiomas ou GeoTIFF com área municipal: hash do código IBGE do
      município, no lugar de ponto/buffer.
    - MapBiomas com ponto (sem arquivo): hash do ponto (arredondado a 5
      casas, ~1,1m) + buffer.
    - Área definida por shapefile próprio: hash dos bytes brutos do(s)
      arquivo(s) enviados (`custom_region_bytes`), no lugar de
      ponto/buffer/município — mesmo arquivo reenviado reaproveita o cache."""
    hasher = hashlib.sha256()
    hasher.update(data_source.encode("utf-8"))
    hasher.update(b"|whole" if whole_raster else b"|point")
    if tif_bytes is not None:
        hasher.update(b"|tif|")
        hasher.update(tif_bytes)
    if municipio_codigo is not None:
        hasher.update(f"|municipio|{municipio_codigo}".encode("utf-8"))
    if custom_region_bytes is not None:
        hasher.update(b"|shp|")
        hasher.update(custom_region_bytes)
    if point_lonlat is not None:
        lon, lat = point_lonlat
        hasher.update(f"|point|{round(lon, 5)},{round(lat, 5)}".encode("utf-8"))
    if buffer_dist is not None:
        hasher.update(f"|buffer|{round(buffer_dist)}".encode("utf-8"))
    return hasher.hexdigest()


def _municipio_geometry_shapely(municipio_geojson: dict):
    """Extrai a geometria (Shapely, EPSG:4326) da(s) feature(s) retornada(s)
    pela malha do IBGE — normalmente uma única feature por município, mas
    combina via `unary_union` se vier mais de uma (defensivo)."""
    from shapely.ops import unary_union

    geoms = [shape(feat["geometry"]) for feat in municipio_geojson["features"]]
    return geoms[0] if len(geoms) == 1 else unary_union(geoms)


@functools.lru_cache(maxsize=256)
def _ibge_get_municipio_geojson(codigo: str) -> dict | None:
    """Busca o polígono (GeoJSON, EPSG:4326) do limite do município na malha
    territorial do IBGE — usado como área de interesse alternativa ao
    ponto+buffer. `qualidade=minima` mantém o payload pequeno.

    Segue a mesma regra do resto do app: se a API falhar, retorna `None` em
    vez de inventar uma geometria — o chamador interrompe o fluxo com uma
    mensagem explicando a causa, nunca segue adiante com um limite
    fabricado."""
    try:
        resp = requests.get(
            f"{IBGE_MALHAS_BASE}/municipios/{codigo}",
            params={"formato": "application/vnd.geo+json", "qualidade": "minima"},
            timeout=IBGE_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        geojson = resp.json()
    except (requests.RequestException, ValueError) as ibge_error:
        logger.warning(f"Falha ao buscar malha municipal do IBGE (código {codigo}): {ibge_error}")
        return None

    if not geojson.get("features"):
        return None
    return geojson


def _build_transition_matrix(class_arrays: list, years: list) -> "pd.DataFrame":
    """Constrói a matriz de transição de probabilidade (classe origem ×
    classe destino) a partir de uma série de arrays de classe — base da
    predição de anos futuros (`_project_future_landcover`, cadeia de
    Markov). Soma as transições pixel-a-pixel de TODOS os pares de anos
    consecutivos disponíveis (não só o primeiro/último), para aproveitar
    toda a série.

    Se dois arrays consecutivos tiverem shapes diferentes (arquivos de
    resoluções/extents ligeiramente diferentes entre si), o array mais
    recente do par é reamostrado por nearest-neighbor
    (`scipy.ndimage.zoom`, ordem 0 — dado categórico, nunca interpolado)
    para o shape do array anterior antes de comparar — aproximação
    necessária para alinhar pixel-a-pixel, documentada aqui para quem for
    interpretar o resultado."""
    order = np.argsort(years)
    arrays_sorted = [class_arrays[i] for i in order]

    all_classes = sorted({int(c) for arr in arrays_sorted for c in np.unique(arr)})
    counts = pd.DataFrame(0.0, index=all_classes, columns=all_classes)

    for arr_before, arr_after in zip(arrays_sorted[:-1], arrays_sorted[1:]):
        if arr_before.shape != arr_after.shape:
            zoom_factors = (
                arr_before.shape[0] / arr_after.shape[0],
                arr_before.shape[1] / arr_after.shape[1],
            )
            arr_after = ndimage_zoom(arr_after, zoom_factors, order=0)
            min_rows = min(arr_before.shape[0], arr_after.shape[0])
            min_cols = min(arr_before.shape[1], arr_after.shape[1])
            arr_before_cmp = arr_before[:min_rows, :min_cols]
            arr_after_cmp = arr_after[:min_rows, :min_cols]
        else:
            arr_before_cmp, arr_after_cmp = arr_before, arr_after

        pair_counts = pd.crosstab(arr_before_cmp.ravel(), arr_after_cmp.ravel())
        counts = counts.add(pair_counts, fill_value=0.0)

    counts = counts.reindex(index=all_classes, columns=all_classes, fill_value=0.0)
    row_sums = counts.sum(axis=1)
    transition = counts.div(row_sums, axis=0)

    # Linhas sem nenhuma transição observada (classe nunca apareceu como
    # "origem" em nenhum par de anos): assume identidade (sem mudança) como
    # fallback conservador — evita NaN, que quebraria a soma de
    # probabilidade = 1 exigida pela projeção via matriz.
    for cls in counts.index[row_sums == 0]:
        transition.loc[cls, cls] = 1.0
    return transition.fillna(0.0)


def _project_future_landcover(
    transition_df: "pd.DataFrame", last_year: int, last_proportions: "pd.Series",
    avg_interval: float, target_years: list,
) -> "pd.DataFrame":
    """Projeta a proporção de cada classe para os `target_years` informados,
    usando a cadeia de Markov definida por `transition_df` (ver
    `_build_transition_matrix`). `avg_interval` é o intervalo médio (anos)
    entre as observações usadas para construir a matriz — define o
    "tamanho do passo" de uma aplicação dela. Para anos-alvo que não caem
    num múltiplo exato desse intervalo, usa potência fracionária da matriz
    (`scipy.linalg.fractional_matrix_power`) — pode gerar pequenos
    artefatos numéricos (proporções levemente negativas ou passando de
    100%), por isso o resultado é sempre clampado a >= 0 e renormalizado
    para somar 100%.

    Método não-espacial: projeta só a distribuição agregada de classes, não
    um mapa futuro — assume estacionariedade das probabilidades de
    transição observadas no período histórico disponível."""
    classes = list(transition_df.index)
    transition_matrix = transition_df.reindex(index=classes, columns=classes, fill_value=0.0).to_numpy()
    v0 = np.array([last_proportions.get(c, 0.0) for c in classes])

    rows = []
    for target_year in target_years:
        n_steps = (target_year - last_year) / avg_interval
        if n_steps <= 0:
            continue
        try:
            step_matrix = np.real(fractional_matrix_power(transition_matrix, n_steps))
        except Exception as power_error:
            logger.warning(f"fractional_matrix_power falhou ({power_error}); usando potência inteira mais próxima.")
            step_matrix = np.linalg.matrix_power(transition_matrix, max(round(n_steps), 1))
        projected = np.clip(v0 @ step_matrix, 0.0, None)
        total = projected.sum()
        if total > 0:
            projected = projected / total * 100
        rows.append([target_year, *projected])

    return pd.DataFrame(rows, columns=["ano", *classes]).set_index("ano")


# Nomes de coluna mais comuns nas malhas municipais do IBGE (varia entre
# publicações/anos) — usados por `_detect_municipio_columns` para
# pré-selecionar código/nome/UF no upload de shapefile de municípios
# (Métricas por município em lote), sempre editável pelo usuário na UI caso
# a detecção erre ou o shapefile venha de outra fonte.
MUNICIPIO_CODE_COL_CANDIDATES = ["CD_MUN", "CD_GEOCMU", "GEOCODIGO", "CD_GEOCODM", "CD_MUNICIP", "GEOCOD_MUN"]
MUNICIPIO_NAME_COL_CANDIDATES = ["NM_MUN", "NM_MUNICIP", "NM_MUNICIPIO", "NOME"]
MUNICIPIO_UF_COL_CANDIDATES = ["SIGLA_UF", "UF", "SIGLA"]


def _detect_municipio_columns(gdf) -> dict:
    """Tenta identificar, por nome (case-insensitive), quais colunas do
    shapefile de municípios enviado pelo usuário trazem o código IBGE, o
    nome e a UF de cada município — shapefiles de fontes/anos diferentes da
    malha do IBGE usam nomes de coluna diferentes, então isso é só um ponto
    de partida, sempre editável pelo chamador.

    Retorna `{"codigo": nome_da_coluna_ou_None, "nome": ..., "uf": ...}`.

    Nota: parte de um trio de funções (`_municipio_files_to_gdf`,
    `_run_municipio_batch`, `_build_municipio_batch_workbook`) que compunham
    o recurso "Métricas por município em lote" só em app.py (Streamlit,
    removido) — essa é a única das quatro sem dependência de
    `uploaded_file_to_gdf`/persistência, por isso foi a única portada nesta
    migração. As outras três (e o recurso completo) ficam descobertas — ver
    ROADMAP.md."""
    columns_by_lower = {str(col).lower(): col for col in gdf.columns}

    def _find(candidates):
        for candidate in candidates:
            match = columns_by_lower.get(candidate.lower())
            if match is not None:
                return match
        return None

    return {
        "codigo": _find(MUNICIPIO_CODE_COL_CANDIDATES),
        "nome": _find(MUNICIPIO_NAME_COL_CANDIDATES),
        "uf": _find(MUNICIPIO_UF_COL_CANDIDATES),
    }


def read_shapefile_from_zip(zip_bytes: bytes) -> gpd.GeoDataFrame:
    """Lê um shapefile comprimido em .zip (contendo .shp, .shx, .dbf, etc.)
    diretamente da memória usando fiona/geopandas."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path = tmp.name

    try:
        # A sintaxe zip:// permite que fiona leia shapefiles de dentro do arquivo zip
        gdf = gpd.read_file(f"zip://{tmp_path}")
        return gdf
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

