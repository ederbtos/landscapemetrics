"""
Rotas para Cálculo e Histórico de Métricas de Paisagem (PyLandStats + MapBiomas + GeoTIFF)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_current_user
from app.db import credentials as credentials_db
from app.db import metric_results as metric_results_db
from app.services import landscape as landscape_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/history")
def list_history(current_user: str = Depends(get_current_user)):
    """Lista as análises salvas no Escritório Virtual do usuário."""
    return metric_results_db.list_metric_results(current_user, full=False)


@router.delete("/history/{fingerprint}")
def delete_history_item(fingerprint: str, current_user: str = Depends(get_current_user)):
    """Remove uma análise salva do histórico do usuário."""
    metric_results_db.delete_metric_result(current_user, fingerprint)
    return {"message": "Análise removida com sucesso!"}


@router.post("/calculate")
async def calculate_metrics(
    data_source: str = Form("mapbiomas"),
    point_lon: Optional[float] = Form(None),
    point_lat: Optional[float] = Form(None),
    buffer_dist: Optional[float] = Form(5000.0),
    municipio_codigo: Optional[str] = Form(None),
    municipio_nome: Optional[str] = Form(None),
    municipio_uf: Optional[str] = Form(None),
    tif_file: Optional[UploadFile] = File(None),
    current_user: str = Depends(get_current_user),
):
    """Calcula as métricas de paisagem (PyLandStats) para o ponto/buffer ou
    município, a partir de dados reais (MapBiomas/Earth Engine ou um GeoTIFF
    próprio enviado) — nunca gera uma análise substituta com dados de
    exemplo se a extração real falhar."""
    tif_bytes = await tif_file.read() if tif_file is not None else None
    tif_filename = tif_file.filename if tif_file is not None else None

    credentials = None
    if data_source == "mapbiomas":
        credentials = credentials_db.get_credentials(current_user)

    try:
        result = landscape_service.run_landscape_analysis(
            data_source=data_source,
            point_lon=point_lon,
            point_lat=point_lat,
            buffer_dist=buffer_dist,
            municipio_codigo=municipio_codigo,
            municipio_nome=municipio_nome,
            municipio_uf=municipio_uf,
            tif_filename=tif_filename,
            tif_bytes=tif_bytes,
            credentials=credentials,
        )
    except landscape_service.LandscapeAnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Erro inesperado no pipeline de métricas: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Não foi possível concluir a análise com dados reais. Detalhes: {exc}",
        ) from exc

    class_metrics_df = result["class_metrics_df"]

    metric_results_db.save_metric_result(
        user_email=current_user,
        fingerprint=result["fingerprint"],
        label=result["label"],
        data_source=data_source,
        point_lonlat=result["point_lonlat"],
        buffer_dist=buffer_dist,
        class_metrics_df=class_metrics_df,
        landscape_metrics=result["landscape_metrics"],
        municipio_codigo=municipio_codigo,
        municipio_nome=municipio_nome,
        municipio_uf=municipio_uf,
        ano=result["ano"],
    )

    return {
        "label": result["label"],
        "fingerprint": result["fingerprint"],
        "ano": result["ano"],
        "class_metrics": class_metrics_df.to_dict(orient="index"),
        "landscape_metrics": result["landscape_metrics"],
    }
