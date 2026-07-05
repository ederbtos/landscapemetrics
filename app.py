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
para o cálculo das métricas de paisagem propriamente ditas.

Regras de negócio
------------------
- Um único ponto de interesse por execução; múltiplos pontos no GeoJSON são
  rejeitados (linha ~382).
- Buffer configurável entre MIN_BUFFER e MAX_BUFFER metros ao redor do ponto.
- Upload restrito a `.geojson` até MAX_FILE_SIZE, com sanitização de nome de
  arquivo (ver validate_file_upload).

Pontos de atenção
------------------
- RISCO DE INTEGRIDADE DE DADOS: quando a extração via Earth Engine falha em
  qualquer estágio (asset indisponível, sampleRectangle, reduceRegion), o
  fluxo principal substitui os dados reais por arrays codificados
  ("dados representativos de Santa Catarina") e segue exibindo
  gráficos/métricas/CSV normalmente, apenas com um `st.warning`/`st.error`
  acima. Um usuário que não leia a mensagem pode baixar e usar como real uma
  análise que não tem nenhuma relação com o ponto que selecionou. Ver
  comentários nos blocos de fallback abaixo.
- Múltiplos blocos de try/except aninhados com lógica de fallback duplicada
  tornam o fluxo difícil de auditar e de testar; um refactor extraindo cada
  etapa (seleção de asset, extração de pixels, cálculo de métricas) em
  funções puras testáveis reduziria bastante o risco acima.
- `except:` bare no botão "Status GEE" (linha ~276) engole qualquer exceção,
  inclusive erros de programação, não só falha de conectividade.

Melhorias sugeridas
---------------------
- Nunca substituir dados reais por dados sintéticos de forma transparente ao
  usuário: falhar explicitamente (ou, no mínimo, bloquear o download do CSV)
  quando a extração do Earth Engine não tiver sucesso.
- Extrair a lógica de negócio (seleção de asset MapBiomas, extração de
  pixels, cálculo de métricas) do corpo do script Streamlit para funções
  puras, permitindo testes unitários sem precisar renderizar a UI.
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
import pandas as pd
import pylandstats as pls
import collections
import geopandas as gpd
import rasterio
from rasterio.mask import mask as rio_mask
from pyproj import Transformer
from shapely.geometry import Point, mapping
import tempfile
import os
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
ALLOWED_EXTENSIONS = {'.geojson'}
MAX_TIF_SIZE = 5 * 1024 * 1024 * 1024  # 5GB (server.maxUploadSize em .streamlit/config.toml precisa bater com isso)
ALLOWED_TIF_EXTENSIONS = {'.tif', '.tiff'}
MIN_BUFFER = 1000
MAX_BUFFER = 10000

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
                else:
                    # Para GeoJSON, lê normalmente
                    gdf = gpd.read_file(file_path)
                    
            except Exception as read_error:
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


def extract_landscape_from_tif(uploaded_tif, point_lonlat, buffer_dist, on_progress=None):
    """
    Recorta o GeoTIFF enviado pelo usuário na área do buffer (ponto + raio em
    metros) e retorna o array de classes de cobertura do solo e a resolução
    real do pixel — alternativa a extrair os mesmos dados via
    MapBiomas/Earth Engine (ver seção "Fonte dos dados" em app.py).

    Pontos de atenção: exige CRS projetado (metros) no GeoTIFF — um CRS
    geográfico (graus) tornaria buffer_dist (definido em metros) incorreto
    sem reprojetar o raster inteiro, então é rejeitado explicitamente em vez
    de produzir um recorte de tamanho errado silenciosamente. O arquivo
    temporário em disco é sempre removido no `finally`, com sucesso ou falha
    — nunca fica retido além da própria chamada.
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
                _report(0.6 * written / total_bytes, "Salvando arquivo enviado...")

        _report(0.65, "Abrindo raster e validando projeção...")
        with rasterio.open(file_path) as src:
            if src.crs is None:
                raise ValueError("O GeoTIFF não tem CRS (sistema de referência) definido.")
            if src.crs.is_geographic:
                raise ValueError(
                    "O GeoTIFF precisa estar em uma projeção métrica (ex.: UTM) — "
                    "este arquivo está em coordenadas geográficas (graus), o que "
                    "tornaria o buffer em metros incorreto."
                )

            transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            x, y = transformer.transform(point_lonlat[0], point_lonlat[1])
            buffer_geom = Point(x, y).buffer(buffer_dist)

            _report(0.8, "Recortando a área do buffer...")
            nodata_value = src.nodata if src.nodata is not None else 0
            try:
                out_image, _ = rio_mask(src, [mapping(buffer_geom)], crop=True, nodata=nodata_value)
            except ValueError as mask_error:
                raise ValueError("A área do buffer não intersecta o raster enviado.") from mask_error

            array = out_image[0]
            resolution = (abs(src.res[0]), abs(src.res[1]))

        if array.size == 0 or np.all(array == nodata_value):
            raise ValueError(
                "Nenhum pixel válido dentro da área do buffer, dentro dos limites do "
                "raster enviado. Aumente o buffer, escolha outro ponto, ou confirme "
                "que o raster cobre essa área."
            )

        _report(0.95, "Descartando arquivo temporário...")
        return array, resolution
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                _report(1.0, "Arquivo temporário descartado")
            except Exception as cleanup_error:
                logger.warning(f"Erro ao limpar arquivo temporário: {cleanup_error}")


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
    📁 GeoJSON máx: {MAX_FILE_SIZE // (1024*1024)}MB
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
        "<h3>2) Upload do arquivo GeoJSON 📤</h3>",
        unsafe_allow_html=True,
    )

    data = st.file_uploader(
        f"📁 Faça upload do arquivo GeoJSON exportado acima",
        type=["geojson"],
        help=f"Limite: {MAX_FILE_SIZE // (1024*1024)}MB • Apenas arquivos GeoJSON são aceitos"
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

    tif_file = None
    if data_source == "Meu raster (GeoTIFF)":
        tif_file = st.file_uploader(
            "📁 Faça upload do GeoTIFF com os dados de cobertura do solo",
            type=["tif", "tiff"],
            help=(
                f"Limite: {MAX_TIF_SIZE // (1024*1024)}MB • Precisa estar em CRS "
                "projetado (ex.: UTM), não geográfico (graus), e usar os mesmos "
                "códigos de classe do MapBiomas"
            ),
        )
        st.caption(
            "O ponto e o buffer definidos abaixo recortam este raster — ele pode "
            "cobrir uma área bem maior que o buffer."
        )

    st.markdown("---")

    # Processamento principal
    if data and (data_source == "MapBiomas (Google Earth Engine)" or tif_file):
        try:
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
                    try:
                        # Cria ROI e buffer com tratamento de erro robusto
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

                        if data_source == "MapBiomas (Google Earth Engine)":
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
                            st.write("📂 Recortando o GeoTIFF enviado...")
                            tif_progress = st.progress(0, text="Iniciando processamento do GeoTIFF...")

                            def _update_tif_progress(fraction, label):
                                tif_progress.progress(min(max(fraction, 0.0), 1.0), text=label)

                            try:
                                np_arr_mb, resolution = extract_landscape_from_tif(
                                    tif_file, gdf_features[0]['geometry']['coordinates'], buffer_dist,
                                    on_progress=_update_tif_progress,
                                )
                                unique_values = np.unique(np_arr_mb)
                                st.write(f"✅ Dados processados: {np_arr_mb.shape[0]}×{np_arr_mb.shape[1]} pixels")
                                st.write(f"📊 Classes encontradas: {len(unique_values)} → {unique_values}")
                                st.write("🗑️ Arquivo GeoTIFF temporário descartado do servidor após o recorte.")

                            except Exception as tif_error:
                                logger.error(f"Erro ao extrair dados do GeoTIFF: {tif_error}")
                                raise RuntimeError(
                                    "Não foi possível extrair dados reais do GeoTIFF enviado para esta "
                                    "área. Isso não gera uma análise substituta com dados de exemplo — a "
                                    "extração real é obrigatória para que as métricas exibidas sejam "
                                    f"confiáveis. Detalhes: {tif_error}. Possíveis causas: buffer fora "
                                    "da área do raster, CRS do raster não é projetado (metros), ou o "
                                    "raster não cobre essa região. Aumente o buffer, selecione outro "
                                    "ponto ou confira o arquivo enviado."
                                ) from tif_error
                            finally:
                                tif_progress.empty()

                            # Instancia PyLandStats com validação
                            st.write("📊 Calculando métricas da paisagem (PyLandStats)...")
                            try:
                                if np_arr_mb.shape[0] < 3 or np_arr_mb.shape[1] < 3:
                                    st.write("⚠️ Área pequena, expandindo para análise...")
                                    np_arr_mb = np.pad(np_arr_mb, ((1, 1), (1, 1)), mode='constant', constant_values=0)

                                ls = pls.Landscape(np_arr_mb, res=resolution)
                            except Exception as pls_error:
                                logger.error(f"Erro no PyLandStats: {pls_error}")
                                raise RuntimeError(
                                    f"Erro ao processar métricas da paisagem: {pls_error}. Forma do "
                                    f"array: {np_arr_mb.shape}. Valores únicos: {np.unique(np_arr_mb)}"
                                ) from pls_error

                            # Cálculo das métricas
                            st.write("🔢 Computando métricas detalhadas...")
                            try:
                                # Calcula métricas de classe
                                class_metrics_df = ls.compute_class_metrics_df(
                                    metrics=[
                                        'total_area', 'proportion_of_landscape', 'number_of_patches',
                                        'largest_patch_index', 'total_edge', 'landscape_shape_index',
                                        'area_mn', 'perimeter_mn', 'perimeter_area_ratio_mn',
                                        'shape_index_mn', 'fractal_dimension_mn', 'euclidean_nearest_neighbor_mn'
                                    ]
                                )

                                # Processa índices das classes
                                classes_index = list(map(int, class_metrics_df.index))

                                # Dicionário de legendas MapBiomas completo
                                # Limitação conhecida: mapeamento fixo por posição de índice,
                                # construído a partir do esquema de classes da Collection
                                # (aprox. 9); classes não usadas nesse esquema ficam como ' '.
                                # Se uma collection mais nova mudar/adicionar códigos de classe
                                # (ver seleção de asset acima), este dicionário precisa ser
                                # atualizado manualmente — não há acoplamento automático entre
                                # a collection selecionada e a legenda usada aqui.
                                legend_keys = [
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
                                    'Restinga arborea'  # 49
                                ]

                                # Cria dicionário de legenda
                                keys = list(range(len(legend_keys)))
                                legend_dict = {keys[i]: legend_keys[i] for i in range(len(legend_keys))}

                                # Substitui índices por nomes
                                replaced_list = [legend_dict.get(x, f'Classe {x}') for x in classes_index]
                                class_metrics_df.index = replaced_list

                                # Filtra elementos com mais de 10% de proporção
                                class_metrics_df_sub = class_metrics_df[class_metrics_df['proportion_of_landscape'] > 10]
                                class_metrics_df_sub = class_metrics_df_sub.sort_values(by=['total_area'], ascending=False)

                                if class_metrics_df_sub.empty:
                                    st.write("⚠️ Nenhuma classe com proporção > 10% encontrada. Mostrando todas as classes.")
                                    class_metrics_df_sub = class_metrics_df.sort_values(by=['total_area'], ascending=False)

                            except Exception as metrics_error:
                                logger.error(f"Erro ao calcular métricas: {metrics_error}")
                                raise RuntimeError(
                                    f"Erro ao calcular métricas da paisagem: {metrics_error}"
                                ) from metrics_error

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

                            pipeline_status.update(label="✅ Processamento concluído", state="complete")

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
                roi = st.session_state["roi"]
                roi_buffer = st.session_state["roi_buffer"]
                np_arr_mb = st.session_state["np_arr_mb"]
                ls = st.session_state["ls"]
                class_metrics_df_sub = st.session_state["class_metrics_df_sub"]

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
                    st.markdown(
                        "<h5 style=' color: black; background-color:yellow; padding:5px; border-radius: 5px; box-shadow: 0 0 0.1em black'> 🗺️ Classes de cobertura do solo:</h5>",
                        unsafe_allow_html=True
                    )

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

                st.markdown("---")

                # Cálculo das métricas
                st.markdown(
                    "<h5 style=' color: black; background-color:yellow; padding:5px; border-radius: 5px; box-shadow: 0 0 0.1em black'> 📈 Métricas da paisagem:</h5>",
                    unsafe_allow_html=True
                )
                st.info("📊 **Elementos com mais de 10% de proporção na paisagem:**")
                st.dataframe(class_metrics_df_sub, use_container_width=True)

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

                logger.info(
                    f"Métricas da paisagem calculadas com sucesso para buffer de "
                    f"{st.session_state['buffer_dist_used']}m"
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
    
        metrics_names = [
            'total_area', 'proportion_of_landscape', 'number_of_patches',
            'largest_patch_index', 'total_edge', 'landscape_shape_index',
            'area_mn', 'perimeter_mn', 'perimeter_area_ratio_mn',
            'shape_index_mn', 'fractal_dimension_mn', 'euclidean_nearest_neighbor_mn'
        ]
    
        metrics_traducao = [
            'Área Total (ha)', 'Proporção da paisagem (%)', 'Número de Manchas',
            'Índice de maior mancha', 'Total de Bordas', 'Índice de forma da paisagem',
            'Área média (ha)', 'Perímetro médio (m)', 'Razão de perímetro/área média',
            'Média de índice de forma', 'Dimensão fractal média', 
            'Distância média para o vizinho mais próximo (m)'
        ]

        zipped = list(zip(metrics_names, metrics_traducao))
        detalhamento_df = pd.DataFrame(zipped, columns=['Item', 'Métricas'])
        st.table(detalhamento_df.set_index("Item"))

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
