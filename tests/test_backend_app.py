import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
os.environ.setdefault("APP_ENCRYPTION_KEY", "QNwRpxp3-W0L-x3oFw8gbVnBD385_idc8dyJ3mNzFEk=")

from app.main import app


def test_fastapi_app_imports_and_exposes_health_route():
    assert app is not None
    assert any(route.path == "/health" for route in app.routes)
