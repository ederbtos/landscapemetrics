"""
Descrição da funcionalidade
---------------------------
Ponto de entrada do Streamlit e única "página" do app: extrai métricas de
paisagem (composição e configuração da cobertura do solo) num raio ao redor
de um ponto de interesse desenhado pelo usuário, usando dados de uso e
cobertura da terra do MapBiomas via Google Earth Engine. Resolve o problema
de negócio de dar a pesquisadores/técnicos ambientais uma análise de
paisagem pronta (área, número de manchas, forma, proximidade etc.) sem
precisar programar em GEE/PyLandStats.

Contexto técnico
-----------------
Script Streamlit executado top-to-bottom a cada interação do usuário (não é
uma API REST). Depende de: auth.py (login), db.py (credenciais do Earth
Engine por usuário), Earth Engine (`ee`) para acesso aos rasters do
MapBiomas, geemap/streamlit-folium para os mapas interativos e PyLandStats
para o cálculo das métricas de paisagem propriamente ditas. As funções de
domínio (validate_file_upload, initialize_ee, uploaded_file_to_gdf,
extract_landscape_from_tif etc.) ficam no topo do módulo; o restante do
script (login, pipeline, renderização) fica dentro de main(), chamada só sob
`if __name__ == "__main__":` — isso preserva o comportamento sob
`streamlit run app.py` (que executa o script como `__main__`) e ao mesmo
tempo permite `import app` num processo de teste sem disparar a aplicação
inteira (ver tests/test_app_validation.py e tests/test_app_tif.py).

Regras de negócio
------------------
- Um único ponto de interesse por execução; múltiplos pontos no arquivo são
  rejeitados (dentro de main(), logo após a conversão para GeoDataFrame).
- Buffer configurável entre MIN_BUFFER e MAX_BUFFER metros ao redor do ponto.
- Upload do ponto restrito a `.geojson` ou shapefile compactado em `.zip`
  (`.shp`+`.shx`+`.dbf`+`.prj`), até MAX_FILE_SIZE, com sanitização de nome
  de arquivo (ver validate_file_upload).
- Nenhuma métrica é exibida ou exportada sem dados reais por trás: se a
  extração via Earth Engine (ou do GeoTIFF próprio) falhar em qualquer
  estágio, o processamento é interrompido com uma mensagem explicando a
  causa provável, nunca substituído por dados fabricados (ver
  "Mudança de arquitetura" no ROADMAP.md — uma versão anterior deste app
  chegou a mascarar essas falhas com uma matriz fixa fictícia de exemplo;
  esse comportamento foi removido deliberadamente por risco de o usuário
  tratar uma análise inválida como real).

Pontos de atenção
------------------
- Múltiplos blocos de try/except aninhados com lógica de fallback (troca de
  collection do MapBiomas, sampleRectangle → reduceRegion) tornam o fluxo
  difícil de auditar e de testar; um refactor extraindo cada etapa (seleção
  de asset, extração de pixels, cálculo de métricas) em funções puras
  testáveis, além das já extraídas, reduziria esse custo de manutenção.
- `except:` bare no botão "Status GEE" (sidebar) engole qualquer exceção,
  inclusive erros de programação, não só falha de conectividade.

Melhorias sugeridas
---------------------
- Extrair a lógica de negócio do pipeline principal (seleção de asset
  MapBiomas, extração de pixels, cálculo de métricas) do corpo de main()
  para funções puras adicionais, no mesmo espírito de
  extract_landscape_from_tif — reduz ainda mais a superfície não testada
  automaticamente (ver documentation/13_testing.md).
"""
# Instalacao de bibliotecas necessarias
import streamlit as st

# IMPORTANTE: st.set_page_config() DEVE ser a primeira função Streamlit
st.set_page_config(
    page_title="Landscape Metrics Extractor",
    page_icon="🏞️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

import geemap.foliumap as geemap
from streamlit_folium import st_folium
import json
import ee
import numpy as np
import matplotlib.pyplot as plt
import altair as alt
import pandas as pd
import pylandstats as pls
import collections
import geopandas as gpd
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from rasterio.windows import Window, from_bounds, transform as window_transform
from rasterio.features import geometry_mask
from affine import Affine
from pyproj import Transformer
from shapely.geometry import Point, mapping
import tempfile
import os
import io
import re
import base64
import time
import hashlib
import uuid
import logging
from pathlib import Path

import auth
import db

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Linha de compatibilidade
collections.Callable = collections.abc.Callable

# Configurações de segurança
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'.geojson', '.zip'}  # .zip = shapefile compactado (.shp+.shx+.dbf+.prj)
MAX_TIF_SIZE = 5 * 1024 * 1024 * 1024  # 5GB (server.maxUploadSize em .streamlit/config.toml precisa bater com isso)
ALLOWED_TIF_EXTENSIONS = {'.tif', '.tiff'}
MIN_BUFFER = 1000
MAX_BUFFER = 10000

# Nome interno (usado em pls.Landscape.compute_class_metrics_df), ícone e
# tradução de cada métrica — fonte única usada tanto na revelação
# progressiva durante o cálculo quanto no expander "Detalhamento das
# métricas" no rodapé, para não duplicar a lista em dois lugares.
#
# ORDEM DELIBERADA (2026-07-07, medida por benchmark — ver
# `_compute_class_metrics`/`SLOW_METRIC_NAME`): métricas sem dependência de
# outros patches vêm primeiro (quase instantâneas, ~0-0,4s cada — a
# primeira chamada aquece o cache interno de geometria de patch que as
# demais reaproveitam), seguidas pelas métricas de área central (custo
# próprio moderado, ~0,5-0,7s cada — exigem erosão de borda além da
# geometria básica), e por último a métrica que depende da posição de
# TODOS os patches da classe entre si (euclidean_nearest_neighbor_mn,
# ~12,5s num raster de teste 3000×3000 — ~97% do tempo total). Isso faz o
# usuário ver a maioria das métricas quase instantaneamente, em vez de
# esperar a mais lenta no meio da lista antes de ver as rápidas que vinham
# depois dela.
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
    # --- Isolamento (depende da posição de todos os patches entre si —
    # a métrica mais cara de longe, sempre por último) ---
    # EM STANDBY (2026-07-07): desativada temporariamente a pedido do usuário
    # para validar o restante do pipeline (cache, painel de histórico) sem
    # esperar pela métrica mais lenta a cada rodada — ver SLOW_METRIC_NAME.
    # Reativar removendo o comentário da linha abaixo.
    # ('euclidean_nearest_neighbor_mn', '📍', 'Distância média ao vizinho mais próximo (m)'),
]

# Métricas de nível de PAISAGEM (um único valor global, não por classe) —
# complementam METRICS_INFO (nível de classe) com diversidade e agregação.
# `shannon_diversity_index`/`contagion`/`effective_mesh_size`/`patch_density`/
# `edge_density`/`landscape_shape_index` vêm do PyLandStats
# (`compute_landscape_metrics_df`); `shannon_evenness_index`/
# `simpson_diversity_index`/`simpson_evenness_index`/`patch_richness` são
# calculadas manualmente em `_compute_landscape_metrics` — fórmulas padrão
# do FRAGSTATS, sem método dedicado equivalente no PyLandStats 3.1.0 usado
# neste projeto.
#
# Fora do escopo por ora (ver ROADMAP.md): Aggregation Index (AI),
# Clumpiness Index (CLUMPY), Landscape Division Index (DIVISION), Splitting
# Index (SPLIT) — não implementados no PyLandStats instalado (sem método
# equivalente). Interspersion & Juxtaposition Index (IJI), Proximity Index
# e Contiguity Index existem como métodos em `pls.Landscape` mas levantam
# `NotImplementedError` nesta versão (3.1.0) — confirmado testando
# diretamente antes de expor qualquer um deles na interface. Métricas de
# Contraste (ex.: TECI) exigiriam uma matriz de similaridade entre classes
# fornecida pelo usuário, não suportado pela UI atual.
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

def validate_file_upload(uploaded_file, allowed_extensions=None, max_size=None):
    """Valida o arquivo enviado pelo usuário"""
    allowed_extensions = allowed_extensions or ALLOWED_EXTENSIONS
    max_size = max_size or MAX_FILE_SIZE

    if not uploaded_file:
        return False, "Nenhum arquivo enviado"

    # Verifica tamanho do arquivo
    if uploaded_file.size > max_size:
        return False, f"Arquivo muito grande. Máximo: {max_size // (1024*1024)}MB"

    # Verifica extensão
    file_extension = Path(uploaded_file.name).suffix.lower()
    if file_extension not in allowed_extensions:
        return False, f"Extensão não permitida. Permitido: {allowed_extensions}"
    
    # Bloqueia path traversal (".." + separadores) e caracteres inválidos em
    # nomes de arquivo do Windows; o nome original do upload nunca é usado
    # como caminho de disco (uploaded_file_to_gdf gera um nome via uuid4),
    # mas a validação fica como defesa em profundidade caso isso mude.
    if any(char in uploaded_file.name for char in ['..', '/', '\\', '<', '>', '|', '*', '?']):
        return False, "Nome do arquivo contém caracteres não permitidos"

    return True, "Arquivo válido"

def initialize_ee(credentials: dict) -> bool:
    """
    Inicializa o Google Earth Engine usando a credencial de conta de serviço
    do usuário logado (armazenada de forma criptografada no banco local).

    Decisão de projeto: usa o endpoint `earthengine-highvolume` em vez do
    padrão porque o app faz várias chamadas síncronas de leitura de pixels
    por execução (sampleRectangle/reduceRegion); o endpoint high-volume tem
    limites de taxa mais adequados para esse padrão de uso interativo.
    """
    try:
        service_account = credentials.get('client_email')
        ee_credentials = ee.ServiceAccountCredentials(
            service_account,
            key_data=json.dumps(credentials)
        )
        ee.Initialize(
            credentials=ee_credentials,
            opt_url='https://earthengine-highvolume.googleapis.com'
        )
        logger.info("Earth Engine inicializado com sucesso")
        st.sidebar.success("✅ Earth Engine conectado!")
        return True

    except Exception as ex:
        logger.error(f"Falha ao inicializar Earth Engine: {ex}")
        st.error("❌ Falha na inicialização do Earth Engine")
        with st.expander("🔍 Detalhes do erro"):
            st.error(f"Erro: {str(ex)}")
            st.markdown("""
            **Possíveis soluções:**
            1. Confirme que o JSON da conta de serviço está correto
            2. Confirme permissões da conta de serviço no GCP
            3. Verifique se a Earth Engine API está habilitada no projeto
            """)
        return False


def save_gee_credentials_from_json(user_email: str, json_input: str) -> bool:
    """Valida e salva a credencial de conta de serviço do usuário. Retorna True se salvou."""
    try:
        parsed = json.loads(json_input, strict=False)
    except json.JSONDecodeError as json_err:
        st.error(f"❌ Credenciais JSON inválidas: {json_err}")
        return False

    # Validação apenas estrutural (campos presentes), não criptográfica: uma
    # private_key malformada ou uma conta de serviço sem a Earth Engine API
    # habilitada só será detectada depois, em initialize_ee(). Isso é
    # intencional para manter esta função sem dependência do SDK do Earth
    # Engine, mas significa que "salvou com sucesso" não implica "credencial
    # funcional".
    required_fields = ['client_email', 'private_key', 'project_id']
    missing_fields = [field for field in required_fields if not parsed.get(field)]
    if missing_fields:
        st.error(f"❌ Campos obrigatórios ausentes nas credenciais: {missing_fields}")
        return False

    db.save_credentials(user_email, parsed)
    return True

@st.cache_data
def uploaded_file_to_gdf(data):
    """Converte arquivo uploaded para GeoDataFrame com validações de segurança"""
    try:
        # Validação de entrada
        is_valid, message = validate_file_upload(data)
        if not is_valid:
            raise ValueError(f"Arquivo inválido: {message}")
        
        # Cria arquivo temporário seguro
        file_extension = Path(data.name).suffix.lower()
        file_id = str(uuid.uuid4())
        safe_filename = f"{file_id}{file_extension}"
        file_path = os.path.join(tempfile.gettempdir(), safe_filename)
        
        # Garante que o caminho é seguro
        temp_dir = Path(tempfile.gettempdir()).resolve()
        file_path_resolved = Path(file_path).resolve()
        if not str(file_path_resolved).startswith(str(temp_dir)):
            raise ValueError("Caminho de arquivo inseguro")
        
        try:
            with open(file_path, "wb") as file:
                file.write(data.getbuffer())
            
            # Lê o arquivo com tratamento específico para versões do fiona
            try:
                if file_extension == ".kml":
                    # Para KML, força o driver específico
                    try:
                        import fiona
                        fiona.supported_drivers['KML'] = 'rw'
                    except:
                        pass
                    gdf = gpd.read_file(file_path, driver="KML")
                elif file_extension == ".zip":
                    # Shapefile compactado (.shp+.shx+.dbf+.prj dentro do .zip): lido
                    # direto de dentro do arquivo via VSI do GDAL (prefixo "zip://"),
                    # sem precisar extrair os componentes em disco antes.
                    gdf = gpd.read_file(f"zip://{file_path}")
                else:
                    # Para GeoJSON, lê normalmente
                    gdf = gpd.read_file(file_path)

            except Exception as read_error:
                if file_extension == ".zip":
                    # Um .zip que falha aqui não é um GeoJSON alternativo — não faz
                    # sentido tentar o fallback de JSON abaixo (o conteúdo é binário).
                    raise ValueError(
                        f"Não foi possível ler o shapefile enviado: {read_error}. "
                        "Confirme que o .zip contém .shp, .shx, .dbf (e .prj, se possível) "
                        "na raiz do arquivo."
                    ) from read_error

                # Fallback: tenta ler como JSON puro e converter
                logger.warning(f"Erro na leitura padrão: {read_error}. Tentando método alternativo...")

                with open(file_path, 'r', encoding='utf-8') as f:
                    geojson_data = json.load(f)
                
                # Converte JSON para GeoDataFrame manualmente
                import shapely.geometry as geom
                
                features = geojson_data.get('features', [])
                if not features:
                    raise ValueError("Nenhuma feature encontrada no GeoJSON")
                
                geometries = []
                properties_list = []
                
                for feature in features:
                    # Cria geometria usando shapely
                    geom_data = feature.get('geometry', {})
                    if geom_data.get('type') == 'Point':
                        coords = geom_data.get('coordinates', [])
                        if len(coords) >= 2:
                            geometry = geom.Point(coords[0], coords[1])
                            geometries.append(geometry)
                            properties_list.append(feature.get('properties', {}))
                
                if not geometries:
                    raise ValueError("Nenhuma geometria válida encontrada")
                
                # Cria GeoDataFrame manualmente
                gdf = gpd.GeoDataFrame(properties_list, geometry=geometries, crs='EPSG:4326')
            
            # Valida GeoDataFrame
            if gdf.empty:
                raise ValueError("Arquivo GeoJSON vazio")
            
            # Garante que tem CRS definido
            if gdf.crs is None:
                gdf = gdf.set_crs('EPSG:4326')
            
            logger.info(f"Arquivo processado com sucesso: {len(gdf)} geometrias")
            return gdf
            
        finally:
            # Remove arquivo temporário
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as cleanup_error:
                    logger.warning(f"Erro ao limpar arquivo temporário: {cleanup_error}")
    
    except Exception as e:
        logger.error(f"Erro ao processar arquivo: {e}")
        raise


WHOLE_RASTER_MAX_PIXELS = 50_000_000  # acima disso, reamostra por moda antes de reprojetar (cabe na memória do processo)


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


def extract_landscape_from_tif(
    uploaded_tif, point_lonlat=None, buffer_dist=None, on_progress=None,
    cleanup=True, temp_path_out=None,
):
    """
    Extrai as classes de cobertura do solo do GeoTIFF enviado pelo usuário —
    alternativa a extrair os mesmos dados via MapBiomas/Earth Engine (ver
    seção "Fonte dos dados" em app.py). Dois modos, conforme os argumentos:

    - `point_lonlat` e `buffer_dist` informados: recorta apenas a área do
      buffer (ponto + raio em metros) ao redor do ponto de interesse.
    - Nenhum dos dois informado: lê o raster inteiro, sem recorte — usado
      quando o usuário sobe só o GeoTIFF, sem enviar um ponto de interesse.

    Se o GeoTIFF estiver em CRS geográfico (graus), é reprojetado
    automaticamente antes da extração — nunca exige que o usuário reprojete
    manualmente fora do app:
    - Com ponto de interesse: recorta uma janela (com margem) ao redor do
      ponto ainda em graus (bem mais barato que reprojetar o raster inteiro)
      e reprojeta só essa janela para a zona UTM que contém o ponto.
    - Sem ponto (modo raster inteiro): reprojeta para SIRGAS 2000/Brazil
      Polyconic (EPSG:5880) — projeção pensada para minimizar distorção de
      área na extensão inteira do Brasil, mais adequada que uma única zona
      UTM para uma área potencialmente continental. Se o raster tiver mais
      de `WHOLE_RASTER_MAX_PIXELS`, é reamostrado por moda (nunca
      interpolado — dado é categórico) antes da reprojeção, para caber na
      memória do processo.

    Retorna `(array, resolution, reprojected_tif_bytes)` — o terceiro item é
    `None` se o raster já estava projetado (nada foi convertido) ou os bytes
    do GeoTIFF final (já recortado/reprojetado) para oferecer download ao
    usuário, caso tenha havido conversão automática.

    Por padrão (`cleanup=True`), o arquivo temporário em disco é sempre
    removido no `finally`, com sucesso ou falha — nunca fica retido além da
    própria chamada. No modo de múltiplos arquivos, o chamador passa
    `cleanup=False` para adiar a remoção até que TODOS os arquivos do lote
    tenham suas métricas calculadas (não só a extração) — nesse caso, o
    caminho do arquivo temporário é anexado à lista `temp_path_out` (se
    informada) para que o chamador possa limpá-lo depois.
    """
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

    try:
        # Escreve em blocos (em vez de um único write) para poder reportar
        # progresso real, proporcional aos bytes já gravados — relevante
        # para arquivos de até 5GB (MAX_TIF_SIZE).
        _report(0.0, "Salvando arquivo enviado...")
        raw_buffer = uploaded_tif.getbuffer()
        total_bytes = len(raw_buffer) or 1
        chunk_size = 8 * 1024 * 1024  # 8MB
        with open(file_path, "wb") as f:
            for offset in range(0, total_bytes, chunk_size):
                f.write(raw_buffer[offset:offset + chunk_size])
                written = min(offset + chunk_size, total_bytes)
                _report(0.5 * written / total_bytes, "Salvando arquivo enviado...")

        _report(0.55, "Abrindo raster e validando projeção...")
        reprojected = False
        with rasterio.open(file_path) as src:
            if src.crs is None:
                raise ValueError("O GeoTIFF não tem CRS (sistema de referência) definido.")

            src_nodata = src.nodata if src.nodata is not None else 0

            if src.crs.is_geographic:
                reprojected = True

                if point_lonlat is not None and buffer_dist is not None:
                    # Recorta uma janela generosa ao redor do ponto AINDA em
                    # graus — bem mais barato que reprojetar o raster
                    # inteiro para só depois recortar um pedaço pequeno.
                    _report(0.60, "CRS geográfico detectado — recortando janela ao redor do ponto...")
                    lon, lat = point_lonlat
                    margin_m = buffer_dist * 3 + 1000  # margem de segurança p/ a reprojeção não faltar pixel na borda
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
                else:
                    # Modo raster inteiro: reamostra por moda antes de
                    # reprojetar se for grande demais para caber na memória
                    # do processo (dado categórico — nunca interpolado).
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
                    resampling=Resampling.nearest,  # dado categórico — nunca interpolar valores de classe
                    src_nodata=src_nodata,
                    dst_nodata=0,
                )

                array = dst_array
                out_transform = dst_transform
                out_crs = dst_crs
                nodata_value = 0
                resolution = (abs(dst_transform.a), abs(dst_transform.e))

                if point_lonlat is not None and buffer_dist is not None:
                    _report(0.85, "Recortando a área do buffer (pós-reprojeção)...")
                    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
                    x, y = transformer.transform(lon, lat)
                    buffer_geom = Point(x, y).buffer(buffer_dist)
                    array, out_transform = _crop_and_mask_array(array, out_transform, buffer_geom, nodata_value)
            else:
                # Já em CRS projetado — comportamento original preservado.
                nodata_value = src_nodata
                out_crs = src.crs
                resolution = (abs(src.res[0]), abs(src.res[1]))

                if point_lonlat is not None and buffer_dist is not None:
                    transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
                    x, y = transformer.transform(point_lonlat[0], point_lonlat[1])
                    buffer_geom = Point(x, y).buffer(buffer_dist)

                    _report(0.8, "Recortando a área do buffer...")
                    try:
                        out_image, out_transform = rio_mask(src, [mapping(buffer_geom)], crop=True, nodata=nodata_value)
                    except ValueError as mask_error:
                        raise ValueError("A área do buffer não intersecta o raster enviado.") from mask_error
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
                   if point_lonlat is not None else
                   "— o arquivo parece conter apenas valores nodata.")
            )

        reprojected_tif_bytes = None
        if reprojected:
            _report(0.95, "Gerando arquivo reprojetado para download...")
            reprojected_tif_bytes = _array_to_geotiff_bytes(array, out_transform, out_crs, nodata_value)

        if cleanup:
            _report(0.98, "Descartando arquivo temporário...")
        return array, resolution, reprojected_tif_bytes
    finally:
        if cleanup and os.path.exists(file_path):
            try:
                os.remove(file_path)
                _report(1.0, "Arquivo temporário descartado")
            except Exception as cleanup_error:
                logger.warning(f"Erro ao limpar arquivo temporário: {cleanup_error}")


METRIC_CHART_COLOR = "#2a78d6"  # azul — paleta validada (skill de dataviz), série única por gráfico


def _render_metric_chart(values: "pd.Series", metric_label: str):
    """Gráfico de barras horizontal (Altair) do valor de uma métrica por
    classe de cobertura do solo — usado na revelação progressiva das
    métricas. Complementa a tabela (não a substitui — mantém uma visão
    tabular acessível ao lado do gráfico)."""
    df = values.reset_index()
    df.columns = ["Classe", "Valor"]
    df = df.sort_values("Valor", ascending=True)

    bars = alt.Chart(df).mark_bar(
        color=METRIC_CHART_COLOR,
        cornerRadiusTopRight=4,
        cornerRadiusBottomRight=4,
    ).encode(
        x=alt.X("Valor:Q", title=metric_label),
        y=alt.Y("Classe:N", sort="-x", title=None),
        tooltip=[
            alt.Tooltip("Classe:N", title="Classe"),
            alt.Tooltip("Valor:Q", title=metric_label, format=",.2f"),
        ],
    )
    labels = bars.mark_text(align="left", dx=4, color="#52514e", fontSize=14, fontWeight="bold").encode(
        text=alt.Text("Valor:Q", format=",.1f")
    )
    chart = (bars + labels).properties(height=max(35 * len(df), 80)).configure_axis(
        labelFontSize=13,
        titleFontSize=15,
        labelLimit=300
    )

    st.markdown(f"""
    **Análise Detalhada:**
    
    A métrica apresentada desempenha um papel fundamental na compreensão da estrutura espacial e da ecologia da paisagem analisada.
    Neste contexto, podemos observar a distribuição dos valores para cada classe de cobertura do solo mapeada na região de estudo.
    A análise cuidadosa destes padrões permite identificar quais classes dominam a paisagem em termos de área, fragmentação ou isolamento,
    dependendo da métrica específica sendo avaliada. Em estudos ecológicos, métricas de composição (como área e proporção)
    ajudam a entender a disponibilidade de habitat, enquanto métricas de configuração (como densidade de borda e isolamento)
    fornecem insights sobre a conectividade e os possíveis efeitos de borda sobre a biodiversidade local.
    É importante considerar o contexto histórico e as pressões antrópicas que podem ter moldado esta configuração atual da paisagem.
    Alterações contínuas, como desmatamento ou expansão urbana, frequentemente se refletem em mudanças abruptas nestas métricas espaciais,
    aumentando a fragmentação estrutural e reduzindo a viabilidade de populações de espécies especialistas.
    Portanto, os resultados quantitativos aqui apresentados servem como base sólida e metodológica para subsidiar estratégias de conservação,
    planejamento territorial e tomadas de decisão voltadas para a sustentabilidade e o manejo adequado dos recursos naturais na bacia ou região de interesse.
    """)

    st.altair_chart(chart, use_container_width=True)

    st.markdown(f"""
    **Considerações Finais sobre a Métrica:**
    
    Observando os resultados consolidados no gráfico acima, evidencia-se a heterogeneidade inerente à paisagem estudada.
    Cada barra representa o valor calculado para a respectiva classe, permitindo uma comparação visual direta de sua representatividade e estado estrutural.
    Classes com valores extremos frequentemente indicam elementos de destaque na paisagem, seja por sua dominância como matriz ou por sua alta vulnerabilidade devido à intensa fragmentação.
    A interpretação ecológica contínua desses dados sugere que a matriz da paisagem e seus respectivos fragmentos remanescentes estão em um estado dinâmico,
    potencialmente influenciado por regimes de perturbação naturais ou por crescentes intervenções humanas no uso do solo.
    Tais informações descritivas são indispensáveis para a construção de um diagnóstico ambiental preciso e fundamentado,
    que vá além da mera quantificação espacial e alcance a compreensão profunda dos processos ecológicos em curso.
    Recomenda-se que estes dados estruturais sejam cruzados com outras variáveis ambientais da região, como topografia, hidrografia e infraestrutura de transporte,
    para uma avaliação integrada e holística. Em síntese, a métrica espacial calculada reflete a complexidade do arranjo e da configuração espacial,
    sendo um indicativo claro de como a organização física do território pode limitar, dificultar ou favorecer a manutenção da biodiversidade
    e o provimento contínuo de serviços ecossistêmicos vitais para o bem-estar da sociedade e resiliência da região.
    """)


# Paleta categórica validada (skill de dataviz) — ordem fixa, usada para
# colorir classes de cobertura do solo nos gráficos de comparação entre
# múltiplos arquivos (uma classe = uma cor, consistente entre gráficos).
CATEGORICAL_PALETTE = [
    "#2a78d6", "#1baf7a", "#eda100", "#008300",
    "#4a3aa7", "#e34948", "#e87ba4", "#eb6834",
]

# Dicionário de legendas MapBiomas completo — ver limitação conhecida no
# comentário original em _compute_class_metrics: mapeamento fixo por posição
# de índice, construído a partir do esquema de classes da Collection
# (aprox. 9); classes não usadas nesse esquema ficam como ' '. Extraído como
# constante de módulo para ser reaproveitado tanto no caminho de uma única
# fonte quanto no loop de múltiplos GeoTIFFs.
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


# Métrica isoladamente responsável por ~97% do tempo de cálculo em testes
# (12,3s de 12,7s para um raster 3000x3000 com patches realistas — as outras
# 11 métricas juntas levam ~0,4s): calcula distância entre TODAS as manchas
# da mesma classe, custo que cresce rápido com o número de manchas. Usado
# para avisar o usuário nesse ponto específico em vez de deixá-lo "parado"
# numa % sem explicação.
SLOW_METRIC_NAME = "euclidean_nearest_neighbor_mn"


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

    `notify`, se informado, recebe mensagens de progresso (ex.: `st.write`)
    — opcional porque no loop de múltiplos arquivos essas mensagens por
    arquivo poluiriam a tela; no caminho de arquivo único elas continuam
    aparecendo em tempo real."""
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


def _compute_landscape_metrics(ls) -> dict:
    """Calcula métricas de nível de PAISAGEM (um único valor global, não
    por classe) — diversidade e agregação da paisagem como um todo,
    complementando as métricas por classe de `_compute_class_metrics`. Não
    levanta exceção: se o PyLandStats falhar num valor específico (raro,
    mas pode ocorrer com só 1 classe presente), essa entrada fica `None`
    em vez de derrubar o cálculo inteiro (as métricas de classe já
    calculadas continuam válidas mesmo assim)."""
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

    # SHEI/SIDI/SIEI/PR: sem método dedicado no PyLandStats 3.1.0 — fórmulas
    # padrão do FRAGSTATS a partir das proporções de área por classe.
    try:
        proportions = ls.compute_class_metrics_df(
            metrics=['proportion_of_landscape']
        )['proportion_of_landscape'] / 100
        richness = len(proportions)
        values['patch_richness'] = richness

        shdi = values.get('shannon_diversity_index')
        values['shannon_evenness_index'] = shdi / np.log(richness) if shdi is not None and richness > 1 else None

        sidi = 1 - float((proportions ** 2).sum())
        values['simpson_diversity_index'] = sidi
        values['simpson_evenness_index'] = sidi / (1 - 1 / richness) if richness > 1 else None
    except Exception as diversity_error:
        logger.warning(f"Erro ao calcular índices de diversidade manuais: {diversity_error}")

    return values


def _render_landscape_metrics(values: dict):
    """Stat tiles com as métricas de nível de paisagem — um valor único
    (não por classe), por isso não faz sentido como gráfico de barras por
    classe como `_render_metric_chart` (ver choosing-a-form.md da skill de
    dataviz: um único número por métrica é um stat tile, não um chart)."""
    calculated = sum(1 for name, *_ in LANDSCAPE_METRICS_INFO if values.get(name) is not None)
    st.markdown(
        f"<h5 style=' color: black; background-color:yellow; padding:5px; border-radius: 5px; box-shadow: 0 0 0.1em black'> 🌎 Métricas da paisagem (nível global) — {calculated}/{len(LANDSCAPE_METRICS_INFO)}:</h5>",
        unsafe_allow_html=True,
    )
    cols = st.columns(5)
    for i, (metric_name, icon, short_label, full_label) in enumerate(LANDSCAPE_METRICS_INFO):
        value = values.get(metric_name)
        display_value = f"{value:,.2f}" if isinstance(value, (int, float)) and value is not None else "—"
        with cols[i % 5]:
            st.metric(f"{icon} {short_label}", display_value, help=full_label)


def _extract_year_from_filename(filename: str):
    """Extrai um ano plausível (19xx/20xx) do nome do arquivo, para ordenar
    e rotular a comparação temporal entre múltiplos GeoTIFFs (ex.:
    'Corte_255_2010.tif' -> 2010). Usa o último padrão encontrado — em
    nomes com mais de um número de 4 dígitos nesse intervalo, assume-se que
    o ano vem por último (convenção comum: <área>_<ano>.tif). Retorna
    `None` se não encontrar nenhum, caso em que a comparação cai de volta
    para a ordem de upload."""
    matches = re.findall(r'(?:19|20)\d{2}', filename)
    return int(matches[-1]) if matches else None


def _compute_fingerprint(data_source, tif_bytes=None, point_lonlat=None,
                          buffer_dist=None, whole_raster=False) -> str:
    """Identifica de forma estável 'esta mesma submissão', para o cache de
    resultados em db.metric_results — uma resubmissão com a mesma
    fingerprint reaproveita o resultado já calculado em vez de refazer a
    extração (Earth Engine/GeoTIFF) e o PyLandStats.

    - GeoTIFF (com ou sem ponto): hash dos bytes do arquivo enviado — exato,
      reconhece o mesmo arquivo independente do nome. `whole_raster` entra
      na fingerprint para não colidir o mesmo arquivo submetido com ponto
      numa vez e sem ponto em outra (resultados diferentes).
    - MapBiomas (sem arquivo): hash do ponto (arredondado a 5 casas, ~1,1m —
      absorve o jitter de redesenhar o mesmo ponto no mapa) + buffer.

    Não considera qual collection do MapBiomas foi usada (auto-detectada e
    pode mudar com o tempo, ver app.py `collection_number`) — checar isso
    antes exigiria uma chamada ao Earth Engine, o que anularia o ganho de
    pular a extração num cache hit. O checkbox 'Forçar novo cálculo' cobre
    esse caso quando o usuário sabe que os dados de origem mudaram."""
    hasher = hashlib.sha256()
    hasher.update(data_source.encode("utf-8"))
    hasher.update(b"|whole" if whole_raster else b"|point")
    if tif_bytes is not None:
        hasher.update(b"|tif|")
        hasher.update(tif_bytes)
    if point_lonlat is not None:
        lon, lat = point_lonlat
        hasher.update(f"|point|{round(lon, 5)},{round(lat, 5)}".encode("utf-8"))
    if buffer_dist is not None:
        hasher.update(f"|buffer|{round(buffer_dist)}".encode("utf-8"))
    return hasher.hexdigest()


def _render_comparison_chart(file_results: list, metric_name: str, metric_label: str):
    """Gráfico de linha (matplotlib) comparando o valor de uma métrica
    entre múltiplos arquivos, uma linha por classe de cobertura do solo —
    eixo X é o ano (se todos os arquivos tiverem um ano identificável no
    nome) ou a ordem de upload, caso contrário. Limitado às classes mais
    relevantes (maior área média entre os arquivos) para não poluir o
    gráfico com dezenas de linhas."""
    all_classes = {}
    for result in file_results:
        df_sub = result["class_metrics_df_sub"]
        if metric_name not in df_sub.columns:
            continue
        for cls, value in df_sub[metric_name].items():
            all_classes.setdefault(cls, []).append(value)

    if not all_classes:
        return None

    top_classes = sorted(
        all_classes, key=lambda c: np.mean(all_classes[c]), reverse=True
    )[:len(CATEGORICAL_PALETTE)]

    x_labels = [r["label"] for r in file_results]

    fig, ax = plt.subplots(figsize=(7, 4))
    for i, cls in enumerate(top_classes):
        values = [
            r["class_metrics_df_sub"][metric_name].get(cls, np.nan)
            if metric_name in r["class_metrics_df_sub"].columns else np.nan
            for r in file_results
        ]
        ax.plot(
            x_labels, values, marker="o", linewidth=2,
            color=CATEGORICAL_PALETTE[i % len(CATEGORICAL_PALETTE)], label=cls,
        )

    ax.set_ylabel(metric_label)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#e1e0d9", linewidth=0.8)
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False)
    fig.tight_layout()
    return fig


def _build_html_report(file_results: list, buffer_dist, data_source: str) -> str:
    """Monta um relatório HTML autocontido (título, resumo por arquivo,
    gráficos comparativos como imagens embutidas em base64) para o usuário
    baixar, abrir no navegador e imprimir/salvar como PDF (Ctrl+P) — evita
    depender de uma biblioteca de geração de PDF nova no Docker."""
    def _fig_to_base64(fig):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    generated_at = pd.Timestamp.now().strftime("%d/%m/%Y %H:%M")
    parts = [f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<title>Relatório de Métricas de Paisagem</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #0b0b0b;
         max-width: 900px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.6rem; }}
  h2 {{ font-size: 1.2rem; border-bottom: 1px solid #e1e0d9; padding-bottom: 0.3rem; margin-top: 2.5rem; }}
  .meta {{ color: #52514e; font-size: 0.9rem; margin-bottom: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.8rem 0; }}
  th, td {{ border: 1px solid #e1e0d9; padding: 0.4rem 0.6rem; text-align: right; font-size: 0.85rem; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #f9f9f7; }}
  img {{ max-width: 100%; margin: 0.5rem 0 1.5rem; }}
  @media print {{ h2 {{ page-break-before: auto; }} }}
</style></head><body>
<h1>🏞️ Relatório de Métricas de Paisagem</h1>
<p class="meta">Gerado em {generated_at} • Fonte: {data_source} •
{'Buffer de ' + str(buffer_dist) + 'm ao redor do ponto selecionado' if buffer_dist else 'Área inteira de cada raster (sem ponto de interesse)'} •
{len(file_results)} arquivo(s) comparado(s)</p>
"""]

    parts.append("<h2>Resumo por arquivo</h2>")
    for result in file_results:
        label = result["label"] if result.get("year") is None else f"{result['label']} ({result['year']})"
        parts.append(f"<h3>{label}</h3>")
        parts.append("<p><strong>Métricas por classe</strong></p>")
        parts.append(result["class_metrics_df_sub"].round(2).to_html())
        if result.get("landscape_metrics"):
            parts.append("<p><strong>Métricas de nível de paisagem</strong></p>")
            landscape_df = pd.DataFrame(
                [
                    (short, result["landscape_metrics"].get(name))
                    for name, _icon, short, _full in LANDSCAPE_METRICS_INFO
                    if result["landscape_metrics"].get(name) is not None
                ],
                columns=["Métrica", "Valor"],
            ).round(3)
            parts.append(landscape_df.to_html(index=False))

    parts.append("<h2>Comparação entre arquivos</h2>")
    if len(file_results) > 1:
        for metric_name, _icon, metric_label in METRICS_INFO:
            fig = _render_comparison_chart(file_results, metric_name, metric_label)
            if fig is None:
                continue
            parts.append(f"<h3>{metric_label}</h3>")
            parts.append(f'<img src="data:image/png;base64,{_fig_to_base64(fig)}" alt="{metric_label}">')

    parts.append("</body></html>")
    return "".join(parts)


def _render_multi_file_results(file_results: list, buffer_dist, data_source: str):
    """Renderiza os resultados de múltiplos GeoTIFFs processados na mesma
    execução: um resumo compacto por arquivo (plot + tabela de métricas) e
    uma seção de comparação entre eles (um gráfico por métrica, uma linha
    por classe), além do botão de download do relatório HTML pronto para
    impressão/PDF (Ctrl+P no navegador)."""
    st.success(f"✅ {len(file_results)} arquivos processados com sucesso.")

    for idx, result in enumerate(file_results):
        label = result["label"] if result.get("year") is None else f"{result['label']} ({result['year']})"
        with st.expander(f"📄 {label}", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                try:
                    fig, ax = plt.subplots(figsize=(5, 3.5))
                    result["ls"].plot_landscape(legend=True, ax=ax)
                    st.pyplot(fig)
                    plt.close(fig)
                except Exception as plot_error:
                    logger.warning(f"Erro no plot ({label}): {plot_error}")
                    st.info("📊 Dados processados (visualização indisponível)")
            with col2:
                st.dataframe(result["class_metrics_df_sub"], use_container_width=True)

            if result.get("landscape_metrics"):
                _render_landscape_metrics(result["landscape_metrics"])

            if result.get("reprojected_tif_bytes") is not None:
                st.caption(
                    "🧭 Este raster estava em coordenadas geográficas (graus) e foi "
                    "reprojetado automaticamente para poder calcular as métricas."
                )
                st.download_button(
                    "📥 Download GeoTIFF reprojetado",
                    result["reprojected_tif_bytes"],
                    f"reprojetado_{idx}_{result['label']}",
                    "image/tiff",
                    key=f"download-tif-{idx}",
                    use_container_width=True,
                )

    st.markdown("---")
    st.markdown(
        "<h3 style='text-align: center;'>📊 Comparação entre arquivos</h3>",
        unsafe_allow_html=True,
    )
    for metric_name, icon, metric_label in METRICS_INFO:
        fig = _render_comparison_chart(file_results, metric_name, metric_label)
        if fig is None:
            continue
        with st.expander(f"{icon} {metric_label}", expanded=True):
            st.pyplot(fig)
            plt.close(fig)

    st.markdown("---")
    st.markdown(
        "<h3 style='text-align: center;'>📥 Relatório para impressão</h3>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Baixe um HTML autocontido com o resumo de cada arquivo e os gráficos "
        "comparativos — abra no navegador e use Ctrl+P para salvar como PDF."
    )
    html_report = _build_html_report(file_results, buffer_dist, data_source)
    st.download_button(
        "📥 Baixar relatório (HTML)",
        html_report.encode("utf-8"),
        f"relatorio_landscape_metrics_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.html",
        "text/html",
        key="download-html-report",
        use_container_width=True,
    )


def main() -> None:
    # Login e credenciais do usuário ANTES de qualquer outra operação
    db.init_db()

    if not auth.is_logged_in():
        auth.render_landing_page()
        st.stop()

    auth.render_user_badge()

    user_email = auth.get_current_user_email()
    credentials = db.get_credentials(user_email)

    if credentials is None:
        st.warning("⚠️ Você ainda não cadastrou suas credenciais do Google Earth Engine.")
        with st.form("gee_credentials_form"):
            st.markdown("Cole abaixo o JSON da sua conta de serviço do Google Earth Engine:")
            json_input = st.text_area("Credencial (JSON)", height=200)
            submitted = st.form_submit_button("Salvar credenciais")
        if submitted and save_gee_credentials_from_json(user_email, json_input):
            st.success("✅ Credenciais salvas!")
            st.rerun()
        st.stop()

    with st.expander("🔑 Atualizar credenciais do Earth Engine"):
        with st.form("gee_credentials_update_form"):
            st.markdown("Cole o novo JSON da sua conta de serviço para substituir a credencial atual:")
            new_json_input = st.text_area("Nova credencial (JSON)", height=200, key="update_creds_input")
            update_submitted = st.form_submit_button("Atualizar")
        if update_submitted and save_gee_credentials_from_json(user_email, new_json_input):
            st.success("✅ Credenciais atualizadas!")
            st.rerun()

    if not initialize_ee(credentials):
        st.stop()

    # Header principal
    col1, col2 = st.columns([2, 3])

    with col1:
        original_title = '<h1 style="color:Blue">🏞️ Landscape Metrics Extractor</h1>'
        st.markdown(original_title, unsafe_allow_html=True)
        st.caption(
            "Powered by MapBiomas, Pylandstats, Google Earth Engine and Geemap | Developed by Pedro Higuchi ([@pe_hi](https://twitter.com/pe_hi))"
        )
        st.caption("Contato: higuchip@gmail.com")

    with col2:
        st.markdown(
            "<h4 style=' color: black; background-color:lightgreen; padding:25px; border-radius: 25px; box-shadow: 0 0 0.1em black'>Aplicativo Web para extração de métricas de paisagem de pontos de interesse a partir da base de dados do MapBiomas</h4>",
            unsafe_allow_html=True,
        )

    # Sidebar com informações de segurança
    with st.sidebar:
        st.markdown("### 🔒 Informações")
        st.info(f"""
    📁 Ponto (GeoJSON/.zip) máx: {MAX_FILE_SIZE // (1024*1024)}MB
    📁 GeoTIFF máx: {MAX_TIF_SIZE // (1024*1024*1024)}GB
    📍 Apenas 1 ponto por vez
    🔧 Buffer: {MIN_BUFFER}-{MAX_BUFFER}m
    🛰️ MapBiomas (Earth Engine) ou seu próprio GeoTIFF
        """)
    
        # Status do Earth Engine
        if st.button("🔄 Status GEE"):
            try:
                ee.Number(1).getInfo()
                st.success("✅ GEE Conectado")
            except:
                st.error("❌ GEE Desconectado")


    # Seção 0: Histórico do usuário — resultados já calculados antes (ver
    # db.metric_results), reaproveitados pelo cache de _compute_fingerprint
    # sempre que o mesmo arquivo/ponto/buffer é resubmetido. Cada expander é
    # independente (Streamlit não permite expander dentro de expander), por
    # isso não há um expander "envelope" ao redor da lista inteira.
    st.markdown("### 📜 Suas análises anteriores")
    _history = db.list_metric_results(user_email)
    if not _history:
        st.caption("Nenhuma análise calculada ainda — os resultados aparecem aqui após o primeiro cálculo.")
    else:
        for _item in _history:
            _when = _item["created_at"][:16].replace("T", " ")
            _title = f"{_item['label']} · {_item['data_source']} · {_when}"
            with st.expander(_title, expanded=False):
                _full = db.get_metric_result(user_email, _item["fingerprint"], [])
                st.dataframe(_full["class_metrics_df_sub"], use_container_width=True)
                if _full["landscape_metrics"]:
                    _render_landscape_metrics(_full["landscape_metrics"])
                if st.button("🗑️ Remover este resultado", key=f"delete-history-{_item['fingerprint']}"):
                    db.delete_metric_result(user_email, _item["fingerprint"])
                    st.rerun()

    st.text(" ")
    st.markdown("---")

    # Seção 1: Seleção do ponto
    st.markdown(
        "<h3>1) Selecione um ponto de interesse 📌 </h3>",
        unsafe_allow_html=True,
    )

    st.warning(
        "⚠️ **Instruções:** Use apenas a ferramenta 'Draw a marker' para selecionar **UM** ponto, depois clique em 'Export'."
    )

    # Mapa para seleção de pontos
    try:
        Map = geemap.Map(
            center=[-15.7801, -47.9292], 
            zoom=5, 
            Draw_export=True,
            plugin_Draw=True,
            plugin_LatLngPopup=False
        )
        Map.add_basemap("HYBRID")

        # Container para o mapa
        map_container = st.container()
        with map_container:
            map_data = st_folium(Map, width=700, height=400, returned_objects=["last_clicked", "all_drawings"])

    except Exception as map_error:
        logger.error(f"Erro ao criar mapa: {map_error}")
        st.error("❌ Erro ao carregar o mapa. Verifique a conexão com o Earth Engine.")
    
        # Mapa alternativo simples
        st.info("🗺️ Carregando mapa alternativo...")
        try:
            import folium
            m = folium.Map(location=[-15.7801, -47.9292], zoom_start=5)
            folium.Marker([-15.7801, -47.9292], popup="Exemplo de localização").add_to(m)
            st_folium(m, width=700, height=400)
            st.warning("⚠️ Use o mapa acima como referência e carregue um arquivo GeoJSON manualmente.")
        except Exception as folium_error:
            logger.error(f"Erro no mapa alternativo: {folium_error}")
            st.error("❌ Não foi possível carregar nenhum mapa. Prossiga diretamente para o upload do arquivo GeoJSON.")

    st.markdown("---")

    # Seção 2: Upload do arquivo
    st.markdown(
        "<h3>2) Upload do ponto de interesse 📤</h3>",
        unsafe_allow_html=True,
    )

    data = st.file_uploader(
        "📁 Faça upload do GeoJSON exportado acima, ou de um shapefile do ponto compactado em .zip",
        type=["geojson", "zip"],
        help=(
            f"Limite: {MAX_FILE_SIZE // (1024*1024)}MB • GeoJSON (.geojson) ou shapefile "
            "compactado (.zip com .shp+.shx+.dbf+.prj) — em ambos os casos, com exatamente "
            "1 ponto"
        ),
    )

    st.markdown("---")

    # Seção 3: Fonte dos dados de cobertura do solo
    st.markdown(
        "<h3>3) Fonte dos dados de cobertura do solo 🛰️</h3>",
        unsafe_allow_html=True,
    )

    data_source = st.radio(
        "De onde vêm os dados de cobertura do solo?",
        ["MapBiomas (Google Earth Engine)", "Meu raster (GeoTIFF)"],
        horizontal=True,
    )

    tif_files = []
    if data_source == "Meu raster (GeoTIFF)":
        tif_files = st.file_uploader(
            "📁 Faça upload de um ou mais GeoTIFFs com os dados de cobertura do solo",
            type=["tif", "tiff"],
            accept_multiple_files=True,
            help=(
                f"Limite: {MAX_TIF_SIZE // (1024*1024)}MB por arquivo • CRS geográfico "
                "é reprojetado automaticamente • mesmos códigos de classe do MapBiomas • "
                "envie mais de um arquivo (ex.: anos diferentes da mesma área) para "
                "comparar lado a lado"
            ),
        ) or []
        if len(tif_files) > 1:
            st.caption(
                f"📚 {len(tif_files)} arquivos enviados — cada um será processado "
                "separadamente e comparado ao final (ano identificado pelo nome do "
                "arquivo, quando presente)."
            )
        elif data:
            st.caption(
                "O ponto e o buffer definidos abaixo recortam este raster — ele pode "
                "cobrir uma área bem maior que o buffer."
            )
        else:
            st.info(
                "📌 Nenhum ponto foi enviado na Seção 2 — as métricas serão calculadas "
                "para a área **inteira** deste raster, sem recorte por ponto/buffer."
            )

    force_recompute = st.checkbox(
        "🔄 Forçar novo cálculo (ignorar cache)",
        help=(
            "Por padrão, se o mesmo arquivo/ponto/buffer já foi calculado antes, o "
            "resultado salvo é reaproveitado em vez de refazer a extração/PyLandStats. "
            "Marque esta opção para recalcular do zero mesmo assim — útil se você sabe "
            "que os dados de origem (ex.: MapBiomas) foram atualizados."
        ),
    )

    st.markdown("---")

    # Modo raster inteiro: só faz sentido com raster próprio (o MapBiomas é
    # um asset nacional, sem um "raster inteiro" delimitado, então sempre
    # exige um ponto+buffer). Ativado quando o usuário sobe um GeoTIFF sem
    # também subir um ponto de interesse na Seção 2.
    own_raster_whole_mode = (
        data_source == "Meu raster (GeoTIFF)" and bool(tif_files) and not data
    )

    # Processamento principal
    ready_to_process = (
        (data_source == "MapBiomas (Google Earth Engine)" and data)
        or (data_source == "Meu raster (GeoTIFF)" and tif_files)
    )
    if ready_to_process:
        try:
            if own_raster_whole_mode:
                gdf_features = None
                buffer_dist = None
            else:
                # Seção 4: Configuração do buffer
                st.markdown(
                    "<h3>4) Defina o tamanho do raio (m) do buffer 🎯</h3>",
                    unsafe_allow_html=True,
                )

                buffer_dist = st.slider(
                    'Tamanho do raio (m) do buffer:',
                    MIN_BUFFER,
                    MAX_BUFFER,
                    5000,
                    step=500,
                    help="Área circular ao redor do ponto para análise das métricas de paisagem"
                )

                with st.spinner("📂 Processando arquivo GeoJSON..."):
                    gdf = uploaded_file_to_gdf(data)

                # Converte para formato Earth Engine com tratamento robusto
                try:
                    # Primeiro tenta o método padrão do geemap
                    gdf_json = gdf.to_json()
                    gdf_features = json.loads(gdf_json)["features"]

                except Exception as json_error:
                    logger.warning(f"Erro na conversão JSON padrão: {json_error}. Tentando método alternativo...")

                    # Método alternativo: converte manualmente
                    gdf_features = []
                    for idx, row in gdf.iterrows():
                        feature = {
                            "type": "Feature",
                            "geometry": json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]["geometry"],
                            "properties": {k: v for k, v in row.items() if k != 'geometry' and pd.notna(v)}
                        }
                        gdf_features.append(feature)

                # Valida que há apenas um ponto
                if len(gdf_features) > 1:
                    st.error("❌ Você selecionou mais de um ponto. Por favor, selecione apenas **UM** ponto de interesse.")
                    st.stop()
                elif len(gdf_features) == 0:
                    st.error("❌ Nenhum ponto encontrado no arquivo. Verifique o arquivo GeoJSON.")
                    st.stop()

            st.markdown("---")

            # Seção 5: Cálculo — disparado explicitamente pelo usuário (em vez de
            # rodar a cada rerun do Streamlit, o que recomputaria tudo a cada
            # interação, incluindo uploads grandes de GeoTIFF). O pipeline roda
            # dentro de um st.status para dar visibilidade em tempo real de cada
            # etapa; o resultado fica em st.session_state para sobreviver a
            # reruns causados por outros widgets (ex.: o botão de download).
            st.markdown(
                "<h3>5) Calcular métricas 🧮</h3>",
                unsafe_allow_html=True,
            )
            calculate_clicked = st.button(
                "🧮 Calcular métricas", type="primary", use_container_width=True
            )

            if calculate_clicked:
                st.session_state["metrics_ready"] = False
                pipeline_status = st.status(
                    "Processando análise de paisagem...", expanded=True
                )
                with pipeline_status:
                    # Barra de progresso geral do pipeline — cobre todas as etapas
                    # (área de interesse, extração de pixels, PyLandStats), não só a
                    # leitura do GeoTIFF, para que o usuário sempre veja em qual etapa
                    # o processamento está e quanto falta, independentemente da fonte
                    # de dados escolhida.
                    overall_progress = st.progress(0, text="Iniciando processamento... (0%)")

                    def _set_stage(fraction, label):
                        pct = int(round(min(max(fraction, 0.0), 1.0) * 100))
                        overall_progress.progress(min(max(fraction, 0.0), 1.0), text=f"{label} ({pct}%)")

                    try:
                        if own_raster_whole_mode:
                            roi = None
                            roi_buffer = None
                            _set_stage(0.20, "Modo raster inteiro — sem ponto/buffer")
                        else:
                            # Cria ROI e buffer com tratamento de erro robusto
                            _set_stage(0.10, "Preparando área de interesse (ponto + buffer)...")
                            st.write("🌍 Preparando área de interesse (ponto + buffer)...")
                            try:
                                # Cria FeatureCollection do Earth Engine
                                roi = ee.FeatureCollection(gdf_features)

                                # Debug: mostra informações sobre o ROI
                                logger.info(f"ROI criado com {len(gdf_features)} features")
                                st.write(f"📍 Processando ponto: {gdf_features[0]['geometry']['coordinates']}")

                                # Cria buffer
                                roi_buffer = roi.geometry().buffer(buffer_dist)

                                # Testa a geometria de forma mais simples
                                try:
                                    # Tenta obter informações básicas da geometria
                                    roi_bounds = roi.geometry().bounds().getInfo()
                                    logger.info(f"Bounds do ROI: {roi_bounds}")

                                    # Verifica se o buffer foi criado
                                    buffer_bounds = roi_buffer.bounds().getInfo()
                                    logger.info(f"Bounds do buffer: {buffer_bounds}")

                                except Exception as bounds_error:
                                    logger.warning(f"Não foi possível obter bounds: {bounds_error}")
                                    # Continua mesmo assim, pois o erro pode ser apenas na validação

                                st.write(f"✅ Área de interesse criada com buffer de {buffer_dist}m")

                            except Exception as roi_error:
                                logger.error(f"Erro ao criar ROI: {roi_error}")

                                # Tenta uma abordagem alternativa
                                st.write("⚠️ Tentando método alternativo para criar a área de interesse...")

                                try:
                                    # Cria geometria diretamente a partir das coordenadas
                                    coords = gdf_features[0]['geometry']['coordinates']
                                    point = ee.Geometry.Point(coords)
                                    roi_buffer = point.buffer(buffer_dist)
                                    roi = ee.FeatureCollection([ee.Feature(point)])

                                    st.write(f"✅ Área criada com método alternativo - buffer de {buffer_dist}m")

                                except Exception as alt_error:
                                    logger.error(f"Erro no método alternativo: {alt_error}")
                                    raise RuntimeError(
                                        f"Não foi possível processar o ponto. Coordenadas recebidas: "
                                        f"{gdf_features[0]['geometry']['coordinates']}"
                                    ) from alt_error

                            _set_stage(0.20, "Área de interesse pronta")

                        # Processamento dos dados de cobertura do solo (MapBiomas/GEE
                        # ou GeoTIFF enviado pelo usuário, conforme escolhido na Seção 3)
                        #
                        # Regra de negócio inegociável: se a extração de pixels reais
                        # falhar em qualquer estágio, o processamento PARA aqui e
                        # nenhuma métrica/CSV é gerada. Versões anteriores
                        # substituíam a falha por uma matriz de exemplo fixa de
                        # Santa Catarina e seguiam como se os dados fossem reais —
                        # isso foi removido por risco de o usuário usar uma análise
                        # fabricada como se fosse do ponto que selecionou.
                        resolution = (30, 30)
                        reprojected_tif_bytes = None  # só GeoTIFF próprio pode gerar isso (ver abaixo)

                        multi_file_mode = data_source == "Meu raster (GeoTIFF)" and len(tif_files) > 1

                        if multi_file_mode:
                            file_results = []
                            # Mantém os arquivos temporários de TODOS os GeoTIFFs do lote em
                            # disco até que as métricas de TODOS eles tenham sido calculadas
                            # (não só extraídas) — só então descarta, no `finally` abaixo,
                            # mesmo se algum arquivo do meio do lote falhar.
                            _temp_paths = []
                            try:
                                for _file_idx, _tif_item in enumerate(tif_files):
                                    _range_start = 0.25 + (_file_idx / len(tif_files)) * 0.5
                                    _range_end = 0.25 + ((_file_idx + 1) / len(tif_files)) * 0.5
                                    st.write(
                                        f"📂 Processando arquivo {_file_idx + 1}/{len(tif_files)}: "
                                        f"{_tif_item.name}..."
                                    )

                                    def _update_tif_progress(fraction, label, _start=_range_start, _end=_range_end,
                                                              _idx=_file_idx, _total=len(tif_files)):
                                        _set_stage(
                                            _start + (_end - _start) * min(max(fraction, 0.0), 1.0),
                                            f"[{_idx + 1}/{_total}] {label}",
                                        )

                                    _point_lonlat_i = (
                                        gdf_features[0]['geometry']['coordinates'] if gdf_features else None
                                    )
                                    _fingerprint_i = _compute_fingerprint(
                                        data_source, tif_bytes=_tif_item.getvalue(), point_lonlat=_point_lonlat_i,
                                        buffer_dist=buffer_dist, whole_raster=own_raster_whole_mode,
                                    )
                                    _required_metric_names = [name for name, *_ in METRICS_INFO]
                                    _cached_i = (
                                        None if force_recompute else
                                        db.get_metric_result(user_email, _fingerprint_i, _required_metric_names)
                                    )

                                    if _cached_i is not None:
                                        st.write(
                                            f"✅ '{_tif_item.name}': já calculado antes — reaproveitando o "
                                            "resultado do cache."
                                        )
                                        file_results.append({
                                            "label": _tif_item.name,
                                            "year": _extract_year_from_filename(_tif_item.name),
                                            "np_arr_mb": None,
                                            "ls": None,
                                            "class_metrics_df_sub": _cached_i["class_metrics_df_sub"],
                                            "landscape_metrics": _cached_i["landscape_metrics"],
                                            "reprojected_tif_bytes": None,
                                        })
                                        continue

                                    try:
                                        if own_raster_whole_mode:
                                            _arr, _res, _reproj_bytes = extract_landscape_from_tif(
                                                _tif_item, on_progress=_update_tif_progress,
                                                cleanup=False, temp_path_out=_temp_paths,
                                            )
                                        else:
                                            _arr, _res, _reproj_bytes = extract_landscape_from_tif(
                                                _tif_item, gdf_features[0]['geometry']['coordinates'], buffer_dist,
                                                on_progress=_update_tif_progress,
                                                cleanup=False, temp_path_out=_temp_paths,
                                            )
                                    except Exception as _tif_error:
                                        logger.error(f"Erro ao extrair dados de '{_tif_item.name}': {_tif_error}")
                                        raise RuntimeError(
                                            f"Não foi possível extrair dados reais do arquivo "
                                            f"'{_tif_item.name}'. Isso não gera uma análise substituta com "
                                            "dados de exemplo — a extração real é obrigatória para que as "
                                            f"métricas exibidas sejam confiáveis. Detalhes: {_tif_error}. "
                                            "Possíveis causas: buffer fora da área do raster, CRS incompatível, "
                                            "raster com apenas nodata, ou arquivo corrompido."
                                        ) from _tif_error

                                    st.write(
                                        f"📊 Calculando {len(METRICS_INFO)} métricas por classe + "
                                        f"{len(LANDSCAPE_METRICS_INFO)} de nível de paisagem para "
                                        f"'{_tif_item.name}'..."
                                    )
                                    _ls_i, _df_sub_i = _compute_class_metrics(_arr, _res, notify=st.write)
                                    _landscape_metrics_i = _compute_landscape_metrics(_ls_i)
                                    db.save_metric_result(
                                        user_email, _fingerprint_i, _tif_item.name, data_source,
                                        _point_lonlat_i, buffer_dist, _df_sub_i, _landscape_metrics_i,
                                    )
                                    file_results.append({
                                        "label": _tif_item.name,
                                        "year": _extract_year_from_filename(_tif_item.name),
                                        "np_arr_mb": _arr,
                                        "ls": _ls_i,
                                        "class_metrics_df_sub": _df_sub_i,
                                        "landscape_metrics": _landscape_metrics_i,
                                        "reprojected_tif_bytes": _reproj_bytes,
                                    })
                                    st.write(
                                        f"✅ {_tif_item.name}: {_arr.shape[0]}×{_arr.shape[1]} pixels, "
                                        f"{len(np.unique(_arr))} classe(s)"
                                    )
                            finally:
                                for _temp_path in _temp_paths:
                                    if os.path.exists(_temp_path):
                                        try:
                                            os.remove(_temp_path)
                                        except Exception as _cleanup_error:
                                            logger.warning(
                                                f"Erro ao limpar arquivo temporário {_temp_path}: {_cleanup_error}"
                                            )

                            # Ordena por ano se TODOS os arquivos tiverem um ano identificável no
                            # nome (ex.: Corte_255_2010.tif); caso contrário, mantém a ordem de upload.
                            if all(r["year"] is not None for r in file_results):
                                file_results.sort(key=lambda r: r["year"])

                            st.session_state["metrics_ready"] = True
                            st.session_state["multi_file_mode"] = True
                            st.session_state["file_results"] = file_results
                            st.session_state["roi"] = roi
                            st.session_state["roi_buffer"] = roi_buffer
                            st.session_state["buffer_dist_used"] = buffer_dist
                            st.session_state["data_source"] = data_source

                            _set_stage(1.0, "Processamento concluído")
                            pipeline_status.update(
                                label="✅ Processamento concluído", state="complete", expanded=True
                            )

                        if not multi_file_mode:
                            st.session_state["multi_file_mode"] = False
                            tif_file = tif_files[0] if tif_files else None
                            point_lonlat = (
                                gdf_features[0]['geometry']['coordinates'] if gdf_features else None
                            )
                            tif_bytes = tif_file.getvalue() if tif_file else None
                            fingerprint = _compute_fingerprint(
                                data_source, tif_bytes=tif_bytes, point_lonlat=point_lonlat,
                                buffer_dist=buffer_dist, whole_raster=own_raster_whole_mode,
                            )
                            required_metric_names = [name for name, *_ in METRICS_INFO]
                            cached_result = (
                                None if force_recompute else
                                db.get_metric_result(user_email, fingerprint, required_metric_names)
                            )

                            if cached_result is not None:
                                _set_stage(0.85, "Resultado encontrado em cache")
                                st.write(
                                    "✅ Esta mesma análise já havia sido calculada antes — "
                                    "reaproveitando o resultado salvo, sem refazer a extração/PyLandStats."
                                )
                                np_arr_mb = None
                                ls = None
                                class_metrics_df_sub = cached_result["class_metrics_df_sub"]
                                landscape_metrics = cached_result["landscape_metrics"]
                            else:
                                if data_source == "MapBiomas (Google Earth Engine)":
                                    _set_stage(0.30, "Conectando ao MapBiomas...")
                                    st.write("🛰️ Conectando ao MapBiomas...")
                                    try:
                                        # Assets oficiais do MapBiomas Collection 9
                                        mapbiomas_assets = [
                                            "projects/mapbiomas-public/assets/brazil/lulc/collection9/mapbiomas_collection90_integration_v1",
                                            "projects/mapbiomas-public/assets/brazil/lulc/collection8/mapbiomas_collection80_integration_v1",
                                            "projects/mapbiomas-workspace/public/collection7/mapbiomas_collection70_integration_v2",
                                            "projects/mapbiomas-workspace/public/collection6/mapbiomas_collection60_integration_v1"
                                        ]

                                        mb = None
                                        collection_number = None

                                        # Lista em ordem de preferência (mais recente primeiro): tenta a
                                        # Collection 9 e recua para versões mais antigas se o asset não
                                        # existir ou estiver indisponível no momento. Isso decide qual
                                        # ano/legenda de classes será usado adiante — collections
                                        # diferentes do MapBiomas podem ter esquemas de classificação
                                        # distintos, então o `legend_dict` hardcoded mais abaixo é
                                        # otimista em assumir que serve para qualquer uma delas.
                                        for asset in mapbiomas_assets:
                                            try:
                                                st.write(f"🔍 Testando {asset.split('/')[-1]}...")
                                                test_image = ee.Image(asset)
                                                bands = test_image.bandNames().getInfo()

                                                if bands and len(bands) > 0:
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

                                            except Exception as asset_error:
                                                logger.warning(f"Asset {asset} falhou: {asset_error}")
                                                continue

                                        if mb is None:
                                            raise ValueError("Nenhum asset MapBiomas disponível")

                                        _set_stage(0.45, f"Conectado ao MapBiomas Collection {collection_number}")
                                        st.write(f"🗺️ Conectado ao MapBiomas Collection {collection_number}")

                                        # Seleciona ano mais recente
                                        bands = mb.bandNames().getInfo()
                                        available_years = []
                                        for band in bands:
                                            if 'classification_' in band:
                                                year = band.replace('classification_', '')
                                                if year.isdigit():
                                                    available_years.append(int(year))

                                        latest_year = max(available_years) if available_years else (2023 if collection_number >= 9 else 2022)
                                        classification_band = f'classification_{latest_year}'

                                        st.write(f"📅 Usando dados do ano: {latest_year}")

                                        mb_year = mb.select(classification_band)

                                        # Mínimo de pixels reais exigido para montar uma matriz 3x3 —
                                        # abaixo disso não há dado suficiente para métricas confiáveis
                                        # e o processamento deve falhar de forma explícita (ver bloco
                                        # de exceção mais abaixo), nunca ser completado com valores
                                        # inventados.
                                        MIN_VALID_PIXELS = 9

                                        # Extração de dados: tenta sampleRectangle e, se falhar ou
                                        # vier vazio, recua para reduceRegion. Qualquer falha nos dois
                                        # métodos propaga para o "except Exception as mb_error" logo
                                        # abaixo, que interrompe o processamento — não há mais um
                                        # terceiro nível de fallback com dados fabricados.
                                        try:
                                            _set_stage(0.55, "Extraindo pixels do MapBiomas...")
                                            st.write("📊 Extraindo dados via sampleRectangle...")
                                            sample_result = mb_year.sampleRectangle(
                                                region=roi_buffer,
                                                defaultValue=0
                                            )
                                            array_data = sample_result.get(classification_band).getInfo()
                                            np_arr_mb = np.array(array_data)

                                            if np_arr_mb.size > 0 and not np.all(np_arr_mb == 0):
                                                st.write("✅ Dados extraídos com sucesso via sampleRectangle")
                                            else:
                                                raise ValueError("Dados insuficientes via sampleRectangle")

                                        except Exception as sample_error:
                                            logger.warning(f"sampleRectangle falhou: {sample_error}")
                                            st.write("🔄 Usando método alternativo (reduceRegion)...")

                                            reduction = mb_year.reduceRegion(
                                                reducer=ee.Reducer.toList(),
                                                geometry=roi_buffer,
                                                scale=30,
                                                maxPixels=1e8,
                                                bestEffort=True
                                            )

                                            values_list = reduction.get(classification_band).getInfo()

                                            # Filtra pixels reais (0 = sem observação no MapBiomas)
                                            valid_values = [int(v) for v in (values_list or []) if v is not None and v != 0]

                                            if len(valid_values) < MIN_VALID_PIXELS:
                                                raise ValueError(
                                                    f"Apenas {len(valid_values)} pixel(is) válido(s) na área selecionada "
                                                    f"(mínimo necessário: {MIN_VALID_PIXELS}). Aumente o buffer ou "
                                                    "escolha outro ponto."
                                                )

                                            # Trunca para o maior quadrado perfeito que cabe nos
                                            # pixels válidos disponíveis — nunca preenche com valores
                                            # repetidos ou inventados.
                                            side = int(np.sqrt(len(valid_values)))
                                            total_needed = side * side
                                            valid_values = valid_values[:total_needed]

                                            np_arr_mb = np.array(valid_values).reshape(side, side)
                                            st.write(f"✅ Dados extraídos: {len(valid_values)} pixels válidos")

                                        # Verifica dados finais
                                        unique_values = np.unique(np_arr_mb)
                                        st.write(f"✅ Dados processados: {np_arr_mb.shape[0]}×{np_arr_mb.shape[1]} pixels")
                                        st.write(f"📊 Classes encontradas: {len(unique_values)} → {unique_values}")
                                        _set_stage(0.75, "Dados do MapBiomas extraídos com sucesso")

                                    except Exception as mb_error:
                                        logger.error(f"Erro MapBiomas: {mb_error}")
                                        raise RuntimeError(
                                            "Não foi possível extrair dados reais do MapBiomas para esta área. "
                                            "Isso não gera uma análise substituta com dados de exemplo — a "
                                            "extração real é obrigatória para que as métricas exibidas sejam "
                                            f"confiáveis. Detalhes: {mb_error}. Possíveis causas: buffer muito "
                                            "pequeno, região sem cobertura no asset MapBiomas, ou instabilidade "
                                            "temporária do Earth Engine. Tente novamente, aumente o raio do "
                                            "buffer ou selecione outro ponto."
                                        ) from mb_error
                                else:
                                    tif_stage_label = (
                                        "Lendo o GeoTIFF enviado por completo (raster inteiro)..."
                                        if own_raster_whole_mode else
                                        "Recortando o GeoTIFF enviado..."
                                    )
                                    _set_stage(0.25, tif_stage_label)
                                    st.write(f"📂 {tif_stage_label}")

                                    # Repassa o progresso interno (0.0-1.0) de extract_landscape_from_tif
                                    # para a faixa 25%-75% da barra geral — o mesmo estágio "extração de
                                    # dados" que o caminho MapBiomas ocupa acima, só que com granularidade
                                    # real (bytes gravados/lidos) em vez de marcos fixos.
                                    def _update_tif_progress(fraction, label):
                                        _set_stage(0.25 + 0.5 * min(max(fraction, 0.0), 1.0), label)

                                    try:
                                        if own_raster_whole_mode:
                                            np_arr_mb, resolution, reprojected_tif_bytes = extract_landscape_from_tif(
                                                tif_file, on_progress=_update_tif_progress,
                                            )
                                        else:
                                            np_arr_mb, resolution, reprojected_tif_bytes = extract_landscape_from_tif(
                                                tif_file, gdf_features[0]['geometry']['coordinates'], buffer_dist,
                                                on_progress=_update_tif_progress,
                                            )
                                        unique_values = np.unique(np_arr_mb)
                                        st.write(f"✅ Dados processados: {np_arr_mb.shape[0]}×{np_arr_mb.shape[1]} pixels")
                                        st.write(f"📊 Classes encontradas: {len(unique_values)} → {unique_values}")
                                        st.write("🗑️ Arquivo GeoTIFF temporário descartado do servidor após a leitura.")
                                        if reprojected_tif_bytes is not None:
                                            st.write(
                                                "🧭 O raster enviado estava em coordenadas geográficas (graus) — "
                                                "reprojetado automaticamente antes da extração (disponível para "
                                                "download na seção de resultados abaixo)."
                                            )
                                        _set_stage(0.75, "Dados do GeoTIFF extraídos com sucesso")

                                    except Exception as tif_error:
                                        logger.error(f"Erro ao extrair dados do GeoTIFF: {tif_error}")
                                        extra_causes = (
                                            "raster contém apenas nodata, ou arquivo corrompido."
                                            if own_raster_whole_mode else
                                            "buffer fora da área do raster, CRS do raster não é projetado "
                                            "(metros), ou o raster não cobre essa região. Aumente o buffer, "
                                            "selecione outro ponto ou confira o arquivo enviado."
                                        )
                                        raise RuntimeError(
                                            "Não foi possível extrair dados reais do GeoTIFF enviado. Isso não "
                                            "gera uma análise substituta com dados de exemplo — a extração real "
                                            "é obrigatória para que as métricas exibidas sejam confiáveis. "
                                            f"Detalhes: {tif_error}. Possíveis causas: {extra_causes}"
                                        ) from tif_error

                                # Instancia PyLandStats e calcula as métricas de classe (lógica
                                # compartilhada com o loop de múltiplos arquivos acima). Progresso
                                # real por métrica (não marcos fixos) — uma delas
                                # (SLOW_METRIC_NAME) domina o tempo total, então sem isso a barra
                                # ficava "parada" numa % sem indicar que ainda estava trabalhando.
                                _set_stage(0.85, "Calculando métricas da paisagem (PyLandStats)...")
                                st.write(
                                    f"📊 Calculando {len(METRICS_INFO)} métricas por classe + "
                                    f"{len(LANDSCAPE_METRICS_INFO)} métricas de nível de paisagem "
                                    f"({len(METRICS_INFO) + len(LANDSCAPE_METRICS_INFO)} no total)..."
                                )

                                def _on_metric_progress(i, total, label):
                                    _set_stage(0.85 + 0.10 * (i / total), f"Calculando ({i + 1}/{total}): {label}")

                                ls, class_metrics_df_sub = _compute_class_metrics(
                                    np_arr_mb, resolution, notify=st.write,
                                    on_metric_progress=_on_metric_progress,
                                )

                                # Revela cada métrica progressivamente (uma de cada vez, com uma
                                # pequena pausa) em vez de só um "calculando..." seguido da tabela
                                # inteira de uma vez — deixa o acompanhamento mais didático,
                                # mostrando o que cada métrica representa conforme ela aparece.
                                metrics_to_reveal = [
                                    (name, icon, label) for name, icon, label in METRICS_INFO
                                    if name in class_metrics_df_sub.columns
                                ]
                                st.write(f"✨ Revelando as {len(metrics_to_reveal)} métricas por classe calculadas...")
                                for i, (metric_name, icon, label) in enumerate(metrics_to_reveal):
                                    _set_stage(
                                        0.95 + 0.04 * ((i + 1) / len(metrics_to_reveal)),
                                        f"Revelando ({i + 1}/{len(metrics_to_reveal)}): {label}",
                                    )
                                    with st.expander(f"{icon} {label}", expanded=True):
                                        _render_metric_chart(class_metrics_df_sub[metric_name], label)
                                        # Tabela sempre visível ao lado do gráfico (não aninhada em outro
                                        # expander — Streamlit não permite expander dentro de expander) —
                                        # mantém uma visão tabular acessível com os valores exatos.
                                        st.dataframe(
                                            class_metrics_df_sub[[metric_name]],
                                            use_container_width=True,
                                        )
                                    time.sleep(0.25)

                                st.write(
                                    f"🌎 Calculando as {len(LANDSCAPE_METRICS_INFO)} métricas de nível de "
                                    "paisagem (diversidade/agregação)..."
                                )
                                landscape_metrics = _compute_landscape_metrics(ls)

                                db.save_metric_result(
                                    user_email, fingerprint,
                                    tif_file.name if tif_file else "MapBiomas (Google Earth Engine)",
                                    data_source, point_lonlat, buffer_dist,
                                    class_metrics_df_sub, landscape_metrics,
                                )

                            # Persiste tudo que a renderização abaixo precisa, para
                            # sobreviver a reruns causados por outros widgets (ex.: o
                            # botão de download do CSV) sem precisar refazer chamadas
                            # ao Earth Engine/GeoTIFF.
                            st.session_state["metrics_ready"] = True
                            st.session_state["roi"] = roi
                            st.session_state["roi_buffer"] = roi_buffer
                            st.session_state["buffer_dist_used"] = buffer_dist
                            st.session_state["np_arr_mb"] = np_arr_mb
                            st.session_state["ls"] = ls
                            st.session_state["class_metrics_df_sub"] = class_metrics_df_sub
                            st.session_state["landscape_metrics"] = landscape_metrics
                            st.session_state["reprojected_tif_bytes"] = reprojected_tif_bytes
                            st.session_state["data_source"] = data_source

                            _set_stage(1.0, "Processamento concluído")
                            pipeline_status.update(
                                label="✅ Processamento concluído", state="complete", expanded=True
                            )

                    except Exception as pipeline_error:
                        logger.error(f"Erro no pipeline de processamento: {pipeline_error}")
                        st.error(
                            "❌ Não foi possível concluir a análise com dados reais. Isso não gera "
                            "uma análise substituta com dados de exemplo — nenhuma métrica é "
                            "exibida sem dados reais por trás."
                        )
                        with st.expander("🔍 Detalhes do erro"):
                            st.error(str(pipeline_error))
                        st.stop()

            if st.session_state.get("metrics_ready"):
                if not st.session_state.get("multi_file_mode"):
                    roi = st.session_state["roi"]
                    roi_buffer = st.session_state["roi_buffer"]
                    np_arr_mb = st.session_state["np_arr_mb"]
                    ls = st.session_state["ls"]
                    class_metrics_df_sub = st.session_state["class_metrics_df_sub"]
                    landscape_metrics = st.session_state.get("landscape_metrics", {})
                    reprojected_tif_bytes = st.session_state.get("reprojected_tif_bytes")

                    def _render_landscape_plot():
                        st.markdown(
                            "<h5 style=' color: black; background-color:yellow; padding:5px; border-radius: 5px; box-shadow: 0 0 0.1em black'> 🗺️ Classes de cobertura do solo:</h5>",
                            unsafe_allow_html=True
                        )

                        if ls is None:
                            # Resultado veio do cache (ver _compute_fingerprint/db.get_metric_result)
                            # — só os valores das métricas são persistidos, não o array de pixels
                            # nem o objeto pls.Landscape, então não há como replotar o mapa de classes.
                            st.info(
                                "📊 Resultado reaproveitado do cache — o gráfico de classes só fica "
                                "disponível ao recalcular (use 'Forçar novo cálculo' acima)."
                            )
                            return

                        # Plota paisagem com tratamento de erro
                        try:
                            fig, ax = plt.subplots(figsize=(6, 4))
                            ls.plot_landscape(legend=True, ax=ax)
                            st.pyplot(fig)
                            plt.close()
                        except Exception as plot_error:
                            logger.warning(f"Erro no plot: {plot_error}")
                            st.info("📊 Dados processados (visualização indisponível)")

                            # Mostra informações básicas sobre as classes
                            unique_classes = np.unique(np_arr_mb)
                            st.write(f"Classes encontradas: {unique_classes}")

                    if roi is None:
                        # Modo raster inteiro: não há ponto/buffer para exibir num mapa.
                        _render_landscape_plot()
                    else:
                        # Layout em duas colunas para visualização
                        col1, col2 = st.columns(2)

                        with col1:
                            st.markdown(
                                "<h5 style=' color: black; background-color:yellow; padding:5px; border-radius: 5px; box-shadow: 0 0 0.1em black'> 📍 Área de interesse:</h5>",
                                unsafe_allow_html=True
                            )

                            # Mapa da área de interesse
                            try:
                                roi_map = geemap.Map()
                                roi_map.add_basemap("HYBRID")
                                roi_map.centerObject(roi, zoom=11)
                                roi_map.addLayer(roi_buffer, {}, "ROI Buffer")

                                st_folium(roi_map, width=400, height=300)

                            except Exception as roi_map_error:
                                logger.warning(f"Erro ao criar mapa ROI: {roi_map_error}")
                                st.info("📍 Área de interesse processada (mapa indisponível)")
                                st.text(f"Buffer de {st.session_state['buffer_dist_used']}m aplicado ao ponto selecionado")

                        with col2:
                            _render_landscape_plot()

                    st.markdown("---")

                    # Cálculo das métricas
                    st.markdown(
                        "<h5 style=' color: black; background-color:yellow; padding:5px; border-radius: 5px; box-shadow: 0 0 0.1em black'> 📈 Métricas da paisagem:</h5>",
                        unsafe_allow_html=True
                    )
                    st.info(
                        f"📊 **{len(class_metrics_df_sub.columns)} métricas por classe**, "
                        f"{len(class_metrics_df_sub)} classe(s) com mais de 10% de proporção "
                        "na paisagem:"
                    )
                    st.dataframe(class_metrics_df_sub, use_container_width=True)

                    st.markdown("---")
                    _render_landscape_metrics(landscape_metrics)

                    # Download dos resultados
                    st.markdown("---")
                    download_container = st.container()
                    with download_container:
                        col1, col2, col3 = st.columns([1, 2, 1])
                        with col2:
                            st.markdown(
                                "<h3 style='text-align: center;'> 📥 Download dos resultados</h3>",
                                unsafe_allow_html=True,
                            )

                            @st.cache_data
                            def convert_df(df):
                                return df.to_csv(sep=";", decimal=",").encode("utf-8")

                            csv = convert_df(class_metrics_df_sub)

                            # Nome de arquivo com timestamp
                            safe_filename = f"landscape_metrics_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"

                            st.download_button(
                                "📥 Download CSV",
                                csv,
                                safe_filename,
                                "text/csv",
                                key="download-csv",
                                use_container_width=True
                            )

                            if landscape_metrics:
                                landscape_csv = convert_df(
                                    pd.DataFrame(
                                        [
                                            (short, landscape_metrics.get(name))
                                            for name, _icon, short, _full in LANDSCAPE_METRICS_INFO
                                            if landscape_metrics.get(name) is not None
                                        ],
                                        columns=["Métrica", "Valor"],
                                    ).set_index("Métrica")
                                )
                                safe_landscape_filename = (
                                    f"landscape_level_metrics_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
                                )
                                st.download_button(
                                    "📥 Download CSV (métricas de paisagem)",
                                    landscape_csv,
                                    safe_landscape_filename,
                                    "text/csv",
                                    key="download-landscape-csv",
                                    use_container_width=True,
                                )

                            if reprojected_tif_bytes is not None:
                                st.caption(
                                    "🧭 O GeoTIFF enviado estava em coordenadas geográficas (graus) e foi "
                                    "reprojetado automaticamente para poder calcular as métricas."
                                )
                                safe_tif_filename = f"raster_reprojetado_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.tif"
                                st.download_button(
                                    "📥 Download GeoTIFF reprojetado",
                                    reprojected_tif_bytes,
                                    safe_tif_filename,
                                    "image/tiff",
                                    key="download-reprojected-tif",
                                    use_container_width=True,
                                )

                    logger.info(
                        f"Métricas da paisagem calculadas com sucesso para buffer de "
                        f"{st.session_state['buffer_dist_used']}m"
                    )
                else:
                    _render_multi_file_results(
                        st.session_state["file_results"],
                        st.session_state.get("buffer_dist_used"),
                        st.session_state.get("data_source", ""),
                    )

        except Exception as e:
            logger.error(f"Erro no processamento principal: {e}")
            st.error("❌ Erro no processamento dos dados")
            with st.expander("🔍 Detalhes do erro"):
                st.error(str(e))

    # Informações adicionais
    st.markdown("---")

    # Detalhamento das métricas em expander
    with st.expander("📊 **Detalhamento das métricas** (clique para expandir)", expanded=False):
        st.markdown(
            "Para maiores informações, acessar o site do [PyLandStats](https://pylandstats.readthedocs.io/en/latest/)."
        )

        st.markdown("**Métricas por classe** (uma linha por classe de cobertura do solo):")
        class_detalhamento_df = pd.DataFrame(
            [(f"{icon} {label}") for _name, icon, label in METRICS_INFO],
            columns=['Métrica'],
        )
        st.table(class_detalhamento_df)

        st.markdown("**Métricas de nível de paisagem** (um único valor para a paisagem inteira):")
        landscape_detalhamento_df = pd.DataFrame(
            [(f"{icon} {short}", full) for _name, icon, short, full in LANDSCAPE_METRICS_INFO],
            columns=['Sigla', 'Descrição'],
        )
        st.table(landscape_detalhamento_df.set_index('Sigla'))

        st.caption(
            "Não incluídas por ora: Aggregation Index (AI), Clumpiness Index (CLUMPY), "
            "Landscape Division Index (DIVISION) e Splitting Index (SPLIT) — sem método "
            "equivalente na versão do PyLandStats usada neste projeto. Interspersion & "
            "Juxtaposition Index (IJI), Proximity Index e Contiguity Index existem na "
            "biblioteca mas não estão implementados nela (retornam erro ao chamar). "
            "Métricas de Contraste (ex.: TECI) exigiriam uma matriz de similaridade entre "
            "classes configurada pelo usuário, não suportada pela interface atual."
        )

    # Referências em footer
    st.markdown("---")
    st.subheader("📚 Referências:")

    references = [
        "**Bosch M.** (2019). PyLandStats: An open-source Pythonic library to compute landscape metrics. *PLOS ONE*, 14(12), 1-19. doi.org/10.1371/journal.pone.0225734",
    
        "**Souza et al.** (2020). Reconstructing Three Decades of Land Use and Land Cover Changes in Brazilian Biomes with Landsat Archive and Earth Engine. *Remote Sensing*, Volume 12, Issue 17, 10.3390/rs12172735.",
    
        "**Wu, Q.** (2020). geemap: A Python package for interactive mapping with Google Earth Engine. *The Journal of Open Source Software*, 5(51), 2305. https://doi.org/10.21105/joss.02305",
    
        "**Wu, Q. et al.** (2019). Integrating LiDAR data and multi-temporal aerial imagery to map wetland inundation dynamics using Google Earth Engine. *Remote Sensing of Environment*, 228, 1-13.",
    
        "**Projeto MapBiomas** - Iniciativa multi-institucional para gerar mapas anuais de uso e cobertura da terra. Descrição completa em http://mapbiomas.org"
    ]

    for ref in references:
        st.markdown(f"• {ref}")

    st.markdown("---")


if __name__ == "__main__":
    main()
