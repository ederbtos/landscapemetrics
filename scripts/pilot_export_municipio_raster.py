"""
Descrição da funcionalidade
---------------------------
Piloto da Fase 1 do Atlas Nacional de Paisagem: prova, para UM único
município, o pipeline de extração REAL de pixels do MapBiomas via
`ee.batch.Export.image.toCloudStorage` — algo nunca tentado neste projeto.

Por que isso existe (ver ROADMAP.md/plano da Fase 1): a extração de pixels
usada hoje em `landscape.py::_extract_mapbiomas_pixels` (`sampleRectangle`,
limite de ~262.144 pixels (~15x15 km a 30m); ou o fallback `reduceRegion` +
`Reducer.toList()`, que NÃO preserva a geometria real do raster) só serve
para pontos+buffer pequenos — não para um município inteiro, necessário
para calcular métricas de fragmentação de verdade (densidade de manchas,
borda, forma, área central), que dependem da adjacência real dos pixels.

Fluxo deste script:
1. Resolve a geometria do município via o cache já existente
   (`app.db.municipios.get_municipio_malha` — não chama a API do IBGE).
2. Encontra o asset/banda do MapBiomas para o ano pedido (mesma lista de
   fallback de `seed_mapbiomas_stats.py`/`landscape.py`).
3. Submete um `Export.image.toCloudStorage` recortado (`.clip()` +
   `region=`) para o bucket informado, e faz polling do status da task até
   completar — SEM engolir falha em `except Exception: continue` (foi
   exatamente esse padrão, em `seed_mapbiomas_stats.py`/`landscape.py`, que
   mascarou uma queda de rede como "asset indisponível" na carga nacional
   documentada no ROADMAP.md; aqui cada estado da task aparece explícito).
4. Baixa o GeoTIFF resultante do bucket.
5. Alimenta o arquivo no pipeline JÁ EXISTENTE de GeoTIFF próprio
   (`landscape_core._clip_raster_at_path` -> `_compute_class_metrics` ->
   `_compute_landscape_metrics`) — as MESMAS ~19 métricas usadas em todo o
   resto do app, incluindo as de fragmentação que a Fase 0 (diversidade,
   `diversity_atlas_municipio`) não cobre.

NÃO grava nada em banco — só imprime o resultado. É um piloto para validar
permissão de export + números plausíveis antes de desenhar a orquestração
em lote para os ~5.570 municípios (Fase 1 "de verdade").

Pré-requisito manual (feito uma vez, fora deste script, no console/gcloud
do GCP — ver plano): o bucket já precisa existir e a conta de serviço
precisa ter `roles/storage.objectAdmin` nele.

Uso:
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\pilot_export_municipio_raster.py \\
        --municipio 4209300 --bucket landscapemetrics-atlas-pilot \\
        --credentials caminho\\service_account.json
"""
import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.municipios import get_municipio_malha  # noqa: E402
from app.db.schema import init_db  # noqa: E402
from app.services import landscape_core  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Mesma lista de fallback usada em landscape.py::_extract_mapbiomas_pixels
# e seed_mapbiomas_stats.py::MAPBIOMAS_ASSETS — duplicada aqui de propósito
# (terceira cópia): um módulo compartilhado só para esta lista de 4 strings
# não paga o preço de mais uma dependência cruzada entre scripts/ e
# backend/app/ neste momento.
MAPBIOMAS_ASSETS = [
    "projects/mapbiomas-public/assets/brazil/lulc/collection9/mapbiomas_collection90_integration_v1",
    "projects/mapbiomas-public/assets/brazil/lulc/collection8/mapbiomas_collection80_integration_v1",
    "projects/mapbiomas-workspace/public/collection7/mapbiomas_collection70_integration_v2",
    "projects/mapbiomas-workspace/public/collection6/mapbiomas_collection60_integration_v1",
]

DEFAULT_POLL_INTERVAL_SECONDS = 15
DEFAULT_TIMEOUT_MINUTES = 30


def load_credentials(path: str | None) -> dict:
    path = path or os.environ.get("GEE_SERVICE_ACCOUNT_FILE")
    if not path:
        raise SystemExit(
            "Nenhuma credencial informada — use --credentials <arquivo.json> "
            "ou defina GEE_SERVICE_ACCOUNT_FILE."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def init_earth_engine(credentials: dict) -> None:
    import ee

    ee_credentials = ee.ServiceAccountCredentials(
        credentials.get("client_email"), key_data=json.dumps(credentials)
    )
    ee.Initialize(credentials=ee_credentials, opt_url="https://earthengine-highvolume.googleapis.com")


def pick_asset_and_band(ano: int | None) -> tuple:
    """Retorna (ee.Image, banda, ano_efetivo). Se `ano` for None, usa o ano
    mais recente disponível no primeiro asset que responder. Levanta
    RuntimeError explícito se nenhum asset tiver a banda pedida — nunca
    segue adiante com um asset/ano incerto."""
    import ee

    for asset in MAPBIOMAS_ASSETS:
        try:
            image = ee.Image(asset)
            bands = image.bandNames().getInfo()
        except Exception as asset_error:
            logger.warning("Falha ao consultar asset %s (%s) — tentando o próximo.", asset, asset_error)
            continue

        anos_disponiveis = sorted(
            int(b.replace("classification_", "")) for b in bands
            if b.startswith("classification_") and b.replace("classification_", "").isdigit()
        )
        if not anos_disponiveis:
            continue

        ano_efetivo = ano if ano is not None else anos_disponiveis[-1]
        banda = f"classification_{ano_efetivo}"
        if banda in bands:
            return image, banda, ano_efetivo
        logger.info("Asset %s não tem a banda %s — tentando o próximo.", asset, banda)

    raise RuntimeError(f"Nenhum asset MapBiomas tem uma banda para o ano {ano} nas coleções conhecidas.")


def submit_export(image, ee_geom, bucket: str, codigo: str, ano: int):
    import ee

    prefix = f"atlas_pilot/{codigo}_{ano}"
    task = ee.batch.Export.image.toCloudStorage(
        image=image.clip(ee_geom),
        description=f"atlas_pilot_{codigo}_{ano}"[:100],
        bucket=bucket,
        fileNamePrefix=prefix,
        region=ee_geom,
        scale=30,
        crs="EPSG:4326",
        maxPixels=1_000_000_000,
        fileFormat="GeoTIFF",
    )
    task.start()
    logger.info("Task de export submetida (id=%s) — prefixo no bucket: %s", task.id, prefix)
    return task, prefix


def wait_for_export(task, poll_interval: int, timeout_minutes: int) -> None:
    """Faz polling do status da task até COMPLETED/FAILED/CANCELLED — cada
    estado é logado explicitamente, e uma falha real (`FAILED`) interrompe
    com a mensagem de erro do próprio Earth Engine, nunca é tratada como
    'seguir para o próximo' (ver docstring do módulo)."""
    started_at = time.monotonic()
    timeout_seconds = timeout_minutes * 60

    while True:
        status = task.status()
        state = status.get("state")
        logger.info("Status da task: %s", state)

        if state == "COMPLETED":
            return
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Export {state.lower()}: {status.get('error_message', 'sem detalhes do Earth Engine')}")

        if time.monotonic() - started_at > timeout_seconds:
            raise RuntimeError(
                f"Timeout de {timeout_minutes}min esperando o export terminar (último estado: {state}). "
                "A task pode continuar rodando no Earth Engine — confira no console."
            )
        time.sleep(poll_interval)


def download_export(credentials: dict, bucket: str, prefix: str, out_dir: str) -> str:
    """Baixa o(s) objeto(s) exportado(s) para `out_dir` e retorna o caminho
    do primeiro `.tif` encontrado. Levanta se nada foi encontrado — nunca
    segue adiante sem o raster real."""
    from google.cloud import storage
    from google.oauth2 import service_account

    gcs_credentials = service_account.Credentials.from_service_account_info(credentials)
    client = storage.Client(credentials=gcs_credentials, project=credentials.get("project_id"))

    blobs = list(client.list_blobs(bucket, prefix=prefix))
    tif_blobs = [b for b in blobs if b.name.endswith(".tif")]
    if not tif_blobs:
        raise RuntimeError(
            f"Nenhum .tif encontrado em gs://{bucket}/{prefix} — o export completou mas "
            "não achei o arquivo esperado. Confira o bucket manualmente."
        )
    if len(tif_blobs) > 1:
        logger.warning(
            "Export saiu em %d arquivos (imagem grande, GEE fatiou) — baixando só o primeiro (%s). "
            "Para um piloto de 1 município isso não deveria acontecer; investigue se ocorrer.",
            len(tif_blobs), tif_blobs[0].name,
        )

    local_path = os.path.join(out_dir, os.path.basename(tif_blobs[0].name))
    tif_blobs[0].download_to_filename(local_path)
    logger.info("Baixado: gs://%s/%s -> %s (%.1f MB)", bucket, tif_blobs[0].name, local_path, tif_blobs[0].size / 1e6)
    return local_path


def main() -> None:
    # cwd só é forçado para backend/ na execução direta como script — nunca
    # ao importar este módulo, para não repetir o vazamento de cwd descrito
    # em scripts/build_diversity_atlas.py::main() (achado ao investigar uma
    # falha de teste em outro módulo que também troca cwd no import).
    os.chdir(BACKEND_DIR)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--municipio", required=True, help="Código IBGE do município (ver /api/ibge/... ou municipios_malha).")
    parser.add_argument("--ano", type=int, default=None, help="Ano da classificação MapBiomas (default: mais recente disponível).")
    parser.add_argument("--bucket", required=True, help="Nome do bucket GCS (já criado, com permissão à conta de serviço).")
    parser.add_argument("--credentials", default=os.environ.get("GEE_SERVICE_ACCOUNT_FILE"), help="JSON da conta de serviço do Earth Engine.")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS, help="Segundos entre checagens do status do export.")
    parser.add_argument("--timeout-minutes", type=int, default=DEFAULT_TIMEOUT_MINUTES, help="Tempo máximo esperando o export terminar.")
    parser.add_argument("--out-dir", default=None, help="Onde salvar o GeoTIFF baixado (default: pasta temporária do sistema).")
    args = parser.parse_args()

    init_db()

    municipio_row = get_municipio_malha(args.municipio)
    if municipio_row is None:
        raise SystemExit(
            f"Município {args.municipio!r} não está em municipios_malha — rode "
            "scripts/seed_municipios_malha.py primeiro (ou confira o código)."
        )
    municipio_geojson = json.loads(municipio_row["geojson"])
    logger.info("Município: %s/%s (%s)", municipio_row["nome"], municipio_row["uf"], args.municipio)

    credentials = load_credentials(args.credentials)
    init_earth_engine(credentials)

    import ee
    from shapely.geometry import mapping

    geom_shapely = landscape_core._municipio_geometry_shapely(municipio_geojson)
    ee_geom = ee.Geometry(mapping(geom_shapely))

    image, banda, ano_efetivo = pick_asset_and_band(args.ano)
    logger.info("Banda escolhida: %s", banda)

    task, prefix = submit_export(image.select(banda), ee_geom, args.bucket, args.municipio, ano_efetivo)
    wait_for_export(task, args.poll_interval, args.timeout_minutes)

    out_dir = args.out_dir or tempfile.mkdtemp(prefix="atlas_pilot_")
    os.makedirs(out_dir, exist_ok=True)
    local_tif = download_export(credentials, args.bucket, prefix, out_dir)

    array, resolution, _ = landscape_core._clip_raster_at_path(
        local_tif, region_geojson=municipio_geojson, want_reprojected_bytes=False,
    )
    logger.info("Raster baixado e recortado: shape=%s, resolução=%s", array.shape, resolution)

    ls, class_metrics_df = landscape_core._compute_class_metrics(array, resolution)
    landscape_metrics = landscape_core._compute_landscape_metrics(ls)

    print("\n=== Métricas por classe ===")
    print(class_metrics_df.to_string())
    print("\n=== Métricas de paisagem (inclui fragmentação — patch_density, edge_density, landscape_shape_index) ===")
    for key, value in landscape_metrics.items():
        print(f"  {key}: {value}")
    print(f"\nRaster baixado em: {local_tif}")


if __name__ == "__main__":
    main()
