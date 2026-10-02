#!/usr/bin/env bash
# Copia de seguridad diaria de la base de datos del PMS.
# Programar con cron (ver INSTALACION.md). Conserva 30 días en el servidor.
set -euo pipefail
cd "$(dirname "$0")"
DESTINO="${PMS_BACKUP_DIR:-/var/backups/pms}"
mkdir -p "$DESTINO"
FICHERO="$DESTINO/pms_$(date +%Y%m%d_%H%M).dump"
docker compose exec -T db pg_dump -U pms -d pms -Fc > "$FICHERO"
# comprobar que la copia es legible antes de dar el proceso por bueno
docker compose exec -T db pg_restore --list < "$FICHERO" > /dev/null
find "$DESTINO" -name 'pms_*.dump' -mtime +30 -delete
echo "$(date '+%F %T') copia OK: $FICHERO ($(du -h "$FICHERO" | cut -f1))"
