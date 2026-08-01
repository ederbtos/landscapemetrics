"""
Rota para Métricas por Município em Lote (shapefile de municípios + 1
GeoTIFF próprio -> métricas de fragmentação de TODOS os municípios do
shapefile contra o mesmo raster).

Porte do que existia só em app.py (Streamlit, removido) — `_run_municipio_batch`
nunca tinha sido movido para o backend durante a migração (ver ROADMAP.md).
As funções puras (`_municipio_files_to_gdf`/`_detect_municipio_columns`/
`_clip_raster_at_path`/`_compute_class_metrics`/`_compute_landscape_metrics`)
já vivem em `app.services.landscape_core` — esta rota só orquestra a
persistência (`app.db.metric_results`), no mesmo padrão de
`api/routes/metrics.py`/`markov.py`.

Isolamento de erro por município: diferente da regra de "nunca fabricar
dado" do resto do app (que interrompe todo o processamento se uma extração
falhar), aqui uma falha num município específico (ex.: polígono fora da
extensão do raster) não derruba o lote inteiro — vira uma entrada em
`erros` e o loop segue para o próximo.
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from shapely.geometry import mapping

from app.api.deps import get_current_user
from app.db import metric_results as metric_results_db
from app.services import landscape as landscape_service
from app.services import landscape_core

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/municipio-batch", tags=["municipio-batch"])

MUNICIPIO_BATCH_DATA_SOURCE = "Meu raster (GeoTIFF) — lote municípios"


@router.post("/run")
async def run_municipio_batch(
    municipio_files: List[UploadFile] = File(...),
    tif_file: UploadFile = File(...),
    code_col: Optional[str] = Form(None),
    name_col: Optional[str] = Form(None),
    uf_col: Optional[str] = Form(None),
    force_recompute: bool = Form(False),
    current_user: str = Depends(get_current_user),
):
    """Calcula as métricas de fragmentação (por classe + nível de paisagem)
    de TODOS os municípios do shapefile enviado contra o MESMO GeoTIFF
    enviado. `municipio_files` aceita um único .zip/.geojson OU os
    componentes soltos de um shapefile (.shp+.shx+.dbf+.prj). Reaproveita o
    cache de `metric_results` (mesma fingerprint de `_compute_fingerprint`,
    variando `municipio_codigo`) — uma nova execução do mesmo lote pula os
    municípios já calculados, a menos que `force_recompute` seja true."""
    municipio_uploads = []
    for f in municipio_files:
        content = await f.read()
        municipio_uploads.append(landscape_service._UploadedFileAdapter(f.filename, content))

    try:
        municipios_gdf = landscape_core._municipio_files_to_gdf(municipio_uploads)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    detected = landscape_core._detect_municipio_columns(municipios_gdf)
    code_col = code_col or detected["codigo"]
    name_col = name_col or detected["nome"]
    uf_col = uf_col or detected["uf"]
    if not code_col:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não foi possível identificar a coluna de código do município no shapefile "
                   "enviado — informe explicitamente via 'code_col'.",
        )

    tif_bytes = await tif_file.read()
    uploaded_tif = landscape_service._UploadedFileAdapter(tif_file.filename, tif_bytes)
    temp_paths: list = []
    file_path = landscape_core._save_uploaded_tif_to_temp(uploaded_tif, temp_path_out=temp_paths)

    landscape_rows = []
    class_rows = []
    errors = []

    try:
        total = len(municipios_gdf)
        for i, (_, row) in enumerate(municipios_gdf.iterrows()):
            codigo = str(row[code_col]) if code_col else str(i)
            nome = str(row[name_col]) if name_col else codigo
            uf = str(row[uf_col]) if uf_col else None

            try:
                region_geojson = {
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "properties": {}, "geometry": mapping(row.geometry)}],
                }

                fingerprint = landscape_core._compute_fingerprint(
                    MUNICIPIO_BATCH_DATA_SOURCE, tif_bytes=tif_bytes, municipio_codigo=codigo,
                )
                required_metric_names = [name for name, *_ in landscape_core.METRICS_INFO]
                cached = (
                    None if force_recompute
                    else metric_results_db.get_metric_result(current_user, fingerprint, required_metric_names)
                )

                if cached is not None:
                    class_metrics_df_sub = cached["class_metrics_df_sub"]
                    landscape_metrics = cached["landscape_metrics"]
                else:
                    array, resolution, _ = landscape_core._clip_raster_at_path(
                        file_path, region_geojson=region_geojson, want_reprojected_bytes=False,
                    )
                    ls, class_metrics_df_sub = landscape_core._compute_class_metrics(array, resolution)
                    landscape_metrics = landscape_core._compute_landscape_metrics(ls)
                    metric_results_db.save_metric_result(
                        user_email=current_user,
                        fingerprint=fingerprint,
                        label=f"{nome}/{uf} (lote)" if uf else f"{nome} (lote)",
                        data_source=MUNICIPIO_BATCH_DATA_SOURCE,
                        point_lonlat=None,
                        buffer_dist=None,
                        class_metrics_df=class_metrics_df_sub,
                        landscape_metrics=landscape_metrics,
                        municipio_codigo=codigo,
                        municipio_nome=nome,
                        municipio_uf=uf,
                    )
            except Exception as row_error:
                logger.warning(f"Falha ao processar município {nome} ({codigo}): {row_error}")
                errors.append({
                    "municipio_codigo": codigo, "municipio_nome": nome, "municipio_uf": uf,
                    "erro": str(row_error),
                })
                continue

            landscape_row = {"municipio_codigo": codigo, "municipio_nome": nome, "municipio_uf": uf}
            for metric_name, *_ in landscape_core.LANDSCAPE_METRICS_INFO:
                landscape_row[metric_name] = landscape_metrics.get(metric_name)
            landscape_rows.append(landscape_row)

            class_df_reset = class_metrics_df_sub.reset_index().rename(columns={"index": "classe"})
            for _, class_row_series in class_df_reset.iterrows():
                class_row = {"municipio_codigo": codigo, "municipio_nome": nome, "municipio_uf": uf}
                class_row.update(class_row_series.to_dict())
                class_rows.append(class_row)
    finally:
        for path in temp_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as cleanup_error:
                    logger.warning(f"Erro ao limpar arquivo temporário {path}: {cleanup_error}")

    return landscape_core.sanitize_for_json({
        "total_municipios": total,
        "sucesso": len(landscape_rows),
        "erros": errors,
        "colunas_detectadas": {"codigo": code_col, "nome": name_col, "uf": uf_col},
        "landscape_rows": landscape_rows,
        "class_rows": class_rows,
        # Envelope do pipeline (wizard do frontend) — aditivo.
        "step": "municipio_batch_completed",
        "next_available_actions": ["cluster", "export"],
    })
