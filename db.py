"""
Descrição da funcionalidade
---------------------------
Persistência das credenciais de conta de serviço do Google Earth Engine, uma
por usuário. Resolve o problema de negócio de eliminar a dependência de uma
única conta de serviço compartilhada (limitada por cota/projeto GCP) — cada
usuário passa a rodar as análises com sua própria cota.

Contexto técnico
-----------------
Camada de acesso a dados do app: SQLite local (arquivo único, sem servidor
de banco separado) em `DB_PATH` (padrão `data/app.db`, path relativo ao
diretório de trabalho do processo — no container é montado como volume via
docker-compose para sobreviver a rebuilds). O e-mail vindo de auth.py é a
chave primária. O JSON da credencial é cifrado em repouso com Fernet
(criptografia simétrica autenticada) antes de tocar o disco. A tabela
`users` guarda as contas do próprio app (login por e-mail/senha, ver
auth.py): senha nunca em texto puro, só o hash bcrypt.

Regras de negócio
------------------
- Cada usuário tem no máximo uma credencial ativa (`INSERT ... ON CONFLICT
  DO UPDATE`): salvar uma nova credencial sempre substitui a anterior, não
  há histórico nem múltiplas contas por usuário.
- A cifra usa uma chave única para todo o app (`app_encryption_key`), não uma
  chave por usuário — qualquer processo com essa chave decifra as credenciais
  de todos os usuários. A chave deve ser tratada com o mesmo cuidado que as
  próprias credenciais do GCP.

Pontos de atenção
------------------
- Perda de `app_encryption_key` torna todas as credenciais salvas
  permanentemente irrecuperáveis (não há mecanismo de rotação de chave ou
  re-criptografia em `save_credentials`).
- `get_credentials` retorna `None` silenciosamente tanto para "usuário nunca
  cadastrou credencial" quanto para "credencial corrompida/chave errada"
  (`InvalidToken`) — do ponto de vista de app.py os dois casos são
  indistinguíveis e levam ao mesmo formulário de cadastro, o que pode
  confundir um usuário que já havia cadastrado credenciais válidas.
- Sem migração de schema: mudanças futuras na tabela exigem lidar com bancos
  `data/app.db` já existentes em produção.

Melhorias sugeridas
---------------------
- Logar (sem vazar o payload) quando `InvalidToken` ocorre, para diferenciar
  "nunca cadastrou" de "credencial corrompida" nos logs de operação.

Cache de métricas já calculadas (`metric_results`)
----------------------------------------------------
Guarda o resultado (valores das métricas, não os pixels/array bruto) de uma
análise já processada, identificada por uma "fingerprint" (ver
`_compute_fingerprint` em app.py) calculada a partir do arquivo enviado (ou,
no caso MapBiomas, do ponto+buffer) — permite que uma resubmissão idêntica
pule a extração (Earth Engine/GeoTIFF) e o PyLandStats por completo. Sempre
escopado por `user_email`: cada usuário só enxerga (lista/lê/apaga) seus
próprios resultados. Se uma métrica nova for adicionada a METRICS_INFO/
LANDSCAPE_METRICS_INFO no futuro e um resultado salvo anteriormente não a
contiver, `get_metric_result` trata isso como cache miss (decisão de
projeto: reprocessar o arquivo inteiro do zero é mais simples e barato em
armazenamento do que também persistir o array bruto só para permitir
recomputar apenas a métrica faltante).
"""
import io
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import bcrypt
import pandas as pd
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "app.db"))


def _get_fernet() -> Fernet:
    key = st.secrets.get("app_encryption_key")
    if not key:
        raise RuntimeError(
            "app_encryption_key não configurado em .streamlit/secrets.toml. "
            "Gere um com: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                email TEXT PRIMARY KEY,
                encrypted_json BLOB NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_results (
                user_email TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                label TEXT NOT NULL,
                data_source TEXT NOT NULL,
                point_lon REAL,
                point_lat REAL,
                buffer_dist REAL,
                class_metrics_json TEXT NOT NULL,
                landscape_metrics_json TEXT NOT NULL,
                metric_names_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_email, fingerprint)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_metric_results_user
            ON metric_results(user_email, created_at)
            """
        )
        conn.commit()


def save_metric_result(
    user_email: str,
    fingerprint: str,
    label: str,
    data_source: str,
    point_lonlat: tuple | None,
    buffer_dist: float | None,
    class_metrics_df,
    landscape_metrics: dict,
) -> None:
    """Salva (ou substitui, se a mesma fingerprint já existir para este
    usuário) o resultado de uma análise já processada. `class_metrics_df` é
    serializado com `to_json(orient="split")` (preserva índice/colunas/tipos
    sem perdas); `metric_names_json` guarda a lista exata de colunas
    presentes, para que `get_metric_result` decida hit/miss sem precisar
    desserializar o DataFrame inteiro."""
    lon, lat = point_lonlat if point_lonlat else (None, None)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            INSERT INTO metric_results (
                user_email, fingerprint, label, data_source,
                point_lon, point_lat, buffer_dist,
                class_metrics_json, landscape_metrics_json, metric_names_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_email, fingerprint) DO UPDATE SET
                label = excluded.label,
                data_source = excluded.data_source,
                point_lon = excluded.point_lon,
                point_lat = excluded.point_lat,
                buffer_dist = excluded.buffer_dist,
                class_metrics_json = excluded.class_metrics_json,
                landscape_metrics_json = excluded.landscape_metrics_json,
                metric_names_json = excluded.metric_names_json,
                created_at = excluded.created_at
            """,
            (
                user_email, fingerprint, label, data_source,
                lon, lat, buffer_dist,
                class_metrics_df.to_json(orient="split"),
                json.dumps(landscape_metrics),
                json.dumps(list(class_metrics_df.columns)),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_metric_result(user_email: str, fingerprint: str, required_metric_names: list) -> dict | None:
    """Retorna o resultado em cache para (user_email, fingerprint), ou None se
    não houver resultado salvo OU se o resultado salvo não contiver todas as
    métricas em `required_metric_names` (ex.: uma métrica nova foi adicionada
    a METRICS_INFO desde que este resultado foi salvo) — nesse caso o
    chamador deve tratar como cache miss e reprocessar o arquivo inteiro (ver
    docstring do módulo)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            """
            SELECT class_metrics_json, landscape_metrics_json, metric_names_json
            FROM metric_results WHERE user_email = ? AND fingerprint = ?
            """,
            (user_email, fingerprint),
        ).fetchone()
    if row is None:
        return None
    class_metrics_json, landscape_metrics_json, metric_names_json = row
    cached_metric_names = set(json.loads(metric_names_json))
    if not set(required_metric_names) <= cached_metric_names:
        return None
    return {
        "class_metrics_df_sub": pd.read_json(io.StringIO(class_metrics_json), orient="split"),
        "landscape_metrics": json.loads(landscape_metrics_json),
    }


def list_metric_results(user_email: str, full: bool = False) -> list:
    """Lista os resultados salvos do usuário, mais recente primeiro — usado
    pelo painel 'Suas análises anteriores'. Por padrão omite os campos JSON
    (podem ser grandes) para manter a listagem barata; passe `full=True` para
    incluí-los (equivalente a chamar `get_metric_result` para cada linha)."""
    columns = "fingerprint, label, data_source, point_lon, point_lat, buffer_dist, created_at"
    if full:
        columns += ", class_metrics_json, landscape_metrics_json, metric_names_json"
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            f"""
            SELECT {columns} FROM metric_results
            WHERE user_email = ? ORDER BY created_at DESC
            """,
            (user_email,),
        ).fetchall()
    col_names = [c.strip() for c in columns.split(",")]
    return [dict(zip(col_names, row)) for row in rows]


def delete_metric_result(user_email: str, fingerprint: str) -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "DELETE FROM metric_results WHERE user_email = ? AND fingerprint = ?",
            (user_email, fingerprint),
        )
        conn.commit()


def create_user(email: str, password: str) -> bool:
    """Cria um usuário novo. Retorna False se o e-mail já estiver cadastrado."""
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    with closing(sqlite3.connect(DB_PATH)) as conn:
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return False
    return True


def verify_user(email: str, password: str) -> bool:
    """Confere e-mail/senha contra o hash salvo."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    if row is None:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), row[0])


def get_credentials(email: str) -> dict | None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT encrypted_json FROM user_credentials WHERE email = ?", (email,)
        ).fetchone()
    if row is None:
        return None
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(row[0])
    except InvalidToken:
        # InvalidToken aqui significa "chave errada/rotacionada" ou "dado
        # corrompido", nunca "usuário não cadastrado" (esse caso já retornou
        # acima). Tratamos como None de propósito para reaproveitar o mesmo
        # formulário de cadastro em app.py, mas isso mascara o problema real
        # do operador do app — ver "Pontos de atenção" no topo do módulo.
        return None
    return json.loads(decrypted.decode("utf-8"))


def save_credentials(email: str, credentials: dict) -> None:
    fernet = _get_fernet()
    encrypted = fernet.encrypt(json.dumps(credentials).encode("utf-8"))
    with closing(sqlite3.connect(DB_PATH)) as conn:
        # Upsert por e-mail: cadastrar uma nova credencial sempre substitui a
        # anterior (sem histórico). Reflete a regra de negócio de "uma
        # credencial GEE ativa por usuário" — ver módulo.
        conn.execute(
            """
            INSERT INTO user_credentials (email, encrypted_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                encrypted_json = excluded.encrypted_json,
                updated_at = excluded.updated_at
            """,
            (email, encrypted, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
