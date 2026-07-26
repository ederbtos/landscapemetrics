import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
os.environ.setdefault("APP_ENCRYPTION_KEY", "dGVzdF9rZXlfZGV2X29ubHlfZm9yX2xvY2FsX3VzZV8xMjM0NQ==")

# Se algum teste anterior (tests/test_app_*.py) já fez `import app` esperando
# o app.py da raiz (Streamlit), sys.modules["app"] fica com esse módulo
# cacheado — Python reaproveita o cache em vez de resolver de novo pelo
# sys.path (que agora tem backend/ na frente), então `from app.main import
# app` abaixo pegaria o app.py errado. Descarta o cache stale antes de
# importar o pacote `app` do backend.
for _mod_name in list(sys.modules):
    if _mod_name == "app" or _mod_name.startswith("app."):
        del sys.modules[_mod_name]

from app.main import app


def test_fastapi_app_imports_and_exposes_health_route():
    assert app is not None
    assert any(route.path == "/health" for route in app.routes)
