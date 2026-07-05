"""Testes de db.py — regras de negócio documentadas em documentation/09_business_rules.md."""
import pytest


def test_create_user_success(temp_db):
    assert temp_db.create_user("user@example.com", "senha12345") is True


def test_create_user_duplicate_email_returns_false(temp_db):
    temp_db.create_user("user@example.com", "senha12345")
    assert temp_db.create_user("user@example.com", "outra-senha") is False


def test_create_user_never_stores_plaintext_password(temp_db):
    temp_db.create_user("user@example.com", "senha12345")
    import sqlite3

    with sqlite3.connect(temp_db.DB_PATH) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", ("user@example.com",)
        ).fetchone()
    assert b"senha12345" not in row[0]


def test_verify_user_correct_password(temp_db):
    temp_db.create_user("user@example.com", "senha12345")
    assert temp_db.verify_user("user@example.com", "senha12345") is True


def test_verify_user_wrong_password(temp_db):
    temp_db.create_user("user@example.com", "senha12345")
    assert temp_db.verify_user("user@example.com", "senha-errada") is False


def test_verify_user_nonexistent_email(temp_db):
    assert temp_db.verify_user("ninguem@example.com", "qualquer") is False


def test_get_credentials_returns_none_when_never_registered(temp_db, fake_secrets):
    assert temp_db.get_credentials("user@example.com") is None


def test_save_and_get_credentials_roundtrip(temp_db, fake_secrets):
    creds = {
        "client_email": "svc@project.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
        "project_id": "my-gcp-project",
    }
    temp_db.save_credentials("user@example.com", creds)
    assert temp_db.get_credentials("user@example.com") == creds


def test_save_credentials_upsert_replaces_previous(temp_db, fake_secrets):
    temp_db.save_credentials("user@example.com", {"client_email": "old", "private_key": "x", "project_id": "p"})
    temp_db.save_credentials("user@example.com", {"client_email": "new", "private_key": "y", "project_id": "p"})
    result = temp_db.get_credentials("user@example.com")
    assert result["client_email"] == "new"


def test_credentials_are_encrypted_at_rest(temp_db, fake_secrets):
    creds = {"client_email": "svc@x.iam.gserviceaccount.com", "private_key": "SECRET_KEY_MATERIAL", "project_id": "p"}
    temp_db.save_credentials("user@example.com", creds)

    import sqlite3

    with sqlite3.connect(temp_db.DB_PATH) as conn:
        row = conn.execute(
            "SELECT encrypted_json FROM user_credentials WHERE email = ?", ("user@example.com",)
        ).fetchone()
    assert b"SECRET_KEY_MATERIAL" not in row[0]


def test_get_credentials_wrong_encryption_key_returns_none(temp_db, fake_secrets):
    """InvalidToken (chave errada/dado corrompido) é tratado como 'sem credencial' —
    comportamento documentado (e sua limitação) em documentation/04_database.md."""
    import streamlit as st
    from cryptography.fernet import Fernet

    temp_db.save_credentials("user@example.com", {"client_email": "a", "private_key": "b", "project_id": "c"})

    st.secrets = {**fake_secrets, "app_encryption_key": Fernet.generate_key().decode()}
    assert temp_db.get_credentials("user@example.com") is None
