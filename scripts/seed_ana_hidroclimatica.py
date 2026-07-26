"""
Descrição da funcionalidade
---------------------------
Popula `ana_estacoes`/`ana_serie_historica` (backend/app/db/ana_hidroclimatica.py)
com estações e séries históricas (vazão, nível, chuva) da ANA via
HidroWebService (https://www.ana.gov.br/hidrowebservice).

BLOQUEADO até você ter uma credencial de API da ANA — confirmado ao vivo
nesta sessão que o acesso à API nova exige pedido manual por e-mail a
hidro@ana.gov.br (assunto "Solicitação de acesso à API"; ver manual oficial
em ana.gov.br/hidrowebservice/manual). Isso não é algo que se resolve por
código — é uma ação que só quem opera o projeto pode tomar. Este script fica
pronto para rodar assim que você tiver o token; sem `ANA_API_TOKEN` (ou
`--token`), ele para imediatamente com uma mensagem explicando o bloqueio —
nunca inventa dado de estação/série na ausência de credencial.

Fluxo de autenticação documentado (não implementado como chamada de rede
ainda, pois não há credencial disponível para validar o formato exato da
resposta): `GET /EstacoesTelemetricas/OAUth/v1` com usuário/senha da ANA
retorna um token (`tokenautenticacao`) válido por 60 minutos, usado depois
como header `Authorization: Bearer <token>` nas demais chamadas
(`EstacoesTelemetricas`, `HidroSerieHistorica` — nomes exatos de path a
confirmar no Swagger em ana.gov.br/hidrowebservice/swagger-ui.html quando a
credencial existir).

Uso (só depois de ter a credencial):
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\seed_ana_hidroclimatica.py --token SEU_TOKEN --municipio-codigo 4205407
"""
import argparse
import logging
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.db.schema import init_db  # noqa: E402
# from app.db.ana_hidroclimatica import save_estacao, save_serie_ponto  # descomentar quando implementar as chamadas reais

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HIDROWEBSERVICE_BASE = "https://www.ana.gov.br/hidrowebservice"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", default=os.environ.get("ANA_API_TOKEN"))
    parser.add_argument("--municipio-codigo", help="Restringe a estações de um município (via municipios_malha).")
    args = parser.parse_args()

    init_db()  # garante que as tabelas existem, mesmo sem credencial ainda

    if not args.token:
        logger.error(
            "Sem credencial da ANA (env ANA_API_TOKEN ou --token) — a ingestão real NÃO vai rodar. "
            "Solicite acesso à API por e-mail a hidro@ana.gov.br (assunto "
            "\"Solicitação de acesso à API\", ver ana.gov.br/hidrowebservice/manual). "
            "As tabelas ana_estacoes/ana_serie_historica já existem no banco, prontas para quando "
            "a credencial chegar — implemente as chamadas reais a EstacoesTelemetricas/"
            "HidroSerieHistorica neste script usando o Swagger oficial como referência."
        )
        return

    # TODO (bloqueado): implementar a chamada real assim que houver credencial —
    # 1) POST/GET de autenticação -> token de 60min
    # 2) GET EstacoesTelemetricas -> save_estacao(...) por estação
    # 3) GET HidroSerieHistorica por estação/intervalo -> save_serie_ponto(...) por ponto
    # Reaproveitar o padrão de paginação + checkpoint de scripts/seed_prodes.py
    # se o volume de séries diárias for grande (provável, dado o histórico de 20 anos).
    logger.warning("Credencial informada, mas a chamada real à API HidroWebService ainda não foi implementada neste script.")


if __name__ == "__main__":
    main()
