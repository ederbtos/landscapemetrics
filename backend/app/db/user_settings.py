"""
Descrição da funcionalidade
---------------------------
Preferências individualizadas do Escritório Virtual (Fase 8) — porte de
`db.py::get_user_settings`/`save_user_settings`/`delete_user_settings` (app
Streamlit legado, removido), sem mudança de schema/comportamento (mesma
tabela `user_settings`, mesmos defaults de fábrica quando o usuário nunca
salvou nada).
"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app.core.config import get_settings

_DEFAULT_SETTINGS = {
    "default_buffer_dist": 5000,
    "default_data_source": "mapbiomas",
    "default_uf": "GO",
    "selected_metrics": [
        "proportion_of_landscape",
        "number_of_patches",
        "edge_density",
        "shannon_diversity_index",
    ],
}


def get_user_settings(email: str) -> dict:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute(
            "SELECT settings_json FROM user_settings WHERE user_email = ?", (email,)
        ).fetchone()
    if row is None or not row[0]:
        return dict(_DEFAULT_SETTINGS)
    return json.loads(row[0])


def save_user_settings(email: str, settings_dict: dict) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_email, settings_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_email) DO UPDATE SET
                settings_json = excluded.settings_json,
                updated_at = excluded.updated_at
            """,
            (email, json.dumps(settings_dict), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def delete_user_settings(email: str) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute("DELETE FROM user_settings WHERE user_email = ?", (email,))
        conn.commit()
