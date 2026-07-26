"""
Descrição da funcionalidade
---------------------------
Popula `mapbiomas_municipio_stats` (backend/app/db/mapbiomas_stats.py) com
área (hectares) por classe de cobertura do solo, por município e por ano,
para os últimos anos disponíveis do MapBiomas — substitui a alternativa de
guardar o raster de pixels nacional (inviável, dezenas de TB).

Dois caminhos, mutuamente exclusivos nesta execução:

1) **Earth Engine (padrão)**: roda `reduceRegions` com
   `ee.Reducer.frequencyHistogram()` contra a malha municipal já salva em
   `municipios_malha` (rode `seed_municipios_malha.py` antes), reaproveitando
   a mesma lista de assets com fallback já usada em
   `backend/app/services/landscape.py::_extract_mapbiomas_pixels`. Processa
   em lotes por UF (não o Brasil inteiro de uma vez) para não estourar o
   limite de computação por requisição do Earth Engine — não foi possível
   validar isso ao vivo nesta sessão por falta de uma credencial de conta de
   serviço aqui; teste primeiro com `--uf SC --anos 2023` (UF pequena, 1 ano)
   antes de rodar o histórico completo.
2) **Importação de Excel (`--from-excel arquivo.xlsx`)**: caminho
   alternativo caso você prefira baixar manualmente o arquivo oficial de
   Estatísticas do MapBiomas (brasil.mapbiomas.org/estatisticas/) em vez de
   esperar o cálculo via Earth Engine. A detecção de colunas é heurística
   (nomes variam entre coleções) — sempre loga o que detectou, nunca adivinha
   silenciosamente (mesmo espírito de `_detect_municipio_columns` em
   `landscape_core.py`). **Não testei contra um arquivo real** (não tenho um
   baixado nesta sessão) — confira o log de detecção de colunas na primeira
   execução.

Resumível: checkpoint em `scripts/.checkpoints/mapbiomas.json` por
`(uf, ano)` já concluído (caminho Earth Engine); upsert idempotente em
ambos os caminhos via `UNIQUE(municipio_codigo, ano, classe_codigo)`.

Uso:
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\seed_mapbiomas_stats.py --uf SC --anos 2023
    ..\\.venv\\Scripts\\python.exe ..\\scripts\\seed_mapbiomas_stats.py --from-excel caminho\\estatisticas.xlsx
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.db.mapbiomas_stats import save_mapbiomas_stat  # noqa: E402
from app.db.municipios import list_municipios_by_uf  # noqa: E402
from app.db.schema import init_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

UFS_BRASIL = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
]

# Mesma lista de fallback usada em backend/app/services/landscape.py::_extract_mapbiomas_pixels
MAPBIOMAS_ASSETS = [
    "projects/mapbiomas-public/assets/brazil/lulc/collection9/mapbiomas_collection90_integration_v1",
    "projects/mapbiomas-public/assets/brazil/lulc/collection8/mapbiomas_collection80_integration_v1",
    "projects/mapbiomas-workspace/public/collection7/mapbiomas_collection70_integration_v2",
    "projects/mapbiomas-workspace/public/collection6/mapbiomas_collection60_integration_v1",
]

# Mesma legenda usada em landscape_core.py (MAPBIOMAS_LEGEND_KEYS), índice = código da classe.
MAPBIOMAS_LEGEND_KEYS = [
    " ", "Floresta", " ", "Formacao florestal", "Savana", "Mangue", " ", " ", " ",
    "Silvicultura", "Formação natural nao-florestal", "Campo Alagado e Área Pantanosa",
    "Campos", "Outras formacoes nao-florestais", "Agropecuaria", "Pastagem", " ", " ",
    "Agricultura", "Agricultura temporarias", "Cana", "Mosaico de Agricultura e Pastagem",
    "Area nao Vegetada", "Dunas", "Area Urbanizada", "Outras areas nao vegetadas", "Agua",
    "Nao Observado", " ", "Afloramento rochoso", "Mineracao", "Aquicultura", "Sal",
    "Rio, lago e oceano", " ", " ", "Lavoura Perene", " ", " ", "Soja", "Arroz",
    "Outras culturas temporarias", " ", " ", " ", " ", "Cafe", "Citrus",
    "Outras lavouras perenes", "Restinga arborea",
]

CHECKPOINT_PATH = Path(__file__).resolve().parent / ".checkpoints" / "mapbiomas.json"


def classe_nome(codigo: int) -> str | None:
    if 0 <= codigo < len(MAPBIOMAS_LEGEND_KEYS):
        nome = MAPBIOMAS_LEGEND_KEYS[codigo].strip()
        return nome or None
    return None


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {}


def save_checkpoint(checkpoint: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def init_earth_engine(credentials_path: str) -> None:
    import ee

    with open(credentials_path, encoding="utf-8") as f:
        credentials = json.load(f)
    ee_credentials = ee.ServiceAccountCredentials(
        credentials.get("client_email"), key_data=json.dumps(credentials)
    )
    ee.Initialize(credentials=ee_credentials, opt_url="https://earthengine-highvolume.googleapis.com")


def pick_asset_for_band(band: str):
    """Mesma lógica de fallback de `_extract_mapbiomas_pixels`: tenta cada
    asset da lista até achar um que tenha a banda do ano pedido."""
    import ee

    for asset in MAPBIOMAS_ASSETS:
        try:
            image = ee.Image(asset)
            if band in image.bandNames().getInfo():
                return image
        except Exception:
            continue
    return None


def processar_uf_ano_earth_engine(uf: str, ano: int, checkpoint: dict) -> None:
    import ee

    chave = f"{uf}:{ano}"
    if chave in checkpoint:
        logger.info("UF %s / ano %d já concluído (checkpoint) — pulando.", uf, ano)
        return

    municipios = list_municipios_by_uf(uf)
    if not municipios:
        logger.warning("Nenhum município de %s em municipios_malha — rode seed_municipios_malha.py antes.", uf)
        return

    band = f"classification_{ano}"
    image = pick_asset_for_band(band)
    if image is None:
        logger.error("Nenhum asset MapBiomas com a banda %s — ano %d indisponível nas coleções conhecidas.", band, ano)
        return

    from app.db.municipios import get_municipio_malha

    features = []
    for m in municipios:
        row = get_municipio_malha(m["codigo_ibge"])
        try:
            geom = json.loads(row["geojson"])["features"][0]["geometry"]
            features.append(ee.Feature(ee.Geometry(geom), {"codigo_ibge": m["codigo_ibge"]}))
        except Exception as err:
            logger.warning("Geometria inválida para município %s (%s), pulando no lote: %s", m["codigo_ibge"], uf, err)

    if not features:
        logger.warning("Nenhuma geometria válida para %s — nada a fazer.", uf)
        return

    fc = ee.FeatureCollection(features)
    try:
        reduzido = image.select(band).reduceRegions(
            collection=fc, reducer=ee.Reducer.frequencyHistogram(), scale=30, tileScale=4
        ).getInfo()
    except Exception as err:
        logger.error("Falha no reduceRegions para %s/%d — considere reprocessar com menos municípios por lote: %s", uf, ano, err)
        return

    total_linhas = 0
    for feature in reduzido.get("features", []):
        props = feature.get("properties", {})
        codigo = props.get("codigo_ibge")
        histograma = props.get("histogram", {}) or {}
        for classe_str, contagem_pixels in histograma.items():
            try:
                classe_codigo = int(float(classe_str))
                area_ha = float(contagem_pixels) * 0.09  # pixel 30m x 30m = 900 m² = 0.09 ha
                save_mapbiomas_stat(codigo, ano, classe_codigo, classe_nome(classe_codigo), area_ha, "gee_reduceregions")
                total_linhas += 1
            except Exception as err:
                logger.warning("Erro salvando classe %s do município %s (%s/%d): %s", classe_str, codigo, uf, ano, err)

    logger.info("UF %s / ano %d: %d linhas (município x classe) salvas.", uf, ano, total_linhas)
    checkpoint[chave] = True
    save_checkpoint(checkpoint)


def importar_excel(caminho: str) -> None:
    import pandas as pd

    df = pd.read_excel(caminho)
    logger.info("Excel carregado: %d linhas, colunas: %s", len(df), list(df.columns))

    candidatos = {
        "municipio_codigo": ["geocodigo", "cod_municipio", "codigo_ibge", "cd_mun", "citycode", "geocod"],
        "ano": ["ano", "year"],
        "classe_codigo": ["classe_codigo", "class_id", "codigo_classe"],
        "classe_nome": ["classe", "class_name", "legenda", "classe_nome"],
        "area_ha": ["area_ha", "area (ha)", "área (ha)", "hectares"],
    }
    colunas_detectadas = {}
    for campo, opcoes in candidatos.items():
        for col in df.columns:
            if str(col).strip().lower() in opcoes:
                colunas_detectadas[campo] = col
                break

    logger.info("Colunas detectadas: %s", colunas_detectadas)
    faltando = [c for c in ("municipio_codigo", "ano", "area_ha") if c not in colunas_detectadas]
    if faltando:
        logger.error(
            "Não foi possível detectar automaticamente as colunas obrigatórias %s. "
            "Colunas disponíveis no arquivo: %s. Ajuste `candidatos` neste script "
            "conforme o cabeçalho real do seu arquivo antes de rodar de novo.",
            faltando, list(df.columns),
        )
        return

    total = 0
    for _, row in df.iterrows():
        try:
            codigo = str(row[colunas_detectadas["municipio_codigo"]])
            ano = int(row[colunas_detectadas["ano"]])
            area_ha = float(row[colunas_detectadas["area_ha"]])
            classe_codigo = int(row[colunas_detectadas["classe_codigo"]]) if "classe_codigo" in colunas_detectadas else None
            nome = str(row[colunas_detectadas["classe_nome"]]) if "classe_nome" in colunas_detectadas else None
            if classe_codigo is None:
                continue
            save_mapbiomas_stat(codigo, ano, classe_codigo, nome, area_ha, "excel_import")
            total += 1
        except Exception as err:
            logger.warning("Linha ignorada na importação do Excel: %s", err)

    logger.info("Importação do Excel concluída: %d linhas salvas.", total)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uf", help="Processa só uma UF (default: todas — cuidado, é lento).")
    parser.add_argument("--anos", help="Anos separados por vírgula, ex. 2004,2024 (default: 2004-2024).")
    parser.add_argument("--credentials", default=os.environ.get("GEE_SERVICE_ACCOUNT_FILE"), help="JSON da conta de serviço do Earth Engine.")
    parser.add_argument("--from-excel", help="Caminho para o Excel oficial de Estatísticas do MapBiomas (caminho alternativo, sem Earth Engine).")
    args = parser.parse_args()

    init_db()

    if args.from_excel:
        importar_excel(args.from_excel)
        return

    if not args.credentials:
        logger.error(
            "Nenhuma credencial do Earth Engine informada (--credentials ou env GEE_SERVICE_ACCOUNT_FILE) "
            "e --from-excel não foi passado. Nada a fazer."
        )
        return

    init_earth_engine(args.credentials)

    ufs = [args.uf.upper()] if args.uf else UFS_BRASIL
    anos = [int(a) for a in args.anos.split(",")] if args.anos else list(range(2004, 2025))
    checkpoint = load_checkpoint()

    for uf in ufs:
        for ano in anos:
            processar_uf_ano_earth_engine(uf, ano, checkpoint)


if __name__ == "__main__":
    main()
