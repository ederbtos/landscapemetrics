import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from fastapi import HTTPException, Request

import app.api.deps as deps_module


class _FakeSettings:
    def __init__(self, dev_auth_bypass_email):
        self.dev_auth_bypass_email = dev_auth_bypass_email


def _make_request(client_host: str | None) -> Request:
    scope = {
        "type": "http",
        "client": (client_host, 12345) if client_host else None,
        "headers": [],
    }
    return Request(scope)


def test_dev_bypass_activates_from_loopback(monkeypatch):
    monkeypatch.setattr(deps_module, "get_settings", lambda: _FakeSettings("dev@example.com"))
    request = _make_request("127.0.0.1")
    assert deps_module.get_current_user(request, authorization=None) == "dev@example.com"


def test_dev_bypass_does_not_activate_from_non_loopback_client(monkeypatch):
    """Regressão da revisão de segurança (2026-07-30): cookie_secure=false
    sozinho não garante que o host esteja fora da rede — docker-compose.yml
    de dev já roda com cookie_secure=false e publicava a porta. O bypass
    precisa também checar a origem da conexão."""
    monkeypatch.setattr(deps_module, "get_settings", lambda: _FakeSettings("dev@example.com"))
    request = _make_request("203.0.113.5")
    with pytest.raises(HTTPException) as exc_info:
        deps_module.get_current_user(request, authorization=None)
    assert exc_info.value.status_code == 401


def test_no_bypass_configured_requires_real_auth(monkeypatch):
    monkeypatch.setattr(deps_module, "get_settings", lambda: _FakeSettings(None))
    request = _make_request("127.0.0.1")
    with pytest.raises(HTTPException) as exc_info:
        deps_module.get_current_user(request, authorization=None)
    assert exc_info.value.status_code == 401
