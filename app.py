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
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as shapely_transform
import requests
from scipy.linalg import fractional_matrix_power
from scipy.ndimage import zoom as ndimage_zoom
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


IBGE_LOCALIDADES_BASE = "https://servicodados.ibge.gov.br/api/v1/localidades"
IBGE_MALHAS_BASE = "https://servicodados.ibge.gov.br/api/v3/malhas"
IBGE_AGREGADOS_BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"
IBGE_REQUEST_TIMEOUT = 15  # segundos — evita travar a UI indefinidamente se a API do IBGE ficar lenta/indisponível


@st.cache_data(ttl=24 * 3600)
def _ibge_get_ufs() -> list[dict]:
    """Lista as 27 UFs (nome + sigla) para popular o seletor de estado do
    modo 'Limite municipal (IBGE)'. Cache de 24h — a lista de UFs não muda
    na prática, então não vale a pena rebuscar a cada sessão."""
    resp = requests.get(
        f"{IBGE_LOCALIDADES_BASE}/estados", params={"orderBy": "nome"},
        timeout=IBGE_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=24 * 3600)
def _ibge_get_municipios(uf_sigla: str) -> list[dict]:
    """Lista os municípios de uma UF (nome + código IBGE de 7 dígitos) para
    popular o segundo seletor do modo município, depois que o usuário
    escolhe a UF no primeiro."""
    resp = requests.get(
        f"{IBGE_LOCALIDADES_BASE}/estados/{uf_sigla}/municipios",
        timeout=IBGE_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=24 * 3600)
def _ibge_get_municipio_geojson(codigo: str) -> dict | None:
    """Busca o polígono (GeoJSON, EPSG:4326) do limite do município na malha
    territorial do IBGE — usado como área de interesse alternativa ao
    ponto+buffer. `qualidade=minima` mantém o payload pequeno (suficiente
    para recorte de raster/consulta ao Earth Engine, não para cartografia de
    precisão).

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


@st.cache_data(ttl=24 * 3600)
def _ibge_get_populacao_estimada(codigo: str) -> int | None:
    """Melhor esforço: população estimada mais recente (agregado SIDRA 6579,
    variável 9324) para o município — enriquecimento opcional da matriz
    socioecológica (ver `_build_sse_matrix`), nunca bloqueia o resto do
    fluxo. Retorna `None` silenciosamente em qualquer falha (rede, formato
    inesperado da resposta, município sem estimativa publicada)."""
    try:
        resp = requests.get(
            f"{IBGE_AGREGADOS_BASE}/6579/periodos/-1/variaveis/9324",
            params={"localidades": f"N6[{codigo}]"},
            timeout=IBGE_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        valor = data[0]["resultados"][0]["series"][0]["serie"]
        (populacao_str,) = valor.values()
        return int(populacao_str)
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as pop_error:
        logger.warning(f"Falha ao buscar população estimada do IBGE (código {codigo}): {pop_error}")
        return None


def _municipio_geometry_shapely(municipio_geojson: dict):
    """Extrai a geometria (Shapely, EPSG:4326) da(s) feature(s) retornada(s)
    pela malha do IBGE — normalmente uma única feature por município, mas
    combina via `unary_union` se vier mais de uma (defensivo)."""
    from shapely.ops import unary_union

    geoms = [shape(feat["geometry"]) for feat in municipio_geojson["features"]]
    return geoms[0] if len(geoms) == 1 else unary_union(geoms)


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
    cleanup=True, temp_path_out=None, region_geojson=None,
):
    """
    Extrai as classes de cobertura do solo do GeoTIFF enviado pelo usuário —
    alternativa a extrair os mesmos dados via MapBiomas/Earth Engine (ver
    seção "Fonte dos dados" em app.py). Três modos, conforme os argumentos:

    - `point_lonlat` e `buffer_dist` informados: recorta apenas a área do
      buffer (ponto + raio em metros) ao redor do ponto de interesse.
    - `region_geojson` informado (GeoJSON EPSG:4326, ver
      `_ibge_get_municipio_geojson`): recorta pela geometria exata (ex.:
      limite municipal), em vez de um buffer circular. Mutuamente exclusivo
      com `point_lonlat`/`buffer_dist` — o chamador escolhe um dos dois.
    - Nenhum dos dois informado: lê o raster inteiro, sem recorte — usado
      quando o usuário sobe só o GeoTIFF, sem enviar um ponto/município de
      interesse.

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

    has_point_region = point_lonlat is not None and buffer_dist is not None
    has_municipio_region = region_geojson is not None
    municipio_geom_wgs84 = _municipio_geometry_shapely(region_geojson) if has_municipio_region else None

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

                if has_point_region:
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
                elif has_municipio_region:
                    # Mesma ideia do ponto: recorta uma janela (bbox do
                    # município + margem) AINDA em graus antes de reprojetar,
                    # em vez de reprojetar o raster inteiro. A zona UTM usada
                    # é a do centróide do município — aproximação aceitável
                    # mesmo para municípios que cruzem duas zonas (o próprio
                    # modo ponto já faz a mesma simplificação para buffers
                    # grandes).
                    _report(0.60, "CRS geográfico detectado — recortando janela ao redor do município...")
                    min_lon, min_lat, max_lon, max_lat = municipio_geom_wgs84.bounds
                    margin_deg = 0.02  # ~2km de margem de segurança para a reprojeção não faltar pixel na borda
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
                # Já em CRS projetado — comportamento original preservado.
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


def _section_header(text: str, level: int = 5) -> None:
    """Cabeçalho de seção com um destaque sutil (borda colorida à esquerda),
    sem cor de texto/fundo fixa — substitui o padrão anterior de `st.markdown`
    com `background-color:yellow`/`lightgreen` + `color:black` hardcoded, que
    ficava ilegível/destoante no tema escuro do Streamlit (o bloco continuava
    claro mesmo com o resto da UI em tema escuro). Herda a cor de texto do
    tema ativo do usuário."""
    tag = f"h{level}"
    st.markdown(
        f'<{tag} style="border-left: 4px solid {METRIC_CHART_COLOR}; padding-left: 0.6em; margin: 0.5em 0;">{text}</{tag}>',
        unsafe_allow_html=True,
    )


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

    st.altair_chart(chart, use_container_width=True)

    top_class, top_value = df.iloc[-1]["Classe"], df.iloc[-1]["Valor"]
    bottom_class, bottom_value = df.iloc[0]["Classe"], df.iloc[0]["Valor"]
    if len(df) > 1:
        st.caption(
            f"Maior valor: **{top_class}** ({top_value:,.2f}) • Menor: "
            f"**{bottom_class}** ({bottom_value:,.2f})"
        )


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
    _section_header(f"🌎 Métricas da paisagem (nível global) — {calculated}/{len(LANDSCAPE_METRICS_INFO)}:")
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
                          buffer_dist=None, whole_raster=False, municipio_codigo=None) -> str:
    """Identifica de forma estável 'esta mesma submissão', para o cache de
    resultados em db.metric_results — uma resubmissão com a mesma
    fingerprint reaproveita o resultado já calculado em vez de refazer a
    extração (Earth Engine/GeoTIFF) e o PyLandStats.

    - GeoTIFF (com ou sem ponto/município): hash dos bytes do arquivo
      enviado — exato, reconhece o mesmo arquivo independente do nome.
      `whole_raster` entra na fingerprint para não colidir o mesmo arquivo
      submetido com ponto numa vez e sem ponto em outra (resultados
      diferentes).
    - MapBiomas ou GeoTIFF com área municipal: hash do código IBGE do
      município (`municipio_codigo`), no lugar de ponto/buffer.
    - MapBiomas com ponto (sem arquivo): hash do ponto (arredondado a 5
      casas, ~1,1m — absorve o jitter de redesenhar o mesmo ponto no mapa) +
      buffer.

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
    if municipio_codigo is not None:
        hasher.update(f"|municipio|{municipio_codigo}".encode("utf-8"))
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


def _render_markov_prediction(file_results: list) -> None:
    """UI da predição de anos futuros — só funciona com os arrays de pixel
    brutos de cada ano (não com resultados vindos do cache, que só guardam
    os VALORES das métricas já calculadas, ver `db.get_metric_result`).
    Exige pelo menos 2 anos com array disponível e ano identificável pelo
    nome do arquivo (ver `_extract_year_from_filename`)."""
    usable = sorted(
        (r for r in file_results if r.get("np_arr_mb") is not None and r.get("year") is not None),
        key=lambda r: r["year"],
    )
    if len(usable) < 2:
        st.info(
            "🔮 Predição para anos futuros indisponível: são necessários pelo menos 2 "
            "arquivos com ano identificável no nome do arquivo E calculados nesta sessão "
            "(resultados vindos do cache não guardam os pixels brutos — marque "
            "'Forçar novo cálculo' acima se precisar)."
        )
        return

    years = [r["year"] for r in usable]
    arrays = [r["np_arr_mb"] for r in usable]

    _section_header("🔮 Predição para anos futuros")
    st.caption(
        "Projeta a proporção futura de cada classe de cobertura do solo a partir da "
        "matriz de transição observada entre os anos calculados (cadeia de Markov). "
        "Método não-espacial — projeta só as proporções agregadas, não um mapa futuro "
        "— e assume que as probabilidades de transição observadas no histórico se "
        "mantêm estáveis no tempo."
    )

    avg_interval = (years[-1] - years[0]) / (len(years) - 1)
    max_target = years[-1] + 30
    default_target = min(years[-1] + max(round(avg_interval), 1), max_target)

    target_years = st.multiselect(
        "Anos para projetar",
        options=list(range(years[-1] + 1, max_target + 1)),
        default=[default_target],
        key="markov_target_years",
    )
    if not target_years:
        return

    transition_df = _build_transition_matrix(arrays, years)
    last_classes, last_counts = np.unique(arrays[-1], return_counts=True)
    last_proportions = pd.Series(last_counts / last_counts.sum(), index=last_classes.astype(int))

    projection_df = _project_future_landcover(
        transition_df, years[-1], last_proportions, avg_interval, sorted(target_years)
    )
    if projection_df.empty:
        return

    legend_dict = {i: name for i, name in enumerate(MAPBIOMAS_LEGEND_KEYS)}
    projection_labeled = projection_df.rename(
        columns={c: legend_dict.get(c, f"Classe {c}") for c in projection_df.columns}
    )
    st.dataframe(projection_labeled.round(2), use_container_width=True)

    # Gráfico: histórico (linha sólida) + projeção (tracejada), ancorando o
    # início da linha projetada no último ano observado para não deixar um
    # "salto" visual entre as duas.
    chart_rows = []
    for year, arr in zip(years, arrays):
        vals, counts = np.unique(arr, return_counts=True)
        for cls, prop in zip(vals, counts / counts.sum() * 100):
            chart_rows.append({"ano": year, "classe": int(cls), "valor": prop, "tipo": "Observado"})
    for cls, prop in zip(last_classes, last_counts / last_counts.sum() * 100):
        chart_rows.append({"ano": years[-1], "classe": int(cls), "valor": prop, "tipo": "Projetado"})
    for year in projection_df.index:
        for cls in projection_df.columns:
            chart_rows.append({"ano": year, "classe": cls, "valor": projection_df.loc[year, cls], "tipo": "Projetado"})

    chart_df = pd.DataFrame(chart_rows)
    chart_df["Classe"] = chart_df["classe"].map(lambda c: legend_dict.get(c, f"Classe {c}"))
    top_classes = (
        chart_df[chart_df["tipo"] == "Observado"].groupby("Classe")["valor"].mean()
        .sort_values(ascending=False).head(len(CATEGORICAL_PALETTE)).index.tolist()
    )
    chart_df = chart_df[chart_df["Classe"].isin(top_classes)]

    chart = alt.Chart(chart_df).mark_line(point=True).encode(
        x=alt.X("ano:O", title="Ano"),
        y=alt.Y("valor:Q", title="Proporção da paisagem (%)"),
        color=alt.Color("Classe:N", scale=alt.Scale(domain=top_classes, range=CATEGORICAL_PALETTE[:len(top_classes)])),
        strokeDash=alt.StrokeDash("tipo:N", title=None),
        tooltip=["ano", "Classe", alt.Tooltip("valor:Q", title="Proporção (%)", format=",.1f"), "tipo"],
    ).properties(height=320)
    st.altair_chart(chart, use_container_width=True)

    csv_bytes = projection_labeled.round(3).to_csv(sep=";", decimal=",").encode("utf-8")
    st.download_button(
        "📥 Download CSV (predição)",
        csv_bytes,
        f"predicao_landcover_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
        "text/csv",
        key="download-markov-csv",
        use_container_width=True,
    )


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
    _render_markov_prediction(file_results)

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


def _build_sse_matrix(user_email: str) -> "pd.DataFrame":
    """Monta a base da matriz socioecológica (SSE): uma linha por análise já
    salva do usuário (ver 'Suas análises anteriores'/`db.metric_results`),
    colunas = proporção de área por classe de cobertura do solo (wide) +
    métricas de nível de paisagem + identificação (label, fonte,
    município/UF/ano, data do cálculo). Só usa o que já está persistido —
    não recalcula nada. Retorna um DataFrame vazio se o usuário ainda não
    tem nenhuma análise salva."""
    history = db.list_metric_results(user_email, full=True)
    if not history:
        return pd.DataFrame()

    rows = []
    for item in history:
        class_metrics_df = pd.read_json(io.StringIO(item["class_metrics_json"]), orient="split")
        landscape_metrics = json.loads(item["landscape_metrics_json"])

        row = {
            "label": item["label"],
            "data_source": item["data_source"],
            "municipio_codigo": item.get("municipio_codigo"),
            "municipio_nome": item.get("municipio_nome"),
            "municipio_uf": item.get("municipio_uf"),
            "ano": item.get("ano"),
            "created_at": item["created_at"],
        }
        if "proportion_of_landscape" in class_metrics_df.columns:
            for cls_name, value in class_metrics_df["proportion_of_landscape"].items():
                row[f"pct_{cls_name}"] = value
        for name, _icon, short, _full in LANDSCAPE_METRICS_INFO:
            if landscape_metrics.get(name) is not None:
                row[short] = landscape_metrics[name]
        rows.append(row)

    matrix = pd.DataFrame(rows)
    # Colunas pct_* ausentes numa linha significam "classe não presente
    # nessa análise" (0%), não um dado faltante — só essas colunas levam
    # fillna(0); o resto (município, ano, métricas de paisagem) fica NaN de
    # propósito quando ausente.
    pct_cols = [c for c in matrix.columns if c.startswith("pct_")]
    matrix[pct_cols] = matrix[pct_cols].fillna(0.0)
    return matrix


def _render_sse_matrix_section(user_email: str) -> None:
    """Seção 'Matriz socioecológica (SSE)': mostra a matriz de
    `_build_sse_matrix`, permite anexar variáveis externas (socioeconômicas/
    hidroclimáticas) via CSV do usuário casado por município+ano, enriquece
    automaticamente com população estimada do IBGE quando há município
    identificado, e oferece um heatmap de correlação + download CSV."""
    _section_header("🧬 Matriz socioecológica (SSE)")
    st.caption(
        "Agrega todas as suas análises salvas (seção acima) numa única matriz "
        "multivariada: uma linha por análise, métricas de paisagem + variáveis "
        "socioeconômicas/hidroclimáticas que você anexar."
    )

    sse_matrix = _build_sse_matrix(user_email)
    if sse_matrix.empty:
        st.caption("Calcule ao menos uma análise (seções abaixo) para começar a montar a matriz.")
        return

    has_municipio = "municipio_codigo" in sse_matrix.columns and sse_matrix["municipio_codigo"].notna().any()
    if has_municipio:
        with st.spinner("🏘️ Buscando população estimada (IBGE) para os municípios da matriz..."):
            sse_matrix["populacao_estimada_ibge"] = sse_matrix["municipio_codigo"].apply(
                lambda cod: _ibge_get_populacao_estimada(str(cod)) if pd.notna(cod) else None
            )

    external_csv = st.file_uploader(
        "📁 (Opcional) CSV com variáveis socioeconômicas/hidroclimáticas — precisa "
        "ter a coluna 'municipio_codigo' (ou 'municipio_nome') e, se houver série "
        "temporal, 'ano'; qualquer outra coluna é livre (ex.: populacao, pib, "
        "precipitacao_mm, temperatura_media_c)",
        type=["csv"],
        key="sse_csv_upload",
    )
    if external_csv is not None:
        try:
            external_df = pd.read_csv(external_csv)
        except Exception as csv_error:
            st.error(f"❌ Não foi possível ler o CSV enviado: {csv_error}")
            external_df = None

        if external_df is not None:
            if "municipio_codigo" in external_df.columns:
                merge_cols = ["municipio_codigo"] + (["ano"] if "ano" in external_df.columns else [])
            elif "municipio_nome" in external_df.columns:
                merge_cols = ["municipio_nome"] + (["ano"] if "ano" in external_df.columns else [])
            else:
                merge_cols = None

            if merge_cols is None:
                st.error(
                    "❌ O CSV precisa ter a coluna 'municipio_codigo' ou 'municipio_nome' "
                    "para ser cruzado com suas análises."
                )
            else:
                # Tipos precisam bater para o merge casar (ex.: código IBGE como
                # texto dos dois lados) — nunca inventa/força um valor, só
                # normaliza a representação.
                for col in merge_cols:
                    if col in sse_matrix.columns:
                        sse_matrix[col] = sse_matrix[col].astype(str)
                    external_df[col] = external_df[col].astype(str)

                before_cols = set(sse_matrix.columns)
                sse_matrix = sse_matrix.merge(external_df, on=merge_cols, how="left")
                new_cols = [c for c in sse_matrix.columns if c not in before_cols]
                matched = int(sse_matrix[new_cols].notna().any(axis=1).sum()) if new_cols else 0
                st.caption(
                    f"🔗 {matched}/{len(sse_matrix)} linha(s) casaram com o CSV enviado "
                    f"(por {' + '.join(merge_cols)}). Linhas sem correspondência ficam com "
                    "essas colunas vazias — a matriz nunca preenche um valor inventado."
                )

    st.dataframe(sse_matrix, use_container_width=True)

    numeric_cols = sse_matrix.select_dtypes(include=[np.number]).columns.tolist()
    if len(numeric_cols) >= 2:
        with st.expander("🔥 Correlação entre variáveis (mapa de calor)", expanded=False):
            corr = sse_matrix[numeric_cols].corr()
            corr_long = corr.reset_index(names="variavel_1").melt(
                id_vars="variavel_1", var_name="variavel_2", value_name="correlacao"
            )
            # Par diverging vermelho↔azul com meio-tom neutro cinza (ver skill de
            # dataviz, references/palette.md § Diverging pair) — não a paleta
            # categórica (CATEGORICAL_PALETTE), que é para identidade, não polaridade.
            heatmap = alt.Chart(corr_long).mark_rect().encode(
                x=alt.X("variavel_1:N", title=None),
                y=alt.Y("variavel_2:N", title=None),
                color=alt.Color(
                    "correlacao:Q", title="Correlação",
                    scale=alt.Scale(domain=[-1, 0, 1], range=["#e34948", "#f0efec", "#2a78d6"]),
                ),
                tooltip=["variavel_1", "variavel_2", alt.Tooltip("correlacao:Q", format=",.2f")],
            ).properties(height=max(25 * len(numeric_cols), 200))
            st.altair_chart(heatmap, use_container_width=True)

    sse_csv_bytes = sse_matrix.to_csv(sep=";", decimal=",", index=False).encode("utf-8")
    st.download_button(
        "📥 Download CSV (matriz socioecológica)",
        sse_csv_bytes,
        f"matriz_socioecologica_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
        "text/csv",
        key="download-sse-csv",
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
        st.title("🏞️ Landscape Metrics Extractor")
        st.caption(
            "Powered by MapBiomas, Pylandstats, Google Earth Engine and Geemap | Developed by Pedro Higuchi ([@pe_hi](https://twitter.com/pe_hi))"
        )
        st.caption("Contato: higuchip@gmail.com")

    with col2:
        st.info(
            "Aplicativo Web para extração de métricas de paisagem de pontos ou "
            "municípios de interesse a partir da base de dados do MapBiomas"
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
            _municipio_bits = " · ".join(
                filter(None, [_item.get("municipio_nome"), _item.get("municipio_uf")])
            )
            _ano_bit = f" · {int(_item['ano'])}" if _item.get("ano") is not None else ""
            _title = (
                f"{_item['label']} · {_item['data_source']}"
                f"{' · ' + _municipio_bits if _municipio_bits else ''}{_ano_bit} · {_when}"
            )
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

    _render_sse_matrix_section(user_email)

    st.markdown("---")

    # Seção 1: Área de interesse — ponto+buffer (comportamento original) ou
    # limite municipal (IBGE, ver `_ibge_get_*`/`extract_landscape_from_tif`
    # `region_geojson`).
    st.markdown(
        "<h3>1) Área de interesse 🗺️</h3>",
        unsafe_allow_html=True,
    )
    roi_mode = st.radio(
        "Como você quer definir a área de interesse?",
        ["📌 Ponto + buffer", "🏘️ Limite municipal (IBGE)"],
        horizontal=True,
    )

    data = None
    municipio_info = None

    if roi_mode == "📌 Ponto + buffer":
        st.markdown("#### Selecione um ponto de interesse 📌")
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

        st.markdown("#### Upload do ponto de interesse 📤")
        data = st.file_uploader(
            "📁 Faça upload do GeoJSON exportado acima, ou de um shapefile do ponto compactado em .zip",
            type=["geojson", "zip"],
            help=(
                f"Limite: {MAX_FILE_SIZE // (1024*1024)}MB • GeoJSON (.geojson) ou shapefile "
                "compactado (.zip com .shp+.shx+.dbf+.prj) — em ambos os casos, com exatamente "
                "1 ponto"
            ),
        )
    else:
        st.markdown("#### Selecione o município 🏘️")
        try:
            ufs = _ibge_get_ufs()
        except requests.RequestException as ufs_error:
            logger.error(f"Falha ao buscar UFs do IBGE: {ufs_error}")
            st.error(
                "❌ Não foi possível buscar a lista de estados na API do IBGE. "
                "Verifique sua conexão e tente novamente."
            )
            ufs = []

        if ufs:
            uf_labels = {f"{uf['sigla']} — {uf['nome']}": uf["sigla"] for uf in ufs}
            uf_label = st.selectbox("Estado (UF)", list(uf_labels.keys()))
            uf_sigla = uf_labels[uf_label]

            try:
                municipios = _ibge_get_municipios(uf_sigla)
            except requests.RequestException as municipios_error:
                logger.error(f"Falha ao buscar municípios do IBGE ({uf_sigla}): {municipios_error}")
                st.error("❌ Não foi possível buscar os municípios dessa UF na API do IBGE.")
                municipios = []

            if municipios:
                municipio_labels = {m["nome"]: m for m in sorted(municipios, key=lambda m: m["nome"])}
                municipio_label = st.selectbox("Município", list(municipio_labels.keys()))
                municipio_sel = municipio_labels[municipio_label]

                municipio_geojson = _ibge_get_municipio_geojson(str(municipio_sel["id"]))
                if municipio_geojson is None:
                    st.error(
                        "❌ Não foi possível buscar o limite territorial deste município na "
                        "API do IBGE (malhas territoriais). Tente novamente em instantes ou "
                        "escolha outro município."
                    )
                else:
                    municipio_info = {
                        "codigo": str(municipio_sel["id"]),
                        "nome": municipio_sel["nome"],
                        "uf": uf_sigla,
                        "geojson": municipio_geojson,
                    }
                    st.success(f"✅ Município selecionado: {municipio_info['nome']}/{uf_sigla}")
                    try:
                        municipio_geom_preview = _municipio_geometry_shapely(municipio_geojson)
                        centroid = municipio_geom_preview.centroid
                        import folium
                        preview_map = folium.Map(location=[centroid.y, centroid.x], zoom_start=9)
                        folium.GeoJson(municipio_geojson, name=municipio_info["nome"]).add_to(preview_map)
                        st_folium(preview_map, width=700, height=350, returned_objects=[])
                    except Exception as preview_error:
                        logger.warning(f"Falha ao desenhar preview do município: {preview_error}")
                        st.info("📍 Município pronto para análise (preview do mapa indisponível).")

    st.markdown("---")

    # Seção 2: Fonte dos dados de cobertura do solo
    st.markdown(
        "<h3>2) Fonte dos dados de cobertura do solo 🛰️</h3>",
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
        elif roi_mode == "🏘️ Limite municipal (IBGE)":
            st.caption(
                "O limite municipal selecionado na Seção 1 recorta este raster "
                "automaticamente — ele pode cobrir uma área bem maior que o município."
            )
        elif data:
            st.caption(
                "O ponto e o buffer definidos abaixo recortam este raster — ele pode "
                "cobrir uma área bem maior que o buffer."
            )
        else:
            st.info(
                "📌 Nenhum ponto foi enviado na Seção 1 — as métricas serão calculadas "
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

    # Modo raster inteiro: só faz sentido com raster próprio no modo
    # "ponto+buffer" (o MapBiomas é um asset nacional, sem um "raster
    # inteiro" delimitado, então sempre exige um ponto+buffer ou município).
    # Ativado quando o usuário sobe um GeoTIFF sem também subir um ponto de
    # interesse na Seção 1. No modo município, o raster é sempre recortado
    # pelo limite municipal — não existe "modo raster inteiro" nesse caso.
    own_raster_whole_mode = (
        data_source == "Meu raster (GeoTIFF)" and bool(tif_files)
        and roi_mode == "📌 Ponto + buffer" and not data
    )

    # Processamento principal
    if roi_mode == "🏘️ Limite municipal (IBGE)":
        ready_to_process = municipio_info is not None and (
            data_source == "MapBiomas (Google Earth Engine)"
            or (data_source == "Meu raster (GeoTIFF)" and tif_files)
        )
    else:
        ready_to_process = (
            (data_source == "MapBiomas (Google Earth Engine)" and data)
            or (data_source == "Meu raster (GeoTIFF)" and tif_files)
        )
    if ready_to_process:
        try:
            if roi_mode == "🏘️ Limite municipal (IBGE)":
                gdf_features = None
                buffer_dist = None
                region_geojson = municipio_info["geojson"]
            elif own_raster_whole_mode:
                gdf_features = None
                buffer_dist = None
                region_geojson = None
            else:
                region_geojson = None
                # Seção 3: Configuração do buffer
                st.markdown(
                    "<h3>3) Defina o tamanho do raio (m) do buffer 🎯</h3>",
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
                "<h3>4) Calcular métricas 🧮</h3>",
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
                        if roi_mode == "🏘️ Limite municipal (IBGE)":
                            _set_stage(
                                0.10,
                                f"Preparando área de interesse (município: {municipio_info['nome']}/{municipio_info['uf']})...",
                            )
                            st.write(
                                f"🏘️ Preparando área municipal: {municipio_info['nome']}/{municipio_info['uf']}..."
                            )
                            try:
                                municipio_geom_ee = mapping(_municipio_geometry_shapely(region_geojson))
                                roi_buffer = ee.Geometry(municipio_geom_ee)
                                roi = ee.FeatureCollection([ee.Feature(roi_buffer)])
                                st.write(f"✅ Área municipal pronta: {municipio_info['nome']}/{municipio_info['uf']}")
                            except Exception as municipio_roi_error:
                                logger.error(f"Erro ao preparar geometria municipal para o Earth Engine: {municipio_roi_error}")
                                raise RuntimeError(
                                    f"Não foi possível preparar a geometria de "
                                    f"'{municipio_info['nome']}/{municipio_info['uf']}' para o Earth Engine."
                                ) from municipio_roi_error
                            _set_stage(0.20, "Área de interesse pronta")
                        elif own_raster_whole_mode:
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
                                    _year_i = _extract_year_from_filename(_tif_item.name)
                                    _fingerprint_i = _compute_fingerprint(
                                        data_source, tif_bytes=_tif_item.getvalue(), point_lonlat=_point_lonlat_i,
                                        buffer_dist=buffer_dist, whole_raster=own_raster_whole_mode,
                                        municipio_codigo=municipio_info["codigo"] if municipio_info else None,
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
                                            "year": _year_i,
                                            "np_arr_mb": None,
                                            "ls": None,
                                            "class_metrics_df_sub": _cached_i["class_metrics_df_sub"],
                                            "landscape_metrics": _cached_i["landscape_metrics"],
                                            "reprojected_tif_bytes": None,
                                        })
                                        continue

                                    try:
                                        if municipio_info is not None:
                                            _arr, _res, _reproj_bytes = extract_landscape_from_tif(
                                                _tif_item, region_geojson=region_geojson,
                                                on_progress=_update_tif_progress,
                                                cleanup=False, temp_path_out=_temp_paths,
                                            )
                                        elif own_raster_whole_mode:
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
                                            "Possíveis causas: buffer/município fora da área do raster, CRS "
                                            "incompatível, raster com apenas nodata, ou arquivo corrompido."
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
                                        municipio_codigo=municipio_info["codigo"] if municipio_info else None,
                                        municipio_nome=municipio_info["nome"] if municipio_info else None,
                                        municipio_uf=municipio_info["uf"] if municipio_info else None,
                                        ano=_year_i,
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
                                municipio_codigo=municipio_info["codigo"] if municipio_info else None,
                            )
                            ano = None  # preenchido abaixo (MapBiomas: ano mais recente; GeoTIFF: nome do arquivo)
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
                                        ano = latest_year

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
                                    ano = _extract_year_from_filename(tif_file.name) if tif_file else None
                                    tif_stage_label = (
                                        f"Recortando o GeoTIFF enviado pelo limite municipal ({municipio_info['nome']})..."
                                        if municipio_info is not None else
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
                                        if municipio_info is not None:
                                            np_arr_mb, resolution, reprojected_tif_bytes = extract_landscape_from_tif(
                                                tif_file, region_geojson=region_geojson,
                                                on_progress=_update_tif_progress,
                                            )
                                        elif own_raster_whole_mode:
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

                                _default_label = (
                                    f"{municipio_info['nome']}/{municipio_info['uf']}"
                                    if municipio_info else "MapBiomas (Google Earth Engine)"
                                )
                                db.save_metric_result(
                                    user_email, fingerprint,
                                    tif_file.name if tif_file else _default_label,
                                    data_source, point_lonlat, buffer_dist,
                                    class_metrics_df_sub, landscape_metrics,
                                    municipio_codigo=municipio_info["codigo"] if municipio_info else None,
                                    municipio_nome=municipio_info["nome"] if municipio_info else None,
                                    municipio_uf=municipio_info["uf"] if municipio_info else None,
                                    ano=ano,
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
                        _section_header("🗺️ Classes de cobertura do solo:")

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
                            _section_header("📍 Área de interesse:")

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
                    _section_header("📈 Métricas da paisagem:")
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
