"""
Descrição da funcionalidade
---------------------------
Popula `ana_estacoes`/`ana_serie_historica` (backend/app/db/ana_hidroclimatica.py)
com estações e série telemétrica da ANA via HidroWebService
(https://www.ana.gov.br/hidrowebservice).

Contexto técnico
-----------------
Implementado a partir do manual oficial ("Tutorial de Serviço para Consumo de
Dados – API HidroWebService", versão 20.02.2026, baixado de
ana.gov.br/hidrowebservice/manual) — a única fonte usada, nenhum campo/rota
foi adivinhado.

**Achado importante, mudando a expectativa da tabela `ana_serie_historica`**:
o manual só documenta rotas sob "WS-EstacoesTelemetricasController"
(descrito no próprio manual como mostrando "todas as rotas disponíveis"), e
a única rota de série documentada com exemplo real
(`HidroinfoanaSerieTelemetricaAdotada/v1`) é telemétrica de curto prazo —
filtra por uma janela relativa (`RangeIntervaloDeBusca`, só o valor
`DIAS_30` aparece confirmado no manual), não uma série histórica de décadas.
Ou seja, esta ingestão traz dado real e recente (a janela pedida em
`--range-intervalo`), não um backfill de 20 anos — se a ANA tiver uma rota
separada para estações convencionais/histórico longo, ela não aparece neste
manual; verifique ao vivo em
https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html se precisar
disso.

Autenticação (seção 2 do manual): `GET .../EstacoesTelemetricas/OAUth/v1`
com headers `Identificador` (CPF/CNPJ cadastrado) e `Senha`, devolve
`items.tokenautenticacao`, válido por 60 minutos — `TokenManager` abaixo
renova um pouco antes disso (55 min) para nunca usar um token expirado no
meio de um lote grande.

Município: o próprio inventário da ANA traz um campo `Municipio_Codigo`,
mas é um código interno da ANA (ex.: "1010000" para Porto Velho), **não**
o código IBGE de 7 dígitos usado no resto deste projeto (`municipios_malha`,
PRODES, MapBiomas) — usá-lo diretamente quebraria qualquer join futuro.
Por isso o município é resolvido por junção espacial (ponto lat/lon da
estação dentro do polígono do município, mesmo padrão de
`scripts/seed_prodes.py` via `shapely.strtree.STRtree`) — requer
`scripts/seed_municipios_malha.py` já ter rodado; sem isso, ou se a estação
cair fora de qualquer polígono cacheado, o campo fica `NULL` (nunca um
palpite).

Credencial: pedida por e-mail a hidro@ana.gov.br (CPF/CNPJ vira o
"identificador", a senha chega por e-mail — ver seção 1.1 do manual). Nunca
passe a senha como argumento de linha de comando em um ambiente
compartilhado (fica no histórico do shell) — prefira as variáveis de
ambiente `ANA_IDENTIFICADOR`/`ANA_SENHA`.

Uso:
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\seed_ana_hidroclimatica.py --limit-estacoes 20 --municipio-codigo 4205407
    (com ANA_IDENTIFICADOR/ANA_SENHA no ambiente; --limit-estacoes e
    --municipio-codigo são só para um piloto pequeno antes do lote completo)
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

import requests  # noqa: E402

from app.db.ana_hidroclimatica import save_estacao, save_serie_ponto  # noqa: E402
from app.db.municipios import all_municipio_codes, get_municipio_malha  # noqa: E402
from app.db.schema import init_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

HIDRO_BASE = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas"
TOKEN_TTL_SECONDS = 55 * 60  # manual diz 60min de validade — renova um pouco antes


class TokenManager:
    """Obtém e renova o `tokenautenticacao` sob demanda (seção 2 do manual) —
    evita re-autenticar em toda chamada (o manual avisa que autenticação em
    alta frequência pode levar ao bloqueio automático do IP)."""

    def __init__(self, identificador: str, senha: str):
        self.identificador = identificador
        self.senha = senha
        self._token: str | None = None
        self._obtained_at: float | None = None

    def get(self) -> str:
        if self._token is None or (time.monotonic() - self._obtained_at) > TOKEN_TTL_SECONDS:
            resp = requests.get(
                f"{HIDRO_BASE}/OAUth/v1",
                headers={"Identificador": self.identificador, "Senha": self.senha},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            token = (data.get("items") or {}).get("tokenautenticacao")
            if not token:
                raise RuntimeError(f"Autenticação na ANA não retornou tokenautenticacao: {data}")
            self._token = token
            self._obtained_at = time.monotonic()
            logger.info("Novo token ANA obtido (válido por até 60 min).")
        return self._token


def _parse_float(value) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_municipio_index():
    """STRtree dos polígonos de município + lista paralela de códigos IBGE —
    mesmo padrão de `scripts/seed_prodes.py::build_municipio_index`."""
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    codigos = all_municipio_codes()
    if not codigos:
        logger.warning("municipios_malha está vazia — rode seed_municipios_malha.py antes para ter o join espacial.")
        return None, [], []

    geoms = []
    codigos_validos = []
    for codigo in codigos:
        row = get_municipio_malha(codigo)
        try:
            feature = json.loads(row["geojson"])["features"][0]
            geoms.append(shape(feature["geometry"]))
            codigos_validos.append(codigo)
        except Exception as err:
            logger.warning("Geometria inválida para município %s, ignorado no join espacial: %s", codigo, err)

    logger.info("Índice espacial construído com %d municípios.", len(geoms))
    return STRtree(geoms), geoms, codigos_validos


def resolver_municipio(tree, geoms, codigos, ponto) -> str | None:
    if tree is None:
        return None
    for idx in tree.query(ponto):
        if geoms[idx].contains(ponto):
            return codigos[idx]
    return None


def fetch_inventario(token_mgr: TokenManager) -> list[dict]:
    resp = requests.get(
        f"{HIDRO_BASE}/HidroInventarioEstacoes/v1",
        headers={"Authorization": f"Bearer {token_mgr.get()}"},
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("items") or []


def fetch_serie_adotada(token_mgr: TokenManager, codigo_estacao: str, range_intervalo: str) -> list[dict]:
    resp = requests.get(
        f"{HIDRO_BASE}/HidroinfoanaSerieTelemetricaAdotada/v1",
        params={
            "CodigoDaEstacao": codigo_estacao,
            "TipoFiltroData": "DATA_LEITURA",
            "RangeIntervaloDeBusca": range_intervalo,
        },
        headers={"Authorization": f"Bearer {token_mgr.get()}"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("items") or []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--identificador", default=os.environ.get("ANA_IDENTIFICADOR"), help="CPF/CNPJ cadastrado na ANA (ou env ANA_IDENTIFICADOR).")
    parser.add_argument("--senha", default=os.environ.get("ANA_SENHA"), help="Senha recebida por e-mail da ANA (ou env ANA_SENHA — prefira o env var).")
    parser.add_argument("--municipio-codigo", help="Restringe às estações cujo ponto caiu neste código IBGE (piloto).")
    parser.add_argument("--limit-estacoes", type=int, default=None, help="Processa só as N primeiras estações do inventário (piloto/teste).")
    parser.add_argument("--so-inventario", action="store_true", help="Só salva o inventário de estações, sem buscar série.")
    parser.add_argument(
        "--range-intervalo", default="DIAS_30",
        help="Janela relativa da série telemétrica adotada. Só 'DIAS_30' está confirmado no manual oficial — "
             "outras opções do dropdown do Swagger (se existirem) não foram validadas aqui.",
    )
    args = parser.parse_args()

    init_db()

    if not args.identificador or not args.senha:
        logger.error(
            "Sem credencial da ANA (--identificador/--senha ou env ANA_IDENTIFICADOR/ANA_SENHA) — "
            "a ingestão real NÃO vai rodar. Ver seção 1.1 do manual oficial para solicitar acesso "
            "(e-mail a hidro@ana.gov.br)."
        )
        return

    token_mgr = TokenManager(args.identificador, args.senha)
    tree, geoms, codigos = build_municipio_index()

    logger.info("Buscando inventário de estações telemétricas da ANA...")
    try:
        itens = fetch_inventario(token_mgr)
    except requests.RequestException as err:
        logger.error("Falha ao buscar o inventário de estações: %s", err)
        return

    logger.info("%d estações retornadas pelo inventário.", len(itens))
    if not itens:
        logger.warning(
            "Inventário veio vazio — confira ao vivo em "
            "https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html (HidroInventarioEstacoes/v1) "
            "se essa rota exige algum filtro obrigatório não documentado no manual."
        )

    from shapely.geometry import Point

    estacoes_processadas: list[str] = []
    for item in itens:
        codigo = item.get("codigoestacao")
        if not codigo:
            continue

        lat = _parse_float(item.get("Latitude"))
        lon = _parse_float(item.get("Longitude"))

        municipio_codigo = None
        if tree is not None and lat is not None and lon is not None:
            municipio_codigo = resolver_municipio(tree, geoms, codigos, Point(lon, lat))

        if args.municipio_codigo and municipio_codigo != args.municipio_codigo:
            continue

        try:
            save_estacao(
                codigo=codigo,
                nome=item.get("Estacao_Nome"),
                lat=lat,
                lon=lon,
                uf=item.get("UF_Estacao"),
                municipio_codigo=municipio_codigo,
                tipo=item.get("Tipo_Estacao"),
            )
        except Exception as err:
            logger.warning("Erro ao salvar estação %s: %s", codigo, err)
            continue

        estacoes_processadas.append(codigo)
        if args.limit_estacoes and len(estacoes_processadas) >= args.limit_estacoes:
            logger.info("Limite de %d estações atingido (--limit-estacoes).", args.limit_estacoes)
            break

    logger.info("%d estações salvas em ana_estacoes.", len(estacoes_processadas))

    if args.so_inventario:
        logger.info("--so-inventario: pulando busca de série telemétrica.")
        return

    total_pontos = 0
    total_erros = 0
    for i, codigo in enumerate(estacoes_processadas):
        try:
            pontos = fetch_serie_adotada(token_mgr, codigo, args.range_intervalo)
        except requests.RequestException as err:
            total_erros += 1
            logger.warning("Falha ao buscar série da estação %s: %s", codigo, err)
            continue

        for ponto in pontos:
            try:
                save_serie_ponto(
                    estacao_codigo=codigo,
                    data=ponto.get("Data_Hora_Medicao"),
                    vazao_m3s=_parse_float(ponto.get("Vazao_Adotada")),
                    nivel_cm=_parse_float(ponto.get("Cota_Adotada")),
                    chuva_mm=_parse_float(ponto.get("Chuva_Adotada")),
                    consistencia=(
                        f"chuva={ponto.get('Chuva_Adotada_Status')};"
                        f"cota={ponto.get('Cota_Adotada_Status')};"
                        f"vazao={ponto.get('Vazao_Adotada_Status')}"
                    ),
                )
                total_pontos += 1
            except Exception as err:
                total_erros += 1
                logger.warning("Erro ao salvar ponto da série (estação %s): %s", codigo, err)

        if (i + 1) % 50 == 0:
            logger.info("Série: %d/%d estações processadas até agora (%d pontos salvos).", i + 1, len(estacoes_processadas), total_pontos)
        time.sleep(0.2)  # cortesia com a API — evita rajada de milhares de GETs

    logger.info("Série telemétrica: %d pontos salvos, %d erros.", total_pontos, total_erros)


if __name__ == "__main__":
    main()
