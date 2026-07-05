#!/usr/bin/env bash
set -euo pipefail

# Deploy da Fase 4 em um VPS com Docker: sobe app + Caddy (HTTPS automático
# via Let's Encrypt) com um único comando. Rode este script DENTRO do
# servidor de produção, na raiz do repositório.
#
# Pré-requisitos (únicas decisões que ainda cabem a quem hospeda):
#   1. Domínio com registro DNS tipo A apontando para o IP deste servidor.
#   2. Portas 80/443 liberadas no firewall.
#   3. .streamlit/secrets.toml já configurado (copie de
#      .streamlit/secrets.toml.example) com jwt_secret_key e app_encryption_key.
#
# Uso: ./scripts/deploy.sh seu-dominio.exemplo.com

DOMAIN="${1:-}"

if [[ -z "$DOMAIN" ]]; then
  echo "Uso: $0 <dominio>" >&2
  echo "Ex.:  $0 app.exemplo.com" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker não encontrado neste servidor. Instale o Docker (e o plugin compose) antes de continuar." >&2
  exit 1
fi

if [[ ! -f .streamlit/secrets.toml ]]; then
  echo "Faltando .streamlit/secrets.toml. Copie de .streamlit/secrets.toml.example e preencha jwt_secret_key + app_encryption_key antes de rodar este script." >&2
  exit 1
fi

if [[ -f Caddyfile ]]; then
  echo "Caddyfile já existe — não sobrescrevendo (edite manualmente se o domínio mudou)."
else
  echo "Gerando Caddyfile para $DOMAIN a partir de Caddyfile.example..."
  sed "s/seu-dominio.exemplo.com/$DOMAIN/" Caddyfile.example > Caddyfile
fi

mkdir -p data

echo "Subindo stack de produção (docker-compose.prod.yml)..."
docker compose -f docker-compose.prod.yml up -d --build

cat <<EOF

Deploy iniciado. Confira:
  - DNS:      dig +short $DOMAIN        (deve resolver para o IP deste servidor)
  - Certificado HTTPS: docker compose -f docker-compose.prod.yml logs -f caddy
  - App:      docker compose -f docker-compose.prod.yml logs -f app
  - Acesso:   https://$DOMAIN
EOF
