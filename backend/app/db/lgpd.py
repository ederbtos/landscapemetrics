"""
Persistência da trilha de auditoria e consentimento (LGPD).
"""
import sqlite3
from contextlib import closing

from app.core.config import get_settings

def save_consent(user_email: str, term_version: str, client_ip: str, user_agent: str, consent_hash: str, timestamp_utc: str) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO lgpd_consents 
            (user_email, term_version, client_ip, user_agent, consent_hash, timestamp_utc)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_email, term_version, client_ip, user_agent, consent_hash, timestamp_utc)
        )
        conn.commit()

def get_user_consent(user_email: str, term_version: str) -> dict | None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute(
            """
            SELECT user_email, term_version, client_ip, user_agent, consent_hash, timestamp_utc 
            FROM lgpd_consents WHERE user_email = ? AND term_version = ?
            """, 
            (user_email, term_version)
        ).fetchone()
        
    if row:
        return {
            "user_email": row[0],
            "term_version": row[1],
            "client_ip": row[2],
            "user_agent": row[3],
            "consent_hash": row[4],
            "timestamp_utc": row[5]
        }
    return None
