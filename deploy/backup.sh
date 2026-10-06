#!/usr/bin/env bash
# Copia de seguridad diaria de la base de datos y de las copias (cifradas) de documentos de identidad.
# Programar con cron (ver INSTALACION.md). Conserva 30 días en el servidor.
# Copia fuera del servidor: si existe el remoto de rclone «pmscopia» (Google Drive cifrado, ver INSTALACION.md),
# sube la copia y conserva allí 90 días.
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

REMOTO="${PMS_BACKUP_REMOTO:-pmscopia:}"
if command -v rclone > /dev/null && rclone listremotes 2>/dev/null | grep -qx "$REMOTO"; then
  SUBIR=("$FICHERO")
  [ -f "$DOCS" ] && SUBIR+=("$DOCS")
  for f in "${SUBIR[@]}"; do
    rclone copy "$f" "$REMOTO" --retries 5
  done
  rclone delete "$REMOTO" --min-age 90d
  echo "$(date '+%F %T') subida a Google Drive OK: ${#SUBIR[@]} fichero(s) en $REMOTO"
else
  echo "$(date '+%F %T') AVISO: sin copia fuera del servidor (falta rclone o el remoto $REMOTO; ver INSTALACION.md)"
fi
