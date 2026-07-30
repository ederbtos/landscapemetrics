"""
Testes de `backend/app/db/users.py` e `backend/app/db/credentials.py` —
cobre principalmente `delete_user`/`delete_credentials`, que faltavam
inteiramente até esta sessão (ver ROADMAP.md): `DELETE /api/lgpd/account`
chamava as duas funções sem que elas existissem, quebrando com
`AttributeError` em produção. Mesmo espírito de isolamento de
`tests/test_backend_db_national.py` (SQLite em `tmp_path`, nunca `data/app.db`
real).
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

for _mod_name in list(sys.modules):
    if _mod_name == "app" or _mod_name.startswith("app."):
        del sys.modules[_mod_name]

import pytest

from app.db import credentials, schema, users


class _FakeSettings:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Precisa ser uma chave Fernet válida de verdade (32 bytes raw,
        # base64 url-safe) — o placeholder legível usado como default em
        # core/config.py NÃO é válido e derrubaria save/get_credentials.
        from cryptography.fernet import Fernet

        self.app_encryption_key = Fernet.generate_key().decode()


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    fake_settings = _FakeSettings(str(tmp_path / "test_auth.db"))
    monkeypatch.setattr(schema, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(users, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(credentials, "get_settings", lambda: fake_settings)
    schema.init_db()
    return fake_settings


# --- users.py ---------------------------------------------------------------


def test_create_and_delete_user_roundtrip(auth_db):
    assert users.create_user("test@example.com", b"hash") is True
    assert users.user_exists("test@example.com") is True

    users.delete_user("test@example.com")

    assert users.user_exists("test@example.com") is False
    assert users.get_password_hash("test@example.com") is None


def test_delete_user_is_noop_for_unknown_email(auth_db):
    # Usuário que só logou via Google nunca tem linha em `users` — deletar a
    # conta não deve levantar erro mesmo assim.
    users.delete_user("never-existed@example.com")


def test_create_user_returns_false_on_duplicate_email(auth_db):
    users.create_user("dup@example.com", b"hash1")
    assert users.create_user("dup@example.com", b"hash2") is False


# --- credentials.py ----------------------------------------------------------


def test_save_and_delete_credentials_roundtrip(auth_db):
    credentials.save_credentials("test@example.com", {"client_email": "svc@example.com"})
    assert credentials.get_credentials("test@example.com") == {"client_email": "svc@example.com"}

    credentials.delete_credentials("test@example.com")

    assert credentials.get_credentials("test@example.com") is None


def test_delete_credentials_is_noop_for_unknown_email(auth_db):
    credentials.delete_credentials("never-existed@example.com")
