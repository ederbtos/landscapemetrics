#!/usr/bin/env bash
set -euo pipefail

# Backup de data/app.db (credenciais do Earth Engine criptografadas por
# usuário). Não decide POR VOCÊ onde guardar o backup fora do servidor —
# isso continua sendo escolha de quem hospeda — mas automatiza a parte
# mecânica: gera um dump datado e, se BACKUP_REMOTE estiver definida, envia
# para lá via rsync (ex.: outro host, ou um bucket montado via rclone/s3fs).
#
# Uso:
#   ./scripts/backup-db.sh                              # só gera backup local
#   BACKUP_REMOTE=user@host:/backups/ ./scripts/backup-db.sh   # + envia via rsync
#
# Agendamento sugerido (crontab -e no servidor):
#   0 3 * * * cd /caminho/do/repo && ./scripts/backup-db.sh >> /var/log/landscapemetrics-backup.log 2>&1

DB_PATH="data/app.db"
BACKUP_DIR="data/backups"

if [[ ! -f "$DB_PATH" ]]; then
  echo "Nada para fazer backup: $DB_PATH não existe ainda." >&2
  exit 0
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/app-$TIMESTAMP.db"

cp "$DB_PATH" "$DEST"
echo "Backup local criado: $DEST"

# Mantém só os 30 backups locais mais recentes.
ls -1t "$BACKUP_DIR"/app-*.db 2>/dev/null | tail -n +31 | xargs -r rm --

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  echo "Enviando para $BACKUP_REMOTE via rsync..."
  rsync -az "$DEST" "$BACKUP_REMOTE"
fi
