"""
Serviço para extração de dados climáticos via Google Earth Engine.
Aproveita a mesma inicialização (credentials) já utilizada para o MapBiomas.
"""
import ee
import logging

logger = logging.getLogger(__name__)

def get_precipitation_stats(lon: float, lat: float, buffer_dist: float, year: int = 2023) -> dict:
    """
    Calcula a precipitação pluviométrica (em mm) para o ponto e buffer no ano especificado,
    utilizando a base CHIRPS Daily (Climate Hazards Group InfraRed Precipitation with Station data).
    """
    try:
        # Verifica se o GEE está inicializado
        if not ee.data.is_initialized():
            return {"error": "Earth Engine não inicializado"}

        # Define a região de interesse (Ponto + Buffer circular)
        roi = ee.Geometry.Point([lon, lat]).buffer(buffer_dist)
        
        # Define o período (Ano inteiro)
        start_date = f'{year}-01-01'
        end_date = f'{year}-12-31'
        
        # Filtra a coleção CHIRPS e soma todos os dias do ano para ter o total anual
        chirps = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY') \
                   .filterDate(start_date, end_date) \
                   .select('precipitation')
                   
        total_annual_precip = chirps.sum()
        
        # Reduz (calcula a média dos pixels de precipitação dentro do buffer)
        stats = total_annual_precip.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=roi,
            scale=5566, # Resolução aproximada do CHIRPS (0.05 graus)
            maxPixels=1e9
        )
        
        # Extrai o valor do servidor do GEE para o Python
        val = stats.get('precipitation').getInfo()
        
        return {
            "year": year,
            "total_precipitation_mm": round(val, 2) if val is not None else 0.0,
            "source": "CHIRPS (UCSB-CHG)"
        }
    except Exception as e:
        logger.error(f"Erro ao extrair dados de precipitação CHIRPS: {e}")
        return {"error": str(e)}
