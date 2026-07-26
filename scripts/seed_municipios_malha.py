"""
Descrição da funcionalidade
---------------------------
Popula `municipios_malha` (backend/app/db/municipios.py) com a malha
municipal do Brasil inteiro (~5.570 municípios), substituindo a necessidade
de chamar a API do IBGE em tempo real por município. Roda uma vez (ou
quando quiser atualizar/reprocessar).

Contexto técnico
-----------------
A API de malhas do IBGE não tem um endpoint "Brasil inteiro de uma vez" —
confirmado ao vivo nesta sessão: `GET /api/v3/malhas/estados/{uf}` com
`intrarregiao=municipio` já retorna a malha do estado SEGMENTADA por
município (uma feature por `codarea`), então basta iterar as 27 UFs (não os
~5.570 municípios individualmente). O nome de cada município vem de
`/api/v1/localidades/estados/{uf}/municipios` (mesma API já usada em
app.py/ibge.py), casado pelo código.

Segue a mesma regra de "nunca fabricar dado" do resto do projeto: falha ao
buscar a malha de uma UF é logada e a UF é pulada (não interrompe as
demais); nenhuma geometria é inventada. Retomável: por padrão pula
municípios já presentes no banco — use --force para reprocessar tudo.

Uso:
    cd backend && ..\\.venv\\Scripts\\python.exe ..\\scripts\\seed_municipios_malha.py
    (ou --force / --skip-populacao — ver argparse abaixo)
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.db.municipios import all_municipio_codes, count_municipios, save_municipio_malha  # noqa: E402
from app.db.schema import init_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

IBGE_LOCALIDADES_BASE = "https://servicodados.ibge.gov.br/api/v1/localidades"
IBGE_MALHAS_BASE = "https://servicodados.ibge.gov.br/api/v3/malhas"
IBGE_AGREGADOS_BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"
IBGE_REQUEST_TIMEOUT = 30  # malhas por UF são maiores que por município


def fetch_ufs() -> list[dict]:
    resp = requests.get(f"{IBGE_LOCALIDADES_BASE}/estados", params={"orderBy": "nome"}, timeout=IBGE_REQUEST_TIMEOUT)
    resp.raise_for_status()
    return [{"sigla": uf["sigla"], "nome": uf["nome"]} for uf in resp.json()]


def fetch_municipios_da_uf(uf_sigla: str) -> dict:
    """codigo (str) -> nome, via API de localidades (não de malhas)."""
    resp = requests.get(f"{IBGE_LOCALIDADES_BASE}/estados/{uf_sigla}/municipios", timeout=IBGE_REQUEST_TIMEOUT)
    resp.raise_for_status()
    return {str(m["id"]): m["nome"] for m in resp.json()}


def fetch_malha_da_uf(uf_sigla: str) -> dict:
    """FeatureCollection da UF já segmentada por município (`codarea` por feature)."""
    resp = requests.get(
        f"{IBGE_MALHAS_BASE}/estados/{uf_sigla}",
        params={"formato": "application/vnd.geo+json", "qualidade": "minima", "intrarregiao": "municipio"},
        timeout=IBGE_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_populacao_estimada(codigo: str) -> int | None:
    """Melhor esforço — mesma consulta SIDRA de `landscape_core._ibge_get_populacao_estimada`.
    Nunca levanta: se falhar por qualquer motivo, retorna None (a coluna é nullable)."""
    try:
        resp = requests.get(
            f"{IBGE_AGREGADOS_BASE}/6579/periodos/-1/variaveis/9324",
            params={"localidades": f"N6[{codigo}]"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        valor = data[0]["resultados"][0]["series"][0]["serie"]
        (populacao_str,) = valor.values()
        return int(populacao_str)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Reprocessa municípios já presentes no banco.")
    parser.add_argument("--skip-populacao", action="store_true", help="Não busca população estimada (mais rápido).")
    args = parser.parse_args()

    init_db()
    ja_presentes = set() if args.force else set(all_municipio_codes())
    logger.info("Municípios já no banco: %d (será %s)", len(ja_presentes), "reprocessado" if args.force else "pulado")

    ufs = fetch_ufs()
    total_inseridos = 0
    total_pulados = 0
    total_erros = 0

    for uf in ufs:
        sigla = uf["sigla"]
        try:
            nomes_por_codigo = fetch_municipios_da_uf(sigla)
            malha = fetch_malha_da_uf(sigla)
        except requests.RequestException as err:
            logger.error("Falha ao buscar UF %s inteira — pulando esta UF: %s", sigla, err)
            total_erros += 1
            continue

        features = malha.get("features", [])
        logger.info("%s: %d municípios na malha, %d na lista de localidades", sigla, len(features), len(nomes_por_codigo))

        for feature in features:
            codigo = str(feature.get("properties", {}).get("codarea", ""))
            if not codigo:
                continue
            if codigo in ja_presentes:
                total_pulados += 1
                continue

            nome = nomes_por_codigo.get(codigo, f"Município {codigo}")
            geojson_str = json.dumps({"type": "FeatureCollection", "features": [feature]})
            populacao = None if args.skip_populacao else fetch_populacao_estimada(codigo)

            try:
                save_municipio_malha(codigo, nome, sigla, geojson_str, populacao)
                total_inseridos += 1
            except Exception as save_err:
                logger.error("Falha ao salvar município %s (%s/%s): %s", codigo, nome, sigla, save_err)
                total_erros += 1
                continue

            if not args.skip_populacao:
                time.sleep(0.05)  # educado com a API do IBGE (5.570 chamadas de população)

        logger.info("UF %s concluída.", sigla)

    logger.info(
        "Concluído: %d inseridos/atualizados, %d pulados (já presentes), %d erros. Total no banco agora: %d",
        total_inseridos, total_pulados, total_erros, count_municipios(),
    )


if __name__ == "__main__":
    main()
