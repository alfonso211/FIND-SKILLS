#!/usr/bin/env bash
# Copia de seguridad diaria de la base de datos y de las copias (cifradas) de documentos de identidad.
# Programar con cron (ver INSTALACION.md). Conserva 30 días en el servidor.
set -euo pipefail
cd "$(dirname "$0")"
DESTINO="${PMS_BACKUP_DIR:-/var/backups/pms}"
mkdir -p "$DESTINO"
FICHERO="$DESTINO/pms_$(date +%Y%m%d_%H%M).dump"
docker compose exec -T db pg_dump -U pms -d pms -Fc > "$FICHERO"
# comprobar que la copia es legible antes de dar el proceso por bueno
docker compose exec -T db pg_restore --list < "$FICHERO" > /dev/null
DOCS="$DESTINO/documentos_$(date +%Y%m%d_%H%M).tar.gz"
if docker compose exec -T app sh -c 'test -d /data/documentos' 2>/dev/null; then
  docker compose exec -T app tar czf - -C /data documentos > "$DOCS"
  tar tzf "$DOCS" > /dev/null
else
  rm -f "$DOCS"; DOCS="(sin carpeta de documentos)"
fi
find "$DESTINO" \( -name 'pms_*.dump' -o -name 'documentos_*.tar.gz' \) -mtime +30 -delete
echo "$(date '+%F %T') copia OK: $FICHERO ($(du -h "$FICHERO" | cut -f1)) · documentos: $DOCS"
