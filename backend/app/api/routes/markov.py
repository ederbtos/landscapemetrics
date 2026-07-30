"""
Rotas para Predição de Anos Futuros via Cadeias de Markov
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_current_user
from app.services import landscape as landscape_service
from app.services import landscape_core

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markov", tags=["markov"])


@router.post("/predict")
async def predict_future_years(
    point_lon: Optional[float] = Form(None),
    point_lat: Optional[float] = Form(None),
    buffer_dist: Optional[float] = Form(5000.0),
    municipio_codigo: Optional[str] = Form(None),
    target_years: str = Form("2030,2040,2050"),
    tif_files: List[UploadFile] = File(...),
    current_user: str = Depends(get_current_user),
):
    """Calcula a matriz de transição a partir de múltiplos GeoTIFFs (de anos
    diferentes) e projeta a proporção das classes para anos futuros."""
    if len(tif_files) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="É necessário enviar pelo menos dois arquivos GeoTIFF para construir a matriz de transição."
        )

    try:
        parsed_target_years = [int(y.strip()) for y in target_years.split(",") if y.strip().isdigit()]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Anos alvo inválidos. Use um formato como '2030,2040,2050'."
        )
        
    if not parsed_target_years:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum ano alvo válido fornecido."
        )

    point_lonlat = (point_lon, point_lat) if point_lon is not None and point_lat is not None else None
    
    municipio_geojson = None
    if municipio_codigo:
        municipio_geojson = landscape_service._get_municipio_geojson_cached(municipio_codigo)
        if municipio_geojson is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Não foi possível obter o limite territorial do município (código {municipio_codigo})."
            )

    class_arrays = []
    years = []
    temp_paths = []
    
    try:
        # Extrai o array de cada arquivo
        for tif_file in tif_files:
            tif_bytes = await tif_file.read()
            uploaded = landscape_service._UploadedFileAdapter(tif_file.filename, tif_bytes)
            
            ano = landscape_core._extract_year_from_filename(tif_file.filename)
            if ano is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Não foi possível identificar o ano no nome do arquivo: {tif_file.filename}. Use um nome como 'meu_raster_2010.tif'."
                )
            years.append(ano)
            
            if municipio_geojson is not None:
                np_arr, res, _reproj = landscape_core.extract_landscape_from_tif(
                    uploaded, region_geojson=municipio_geojson, cleanup=False, temp_path_out=temp_paths
                )
            elif point_lonlat is not None and buffer_dist is not None:
                np_arr, res, _reproj = landscape_core.extract_landscape_from_tif(
                    uploaded, point_lonlat, buffer_dist, cleanup=False, temp_path_out=temp_paths
                )
            else:
                np_arr, res, _reproj = landscape_core.extract_landscape_from_tif(
                    uploaded, cleanup=False, temp_path_out=temp_paths
                )
                
            class_arrays.append(np_arr)

        if len(set(years)) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Os arquivos enviados precisam ser de pelo menos dois anos distintos."
            )

        # Montar a matriz de transição
        transition_df = landscape_core._build_transition_matrix(class_arrays, years)
        
        # Calcular proporções do último ano
        order = sorted(range(len(years)), key=lambda i: years[i])
        last_year = years[order[-1]]
        last_array = class_arrays[order[-1]]
        
        # Ignora valores nulos (geralmente <= 0 ou definidos pelo nodata, assumindo 0 como nodata comum)
        valid_pixels = last_array[last_array > 0]
        if valid_pixels.size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O arquivo do último ano não possui pixels válidos."
            )
            
        unique, counts = np.unique(valid_pixels, return_counts=True)
        total_valid = valid_pixels.size
        last_proportions = {int(k): v / total_valid for k, v in zip(unique, counts)}
        import pandas as pd
        last_proportions_series = pd.Series(last_proportions)
        
        # Intervalo médio histórico
        sorted_years = sorted(years)
        intervals = [sorted_years[i] - sorted_years[i-1] for i in range(1, len(sorted_years))]
        avg_interval = sum(intervals) / len(intervals) if intervals else 1.0

        # Projetar futuro
        prediction_df = landscape_core._project_future_landcover(
            transition_df, last_year, last_proportions_series, avg_interval, parsed_target_years
        )
        
        # Preparar dados do histórico
        history = []
        for y, arr in zip(years, class_arrays):
            v_pix = arr[arr > 0]
            if v_pix.size > 0:
                unq, cnts = np.unique(v_pix, return_counts=True)
                props = {int(k): float(v / v_pix.size) for k, v in zip(unq, cnts)}
                history.append({"ano": y, "proporcoes": props})
        
        # Ordenar histórico
        history = sorted(history, key=lambda x: x["ano"])
        
        return {
            "historico": history,
            "predicoes": prediction_df.to_dict(orient="index"),
            "matriz_transicao": transition_df.to_dict(orient="index"),
            "anos_alvo": parsed_target_years,
            "ultimo_ano_observado": last_year,
            "classes_mapbiomas": landscape_core.MAPBIOMAS_LEGEND_KEYS
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Erro ao processar predição de Markov: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao processar a predição. Detalhes: {exc}"
        ) from exc
    finally:
        for path in temp_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    logger.warning(f"Não foi possível remover arquivo temporário {path}: {e}")
