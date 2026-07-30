"""
Fixtures compartilhadas da suíte de testes. Ver documentation/13_testing.md
para a estratégia geral.

Correção de ambiente (Windows): se houver uma variável de ambiente PROJ_LIB
global (comum em máquinas com PostgreSQL/PostGIS instalado — o instalador
registra seu próprio proj.db como padrão do sistema), o rasterio deste
projeto tenta abrir esse proj.db com sua própria libproj interna, de versão
incompatível, e qualquer operação de CRS falha com
"DATABASE.LAYOUT.VERSION.MINOR ... whereas a number >= 5 is expected".
Isso não é um bug do código do app — é um conflito de ambiente que também
afetaria a funcionalidade real de upload de GeoTIFF (extract_landscape_from_tif)
se o app rodasse localmente (fora do Docker) nessa mesma máquina. Forçamos
aqui o proj_data que vem empacotado dentro do próprio rasterio, evitando que
a suíte de testes dependa de como o Windows do executor está configurado.
"""
import os
import sys
from pathlib import Path

import rasterio

os.environ["PROJ_LIB"] = str(Path(rasterio.__file__).parent / "proj_data")
os.environ["PROJ_DATA"] = os.environ["PROJ_LIB"]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
