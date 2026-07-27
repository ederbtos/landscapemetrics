FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libexpat1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
COPY static /app/static
# Módulos legados na raiz do repo, reaproveitados via importlib/import direto
# por backend/app/services/landscape.py, backend/app/api/routes/sse.py|
# supervised.py|user.py (ver docstrings desses arquivos) — não confundir com
# app.py/auth.py, que dependem do Streamlit e não são usados pelo backend.
COPY landscape_core.py clustering.py supervised_models.py db.py ./

EXPOSE 8000

HEALTHCHECK CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
