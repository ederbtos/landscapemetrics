# 14 — Deploy

## Ambientes

| Ambiente | Como rodar | Arquivo(s) |
| --- | --- | --- |
| Local (sem Docker) | `streamlit run app.py` | [requirements.txt](../requirements.txt) |
| Local (Docker) | `docker compose up --build` | [docker-compose.yml](../docker-compose.yml), [Dockerfile](../Dockerfile) |
| Produção (VPS + HTTPS) | `./scripts/deploy.sh seu-dominio.com` | [docker-compose.prod.yml](../docker-compose.prod.yml), [Caddyfile.example](../Caddyfile.example) |

## Variáveis de ambiente e segredos

| Variável/segredo | Onde é definido | Obrigatório | Descrição |
| --- | --- | --- | --- |
| `jwt_secret_key` | `.streamlit/secrets.toml` | Sim | Assina o JWT de sessão do login por e-mail/senha |
| `app_encryption_key` | `.streamlit/secrets.toml` | Sim | Chave Fernet para cifrar credenciais do Earth Engine |
| `[auth]` (bloco: `client_id`, `client_secret`, `redirect_uri`, `server_metadata_url`, `cookie_secret`) | `.streamlit/secrets.toml` | Não | Habilita o login com Google |
| `DB_PATH` | Variável de ambiente do processo | Não (default `data/app.db`) | Caminho do arquivo SQLite |
| `BACKUP_REMOTE` | Variável de ambiente no momento de rodar `backup-db.sh` | Não | Destino `rsync` para backup fora do servidor |

`secrets.toml` real nunca é commitado (`.gitignore`) nem copiado para dentro da imagem Docker —
é sempre montado como volume somente-leitura.

## Local sem Docker

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# editar .streamlit/secrets.toml: jwt_secret_key e app_encryption_key
streamlit run app.py
```

## Local com Docker

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# editar .streamlit/secrets.toml
docker compose up --build
```

Acesse `http://localhost:8501`. `docker-compose.yml` publica a porta 8501 diretamente (sem
HTTPS) — adequado só para desenvolvimento local.

## Produção (VPS + Docker + Caddy)

### Pré-requisitos (decisão de quem hospeda)

1. Servidor com Docker instalado.
2. Domínio com registro DNS tipo A apontando para o IP do servidor.
3. Portas 80 e 443 liberadas no firewall.

### Passos

```bash
git clone <repo> && cd landscapemetrics
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# editar .streamlit/secrets.toml com valores de produção (gerados no próprio servidor)
chmod +x scripts/deploy.sh
./scripts/deploy.sh seu-dominio.com
```

O script:
1. Verifica pré-requisitos (Docker instalado, `secrets.toml` presente).
2. Gera `Caddyfile` a partir de `Caddyfile.example`, substituindo o domínio.
3. Sobe `docker-compose.prod.yml` (`app` + `caddy`), que expõe HTTPS automaticamente via
   Let's Encrypt.

### Diferenças entre local e produção

| Aspecto | `docker-compose.yml` (local) | `docker-compose.prod.yml` (produção) |
| --- | --- | --- |
| Porta exposta ao host | 8501 (app direto) | Nenhuma do app — só 80/443 do Caddy |
| HTTPS | Não | Sim, automático via Caddy + Let's Encrypt |
| Serviços | `app` | `app` + `caddy` |

## Backup

```bash
./scripts/backup-db.sh                                      # apenas backup local
BACKUP_REMOTE=user@host:/backups/ ./scripts/backup-db.sh     # + envio remoto via rsync
```

Recomendado agendar via `cron` (ver comentário no próprio script):

```
0 3 * * * cd /caminho/do/repo && ./scripts/backup-db.sh >> /var/log/landscapemetrics-backup.log 2>&1
```

Mantém os 30 backups locais mais recentes automaticamente.

## Verificação pós-deploy

```bash
dig +short seu-dominio.com                                       # deve resolver ao IP do servidor
docker compose -f docker-compose.prod.yml logs -f caddy          # acompanhar emissão do certificado
docker compose -f docker-compose.prod.yml logs -f app            # acompanhar boot do app
```
