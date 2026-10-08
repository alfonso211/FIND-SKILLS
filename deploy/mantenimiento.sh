#!/usr/bin/env bash
# Mantenimiento diario del PMS (cron a las 06:00, ver INSTALACION.md, apartado 8 quinquies).
#
# Comprueba que todo funciona y no hay puntos débiles. Lo que puede arreglar solo, lo arregla; lo que no,
# lo avisa por correo URGENTE a PMS_MANTENIMIENTO_EMAIL (por defecto alfonso@inversiete.es).
#   Servidor: Docker, contenedores (db, app, caddy), acceso HTTPS, certificado, disco, memoria, copias de
#             seguridad (en el servidor y en Google Drive), cortafuegos, actualizaciones de seguridad, puertos
#             abiertos, SSH, permisos del .env, errores en el registro y versión desplegada.
#   PMS (app.mantenimiento): base de datos y su versión, documentos cifrados (presentes y legibles), correo,
#             cuelgues y usuarios con contraseña provisional.
#
# Correos: URGENTE si queda algún fallo GRAVE; normal si ha arreglado algo o hay un aviso nuevo; los lunes, resumen
# semanal aunque todo esté correcto (así se sabe que el mantenimiento sigue funcionando).
#
#   /opt/pms/deploy/mantenimiento.sh             ejecutarlo a mano (muestra el informe)
#   /opt/pms/deploy/mantenimiento.sh --instalar  programarlo cada día a las 06:00 de Madrid (una sola vez)
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C.UTF-8  # cron trae un PATH mínimo
cd "$(dirname "$0")" || exit 1
DEPLOY=$(pwd)
ESTADO_DIR=/var/lib/pms-mantenimiento
LOG=/var/log/pms-mantenimiento.log
LOG_BACKUP=/var/log/pms-backup.log
BACKUPS="${PMS_BACKUP_DIR:-/var/backups/pms}"
SERVICIOS=(db app caddy)
PUERTOS_PUBLICOS="22 80 443"

# El servidor va en hora UTC: cron lo lanza a las 04:00 y a las 05:00 UTC y solo sigue la vez que en Madrid son las
# 06:00 (05:00 UTC en invierno, 04:00 UTC en verano).
if [ "${1:-}" = "--programado" ] && [ "$(TZ=Europe/Madrid date +%H)" != "06" ]; then
  exit 0
fi
if [ "${1:-}" = "--instalar" ]; then
  LINEA="0 4,5 * * * $DEPLOY/mantenimiento.sh --programado >> $LOG 2>&1"
  ( crontab -l 2>/dev/null | grep -v 'deploy/mantenimiento.sh'; echo "$LINEA" ) | crontab -
  cat > /etc/logrotate.d/pms-mantenimiento <<EOF
$LOG {
  monthly
  rotate 12
  compress
  missingok
  notifempty
}
EOF
  echo "Programado: $LINEA"
  exit 0
fi

exec 9> /run/pms-mantenimiento.lock
flock -n 9 || { echo "Ya hay un mantenimiento en marcha"; exit 0; }
mkdir -p "$ESTADO_DIR"
INFORME=$(mktemp)
trap 'rm -f "$INFORME"' EXIT

anota() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$INFORME"; }
# lee una variable del .env sin cargar ni mostrar el resto (contraseñas)
env_var() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']$//"; }
DOMINIO=$(env_var PMS_DOMINIO)

# ------------------------------------------------------------------------------------------------ Docker
DOCKER_OK=1
if ! docker info > /dev/null 2>&1; then
  systemctl restart docker > /dev/null 2>&1; sleep 20
  if docker info > /dev/null 2>&1; then
    anota ARREGLADO Docker "Docker estaba parado: se ha vuelto a arrancar"
  else
    DOCKER_OK=0
    anota GRAVE Docker "Docker no arranca: el PMS está parado. Revisar con «systemctl status docker»."
  fi
fi

# ------------------------------------------------------------------------------------------------ contenedores
estado() {  # «running healthy», «running starting», «exited -»… o «ausente»
  local id; id=$(docker compose ps -aq "$1" 2>/dev/null | head -1)
  [ -n "$id" ] || { echo "ausente"; return; }
  docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$id"
}
bien() { case "$(estado "$1")" in "running healthy"|"running -") return 0;; *) return 1;; esac; }
esperar() {  # hasta 3 minutos a que el servicio esté bien
  local _; for _ in $(seq 18); do bien "$1" && return 0; sleep 10; done; return 1
}

if [ "$DOCKER_OK" = 1 ]; then
  for s in "${SERVICIOS[@]}"; do
    e=$(estado "$s")
    [ "$e" = "running starting" ] && { esperar "$s"; e=$(estado "$s"); }
    if bien "$s"; then continue; fi
    if [ "${e%% *}" = "running" ]; then
      docker compose restart "$s" > /dev/null 2>&1
    else
      docker compose up -d > /dev/null 2>&1
    fi
    if esperar "$s"; then
      anota ARREGLADO Contenedores "$s no funcionaba ($e): reiniciado y ya responde"
    else
      anota GRAVE Contenedores "$s no funciona ($(estado "$s")) ni tras reiniciarlo. Ver «docker compose logs --tail=100 $s»."
    fi
  done
  grep -q "^GRAVE"$'\t'"Contenedores" "$INFORME" || anota OK Contenedores "db, app y caddy funcionando"
fi

# ------------------------------------------------------------------------------------------------ HTTPS
if [ -n "$DOMINIO" ] && command -v curl > /dev/null; then
  web() { curl -fsS --max-time 20 --resolve "$DOMINIO:443:127.0.0.1" "https://$DOMINIO/salud" > /dev/null 2>&1; }
  if web; then
    anota OK Web "https://$DOMINIO responde"
  else
    docker compose restart caddy > /dev/null 2>&1; sleep 20
    if web; then anota ARREGLADO Web "https://$DOMINIO no respondía: reiniciado el proxy (caddy)"
    else anota GRAVE Web "https://$DOMINIO no responde: nadie puede entrar al PMS. Ver «docker compose logs --tail=100 caddy»."
    fi
  fi
  caduca() {
    local fin; fin=$(echo | timeout 20 openssl s_client -connect 127.0.0.1:443 -servername "$DOMINIO" 2>/dev/null \
      | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    [ -n "$fin" ] && echo $(( ($(date -d "$fin" +%s) - $(date +%s)) / 86400 ))
  }
  DIAS=$(caduca)
  if [ -n "$DIAS" ] && [ "$DIAS" -lt 20 ]; then  # caddy lo renueva solo 30 días antes: si no lo ha hecho, se fuerza
    docker compose restart caddy > /dev/null 2>&1; sleep 60; DIAS2=$(caduca)
    if [ -n "$DIAS2" ] && [ "$DIAS2" -gt "$DIAS" ]; then
      anota ARREGLADO Certificado "El certificado HTTPS caducaba en $DIAS días: renovado ($DIAS2 días)"
    elif [ "$DIAS" -lt 7 ]; then
      anota GRAVE Certificado "El certificado HTTPS caduca en $DIAS días y no se renueva solo: el navegador bloqueará el PMS. Revisar DNS y «docker compose logs caddy»."
    else
      anota AVISO Certificado "El certificado HTTPS caduca en $DIAS días y aún no se ha renovado"
    fi
  elif [ -n "$DIAS" ]; then
    anota OK Certificado "Certificado HTTPS válido $DIAS días más (se renueva solo)"
  else
    anota AVISO Certificado "No se ha podido leer el certificado HTTPS"
  fi
else
  anota AVISO Web "No se ha podido comprobar el acceso HTTPS (falta PMS_DOMINIO en el .env o curl)"
fi

# ------------------------------------------------------------------------------------------------ disco y memoria
uso_disco() { df -P / | awk 'NR==2 {gsub("%","",$5); print $5}'; }
D=$(uso_disco)
if [ "$D" -ge 80 ]; then
  docker image prune -af --filter "until=168h" > /dev/null 2>&1
  docker builder prune -af --filter "until=168h" > /dev/null 2>&1
  journalctl --vacuum-size=200M > /dev/null 2>&1
  apt-get clean > /dev/null 2>&1
  D2=$(uso_disco)
  if [ "$D2" -ge 90 ]; then
    anota GRAVE Disco "Disco al $D2 % incluso después de limpiar: si se llena, el PMS y las copias se paran. Hay que ampliar el disco o revisar qué ocupa («du -xh / --max-depth=2 | sort -h | tail»)."
  elif [ "$D2" -ge 80 ]; then
    anota AVISO Disco "Disco al $D2 % después de limpiar (estaba al $D %): conviene ampliarlo"
  else
    anota ARREGLADO Disco "Disco al $D %: borradas imágenes y registros antiguos, ahora al $D2 %"
  fi
else
  anota OK Disco "Disco al $D %"
fi
MEM=$(free -m | awk '/^Mem:/ {printf "%d", $7 * 100 / $2}')
if [ -n "$MEM" ] && [ "$MEM" -lt 10 ]; then
  anota AVISO Memoria "Solo queda libre el $MEM % de la memoria: el PMS puede ir lento o colgarse"
else
  anota OK Memoria "Memoria libre: ${MEM:-?} %"
fi

# ------------------------------------------------------------------------------------------------ copias de seguridad
if ! crontab -l 2>/dev/null | grep -q 'deploy/backup.sh'; then
  ( crontab -l 2>/dev/null; echo "15 3 * * * $DEPLOY/backup.sh >> $LOG_BACKUP 2>&1" ) | crontab -
  anota ARREGLADO Copias "La copia diaria no estaba programada: programada a las 03:15"
fi
copia_reciente() { find "$BACKUPS" -maxdepth 1 -name 'pms_*.dump' -size +0 -mmin -1560 2>/dev/null | grep -q .; }
if copia_reciente; then
  anota OK Copias "Copia de la base de datos de las últimas 24 h en $BACKUPS"
elif [ "$DOCKER_OK" = 1 ] && ./backup.sh >> "$LOG_BACKUP" 2>&1 && copia_reciente; then
  anota ARREGLADO Copias "No había copia de las últimas 24 h: hecha ahora"
else
  anota GRAVE Copias "No hay copia de seguridad de las últimas 24 h y backup.sh falla. Ver «tail -30 $LOG_BACKUP»."
fi
if command -v rclone > /dev/null && rclone listremotes 2>/dev/null | grep -qx "pmscopia:"; then
  ULT=$(grep -h "subida a Google Drive OK" "$LOG_BACKUP" 2>/dev/null | tail -1 | cut -c1-10)
  if [ -n "$ULT" ] && [ "$(( ($(date +%s) - $(date -d "$ULT" +%s)) / 86400 ))" -le 1 ]; then
    anota OK Copias "Última copia en Google Drive: $ULT"
  else
    anota GRAVE Copias "La copia no se sube a Google Drive desde ${ULT:-hace tiempo}: si se pierde el servidor no habría copia. Probar «$DEPLOY/backup.sh» y revisar la autorización de rclone."
  fi
else
  anota GRAVE Copias "No hay copia fuera del servidor (rclone sin el remoto pmscopia, ver INSTALACION.md apartado 8)"
fi

# ------------------------------------------------------------------------------------------------ seguridad
if [ -f .env ] && [ "$(stat -c %a .env)" != "600" ]; then
  chmod 600 .env && anota ARREGLADO Seguridad "El fichero .env (contraseñas) se podía leer por otros usuarios: permisos corregidos"
fi
if command -v ufw > /dev/null; then
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    anota OK Seguridad "Cortafuegos activo"
  else
    ufw allow OpenSSH > /dev/null; ufw allow 80/tcp > /dev/null; ufw allow 443/tcp > /dev/null
    ufw --force enable > /dev/null && anota ARREGLADO Seguridad "El cortafuegos estaba desactivado: activado (solo SSH, 80 y 443)"
  fi
else
  anota AVISO Seguridad "No hay cortafuegos (ufw) instalado"
fi
if [ -f /etc/apt/apt.conf.d/20auto-upgrades ] && grep -q 'Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades; then
  anota OK Seguridad "Actualizaciones de seguridad automáticas activadas"
else
  anota AVISO Seguridad "Las actualizaciones de seguridad automáticas no están activadas («dpkg-reconfigure -plow unattended-upgrades»)"
fi
if [ -f /var/run/reboot-required ]; then
  anota AVISO Seguridad "El servidor necesita reiniciarse para aplicar actualizaciones de seguridad. Hacerlo fuera de horario con «reboot» (el PMS arranca solo en 1-2 minutos)."
fi
ABIERTOS=$(ss -Htln 2>/dev/null | awk '{print $4}' | grep -vE '^(127\.|\[::1\]|::1)' | sed 's/.*://' | sort -un \
  | while read -r p; do case " $PUERTOS_PUBLICOS " in *" $p "*) ;; *) printf '%s ' "$p";; esac; done)
if [ -n "$ABIERTOS" ]; then
  anota AVISO Seguridad "Puertos abiertos no previstos: ${ABIERTOS% }. Solo deberían estar 22, 80 y 443."
fi
if sshd -T 2>/dev/null | grep -q '^passwordauthentication yes'; then
  FALLOS=$(journalctl -u ssh -u sshd --since "24 hours ago" 2>/dev/null | grep -c "Failed password")
  if systemctl is-active --quiet fail2ban; then
    anota OK Seguridad "SSH con contraseña protegido con fail2ban ($FALLOS intentos fallidos en 24 h)"
  else
    anota AVISO Seguridad "SSH admite contraseña y no hay fail2ban: $FALLOS intentos fallidos de entrar en 24 h. Recomendable «apt install fail2ban»."
  fi
fi

# ------------------------------------------------------------------------------------------------ versión y registros
if git -C .. rev-parse > /dev/null 2>&1; then
  # Ficheros del programa cambiados en el servidor: el próximo «git pull» puede fallar. Si solo cambian los permisos
  # o los finales de línea, se restauran. Si cambia el contenido NO se toca (puede ser un cambio necesario, como otra
  # web en el Caddyfile): se guarda una copia del cambio y se avisa de qué ficheros son.
  CAMBIADOS=$(git -C .. status --porcelain --untracked-files=no | cut -c4-)
  if [ -n "$CAMBIADOS" ]; then
    LISTA=$(tr '\n' ' ' <<< "$CAMBIADOS" | sed 's/ $//')
    if git -C .. -c core.fileMode=false diff --quiet --ignore-cr-at-eol HEAD 2>/dev/null; then
      git -C .. config core.fileMode false
      git -C .. checkout -q -- . && \
        anota ARREGLADO Versión "Ficheros con solo permisos o finales de línea cambiados ($LISTA): restaurados"
    else
      mkdir -p "$ESTADO_DIR"
      PARCHE="$ESTADO_DIR/cambios_locales.patch"
      git -C .. diff HEAD > "$PARCHE" 2>/dev/null
      CONSEJO="pase el cambio al programa o, si sobra, deshágalo con «git -C /opt/pms checkout -- <fichero>»"
      grep -q "deploy/Caddyfile" <<< "$CAMBIADOS" && \
        CONSEJO="las webs adicionales van en un fichero propio en /opt/pms/deploy/sitios/ (ver LEEME.md de esa carpeta), no en el Caddyfile"
      anota AVISO Versión "Ficheros modificados a mano en /opt/pms ($LISTA): el próximo «git pull» puede fallar. Copia del cambio en $PARCHE; $CONSEJO"
    fi
  fi
  timeout 60 git -C .. fetch -q origin 2>/dev/null
  ACTUAL=$(git -C .. log --oneline -1 | cut -c1-7)
  NUEVOS=$(git -C .. rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
  if [ "$NUEVOS" -gt 0 ]; then
    anota OK Versión "Versión $ACTUAL; hay $NUEVOS cambio(s) publicados pendientes de desplegar"
  else
    anota OK Versión "Versión $ACTUAL (la última)"
  fi
fi
if [ "$DOCKER_OK" = 1 ]; then
  REG=$(docker compose logs --since 24h --no-log-prefix app 2>/dev/null)
  ERR=$(grep -cE "Traceback|ERROR|CRITICAL" <<< "$REG")
  E500=$(grep -cE '" 5[0-9]{2} ' <<< "$REG")
  if [ "$ERR" -gt 0 ] || [ "$E500" -gt 0 ]; then
    anota AVISO Registro "En 24 h: $ERR error(es) internos y $E500 respuesta(s) 5xx. Ver «docker compose logs --since 24h app | grep -E 'Traceback|ERROR' -A5»."
  else
    anota OK Registro "Sin errores en el registro en 24 h"
  fi
fi

# ------------------------------------------------------------------------------------------------ PMS por dentro
if [ "$DOCKER_OK" = 1 ] && bien app; then
  docker compose exec -T app python -m app.mantenimiento comprobar >> "$INFORME" 2>/dev/null \
    || anota GRAVE PMS "No se han podido hacer las comprobaciones internas del PMS"
fi

# ------------------------------------------------------------------------------------------------ informe y correo
{
  echo "=== Mantenimiento $(date '+%F %T') ==="
  awk -F'\t' 'BEGIN {o["GRAVE"]=0; o["ARREGLADO"]=1; o["AVISO"]=2; o["OK"]=3}
    {printf "%d\t%-10s %-14s %s\n", o[$1], $1, $2, $3}' "$INFORME" | sort -s -n -k1,1 | cut -f2-
} | tee "$ESTADO_DIR/ultimo.txt"

# los avisos se envían cuando aparecen por primera vez (sin cifras, para que «12 intentos» y «15 intentos» sean el mismo)
CLAVES=$(awk -F'\t' '$1 == "AVISO" {print $2 "|" substr($3, 1, 60)}' "$INFORME" | tr -d '0-9' | sort -u)
NUEVOS_AVISOS=$(comm -23 <(echo "$CLAVES") <(sort -u "$ESTADO_DIR/avisos" 2>/dev/null) | grep -c .)
echo "$CLAVES" > "$ESTADO_DIR/avisos"

if grep -q "^GRAVE" "$INFORME"; then TIPO=urgente
elif grep -q "^ARREGLADO" "$INFORME" || [ "$NUEVOS_AVISOS" -gt 0 ]; then TIPO=avisos
elif [ "$(date +%u)" = 1 ]; then TIPO=semanal
else TIPO=""
fi
if [ -n "$TIPO" ]; then
  if { bien app && docker compose exec -T app python -m app.mantenimiento correo "$TIPO" "$(hostname)" < "$INFORME"; } ||
     docker compose run --rm --no-deps -T app python -m app.mantenimiento correo "$TIPO" "$(hostname)" < "$INFORME"; then
    echo "Correo ($TIPO) enviado"
  else
    echo "ATENCIÓN: NO SE HA PODIDO ENVIAR EL CORREO ($TIPO). Revisar la configuración SMTP del .env."
  fi
fi
