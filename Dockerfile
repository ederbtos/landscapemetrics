# Compila o frontend TypeScript (frontend-src/) para static/app.js e
# static/atlas.js (dois entry points, dois tsconfig — ver tsconfig.json e
# tsconfig.atlas.json, cada um com seu próprio "outFile"). Estágio isolado:
# Node nunca entra na imagem final, só os .js já compilados.
FROM node:20-slim AS frontend-build
WORKDIR /app
COPY package.json package-lock.json tsconfig.json tsconfig.atlas.json ./
COPY frontend-src ./frontend-src
RUN mkdir -p static && npm ci && npm run build

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
COPY --from=frontend-build /app/static/app.js /app/static/app.js
COPY --from=frontend-build /app/static/atlas.js /app/static/atlas.js

EXPOSE 8000

HEALTHCHECK CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
