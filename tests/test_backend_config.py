import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.core.config import Settings, assert_dev_bypass_is_safe


def test_dev_bypass_with_secure_cookie_refuses_to_start():
    settings = Settings(dev_auth_bypass_email="dev@example.com", cookie_secure=True)
    with pytest.raises(RuntimeError, match="dev_auth_bypass_email"):
        assert_dev_bypass_is_safe(settings)


def test_dev_bypass_with_insecure_cookie_is_allowed():
    settings = Settings(dev_auth_bypass_email="dev@example.com", cookie_secure=False)
    assert_dev_bypass_is_safe(settings)  # não deve levantar


def test_no_bypass_configured_is_always_allowed():
    settings = Settings(dev_auth_bypass_email=None, cookie_secure=True)
    assert_dev_bypass_is_safe(settings)  # não deve levantar
