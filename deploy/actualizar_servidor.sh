#!/usr/bin/env bash
# Actualizaciones de seguridad y reinicio nocturno del servidor (cada día a las 03:00, hora de Madrid).
#
# 1. Comprueba que hay una copia de seguridad de las últimas 26 h; si no, la hace antes de tocar nada.
# 2. Instala las actualizaciones de SEGURIDAD del sistema (unattended-upgrade: solo los repositorios de seguridad;
#    no toca Docker ni las imágenes del PMS, que se actualizan con «git pull» y «docker compose up -d --build»).
# 3. Reinicia el servidor. Los contenedores del PMS (db, app, caddy) arrancan solos («restart: unless-stopped»);
#    los de gestión, según su propia configuración (comprobar que también tienen «restart»).
#    A los 90 s del arranque se comprueba que el PMS está en marcha; si no, se levanta con «docker compose up -d».
#    El PMS está parado 1-2 minutos. El mantenimiento de las 06:00 avisa por correo si algo no ha ido bien.
#
#   /opt/pms/deploy/actualizar_servidor.sh --instalar   programarlo cada día a las 03:00 de Madrid (una sola vez)
#   /opt/pms/deploy/actualizar_servidor.sh --probar     ver qué se actualizaría (no instala ni reinicia)
#   /opt/pms/deploy/actualizar_servidor.sh --ahora      hacerlo ya (actualiza y REINICIA el servidor)
#   /opt/pms/deploy/actualizar_servidor.sh --quitar     dejar de hacerlo
#   touch /etc/pms-sin-reinicio                         mientras exista: actualiza, pero no reinicia
#
# Último resultado: cat /var/lib/pms-actualizacion/ultimo.txt · histórico: /var/log/pms-actualizacion.log
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive
cd "$(dirname "$0")" || exit 1
DEPLOY=$(pwd)
LOG=/var/log/pms-actualizacion.log
ESTADO_DIR=/var/lib/pms-actualizacion
PAUSA=/etc/pms-sin-reinicio
BACKUPS="${PMS_BACKUP_DIR:-/var/backups/pms}"
APT_LOCK=(-o DPkg::Lock::Timeout=900)  # si unattended-upgrades ya está trabajando, espera hasta 15 min

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
estado() { mkdir -p "$ESTADO_DIR"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" > "$ESTADO_DIR/ultimo.txt"; log "$*"; }

case "${1:-}" in
  --instalar)
    apt-get "${APT_LOCK[@]}" install -y unattended-upgrades > /dev/null || { echo "No se pudo instalar unattended-upgrades"; exit 1; }
    systemctl enable docker > /dev/null 2>&1  # Docker arranca con el servidor
    # El servidor va en hora UTC: cron lo lanza a la 01:00 y a las 02:00 UTC y solo sigue la vez que en Madrid son
    # las 03:00 (02:00 UTC en invierno, 01:00 UTC en verano).
    PROG="0 1,2 * * * $DEPLOY/actualizar_servidor.sh --programado >> $LOG 2>&1"
    ARRANQUE="@reboot sleep 90 && $DEPLOY/actualizar_servidor.sh --tras-reinicio >> $LOG 2>&1"
    ( crontab -l 2>/dev/null | grep -v 'deploy/actualizar_servidor.sh'; echo "$PROG"; echo "$ARRANQUE" ) | crontab -
    cat > /etc/logrotate.d/pms-actualizacion <<EOF
$LOG {
  monthly
  rotate 12
  compress
  missingok
  notifempty
}
EOF
    echo "Programado cada día a las 03:00 (hora de Madrid):"
    echo "  $PROG"
    echo "  $ARRANQUE"
    exit 0 ;;
  --quitar)
    ( crontab -l 2>/dev/null | grep -v 'deploy/actualizar_servidor.sh' ) | crontab -
    echo "Quitado: el servidor ya no se actualiza ni se reinicia cada noche."
    exit 0 ;;
  --probar)
    apt-get "${APT_LOCK[@]}" update -qq
    echo "Actualizaciones de seguridad que se instalarían esta noche:"
    unattended-upgrade --dry-run -v 2>&1 | grep -iE "^(Packages that will be upgraded|Paquetes|Allowed origins|No packages)" || true
    echo; echo "Todas las actualizaciones pendientes (solo se instalan las de seguridad):"
    apt list --upgradable 2>/dev/null | tail -n +2
    [ -f /var/run/reboot-required ] && echo && echo "Hay un reinicio pendiente de actualizaciones anteriores."
    [ -f "$PAUSA" ] && echo && echo "OJO: existe $PAUSA, esta noche NO se reiniciará."
    exit 0 ;;
  --tras-reinicio)
    if docker compose ps --status running --services 2>/dev/null | grep -qx app; then
      estado "OK tras el reinicio: PMS en marcha"
    else
      docker compose up -d > /dev/null 2>&1; sleep 30
      if docker compose ps --status running --services 2>/dev/null | grep -qx app; then
        estado "OK tras el reinicio: PMS arrancado con «docker compose up -d»"
      else
        estado "ERROR tras el reinicio: el PMS no arranca (ver «docker compose logs --tail=100 app»)"
      fi
    fi
    exit 0 ;;
  --programado)
    [ "$(TZ=Europe/Madrid date +%H)" = "03" ] || exit 0 ;;
  --ahora) ;;
  *)
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
esac

exec 9> /run/pms-actualizacion.lock
flock -n 9 || { log "Ya hay una actualización en marcha"; exit 0; }
log "---- Actualización nocturna"

# 1. copia de seguridad reciente (la diaria de backup.sh); si no la hay, se hace ahora
if [ -z "$(find "$BACKUPS" -name 'pms_*.dump' -mmin -1560 2>/dev/null | head -1)" ]; then
  log "No hay copia de las últimas 26 h: se hace ahora"
  if ! "$DEPLOY/backup.sh" >> /var/log/pms-backup.log 2>&1; then
    estado "ERROR: la copia de seguridad ha fallado; no se actualiza ni se reinicia (ver /var/log/pms-backup.log)"
    exit 1
  fi
fi

# 2. actualizaciones de seguridad
apt-get "${APT_LOCK[@]}" update -qq || log "Aviso: «apt-get update» ha fallado; se sigue con lo que hay"
if unattended-upgrade -v >> "$LOG" 2>&1; then
  RESUMEN="actualizaciones de seguridad instaladas"
else
  RESUMEN="unattended-upgrade terminó con error (ver $LOG)"
fi
apt-get "${APT_LOCK[@]}" -y autoremove --purge > /dev/null 2>&1

# 3. reinicio
if [ -f "$PAUSA" ]; then
  estado "OK sin reinicio ($RESUMEN; existe $PAUSA)"
  exit 0
fi
estado "REINICIANDO ($RESUMEN)"
sync
systemctl reboot
