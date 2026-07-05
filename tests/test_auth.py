"""Testes de auth.py — sessão JWT e validação de e-mail no cadastro."""
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

import auth


def test_email_regex_accepts_valid_emails():
    for email in ["a@b.com", "user.name+tag@example.co.uk", "x@y.io"]:
        assert auth.EMAIL_RE.match(email), email


def test_email_regex_rejects_invalid_emails():
    for email in ["", "sem-arroba.com", "a@b", "a @b.com", "@b.com"]:
        assert not auth.EMAIL_RE.match(email), email


def test_create_token_roundtrips_to_same_email(fake_secrets):
    token = auth._create_token("user@example.com")
    assert auth._decode_token(token) == "user@example.com"


def test_decode_token_rejects_garbage(fake_secrets):
    assert auth._decode_token("isto-nao-e-um-jwt") is None


def test_decode_token_rejects_expired_token(fake_secrets):
    payload = {"email": "user@example.com", "exp": datetime.now(timezone.utc) - timedelta(hours=1)}
    expired = pyjwt.encode(payload, fake_secrets["jwt_secret_key"], algorithm=auth.JWT_ALGORITHM)
    assert auth._decode_token(expired) is None


def test_decode_token_rejects_wrong_signature(fake_secrets):
    payload = {"email": "user@example.com", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    token_signed_by_someone_else = pyjwt.encode(payload, "outra-chave-completamente-diferente", algorithm=auth.JWT_ALGORITHM)
    assert auth._decode_token(token_signed_by_someone_else) is None


def test_get_jwt_secret_missing_raises_clear_error(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(st, "secrets", {})
    with pytest.raises(RuntimeError, match="jwt_secret_key"):
        auth._get_jwt_secret()


def test_is_logged_in_false_without_session(fake_secrets):
    assert auth.is_logged_in() is False


def test_get_current_user_email_raises_without_session(fake_secrets):
    with pytest.raises(RuntimeError):
        auth.get_current_user_email()
