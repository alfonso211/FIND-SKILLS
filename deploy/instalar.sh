#!/usr/bin/env bash
# Instalador automático del PMS Grupo INVERSIETE para un servidor Ubuntu limpio (Arsys).
# Uso (como root):   bash /opt/pms/deploy/instalar.sh [dominio]
# Se puede ejecutar de nuevo sin riesgo: no borra datos ni cambia claves ya generadas.
set -euo pipefail

DOMINIO="${1:-pms.inversiete.es}"
DIR="${PMS_DIR:-/opt/pms}"
DEPLOY="$DIR/deploy"
CRED="${PMS_CRED:-/root/pms-credenciales.txt}"

verde() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }
aviso() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }
error() { printf '\033[1;31mERROR: %s\033[0m\n' "$*"; exit 1; }
pregunta() { local r; read -r -p "$1 [s/N] " r < /dev/tty; [[ "$r" =~ ^[sS]$ ]]; }

[ "$(id -u)" -eq 0 ] || error "Ejecute como root (escriba primero: sudo -i)"
[ -f "$DEPLOY/docker-compose.yml" ] || error "No encuentro $DEPLOY/docker-compose.yml. ¿Se descargó el código en $DIR?"

verde "1/7 Comprobando que $DOMINIO apunta a este servidor"
apt-get update -qq && apt-get install -y -qq curl dnsutils >/dev/null
IP_SERVIDOR=$(curl -fsS4 --max-time 10 https://api.ipify.org || true)
IP_DNS=$(dig +short A "$DOMINIO" | tail -n1)
echo "IP de este servidor: ${IP_SERVIDOR:-desconocida}   |   $DOMINIO apunta a: ${IP_DNS:-(nada)}"
if [ -z "$IP_DNS" ] || [ "$IP_DNS" != "$IP_SERVIDOR" ]; then
  aviso "El dominio aún no apunta a este servidor. Sin eso no se puede obtener el certificado HTTPS."
  pregunta "¿Continuar de todos modos?" || exit 1
fi
if [ -n "$(dig +short AAAA "$DOMINIO")" ]; then
  aviso "$DOMINIO tiene un registro AAAA (IPv6). Elimínelo en IONOS o el certificado puede fallar."
fi

verde "2/7 Actualizando el sistema (puede tardar unos minutos)"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
apt-get upgrade -y -qq >/dev/null
apt-get install -y -qq git ufw unattended-upgrades openssl cron >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

verde "3/7 Cortafuegos: solo SSH (22), HTTP (80) y HTTPS (443)"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | sed -n '1,10p'

verde "4/7 Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
docker --version && docker compose version

verde "5/7 Configuración"
cd "$DEPLOY"
if [ ! -f .env ]; then
  clave() { openssl rand -base64 48 | tr -d '/+=\n' | cut -c1-40; }
  ADMIN_PW=$(clave)
  umask 077
  cat > .env <<EOF
PMS_DOMINIO=$DOMINIO
DB_PASSWORD=$(clave)
PMS_SECRET_KEY=$(clave)
PMS_ADMIN_EMAIL=admin@inversiete.es
PMS_ADMIN_PASSWORD=$ADMIN_PW
PMS_TOKEN_HOURS=12
EOF
  cat > "$CRED" <<EOF
PMS Grupo INVERSIETE - credenciales del administrador técnico
Dirección: https://$DOMINIO
Usuario:   admin@inversiete.es
Clave:     $ADMIN_PW
Guárdela en un lugar seguro y borre este fichero:  rm $CRED
EOF
  echo "Claves generadas. Credenciales del administrador en $CRED"
else
  echo "Ya existe $DEPLOY/.env: se mantienen las claves actuales."
fi
# Clave de cifrado de los documentos de identidad (se añade también a instalaciones anteriores)
if ! grep -q '^PMS_DOCS_KEY=.' .env; then
  sed -i '/^PMS_DOCS_KEY=/d' .env
  DOCS_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
  echo "PMS_DOCS_KEY=$DOCS_KEY" >> .env
  umask 077
  {
    echo
    echo "Clave de cifrado de las copias de documentos de identidad (PMS_DOCS_KEY):"
    echo "$DOCS_KEY"
    echo "Guárdela FUERA del servidor (gestor de contraseñas). Sin ella no se pueden recuperar las copias."
  } >> "$CRED"
  aviso "Generada la clave de cifrado de documentos. Está en $CRED: guárdela fuera del servidor y borre el fichero."
fi

verde "6/7 Arrancando el PMS (la primera vez tarda 3-5 minutos)"
docker compose up -d --build
echo -n "Esperando a que responda https://$DOMINIO "
OK=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 5 "https://$DOMINIO/" >/dev/null 2>&1; then OK=1; break; fi
  echo -n "."; sleep 5
done
echo
if [ "$OK" -eq 1 ]; then
  echo "El PMS responde correctamente por HTTPS."
else
  aviso "No responde aún por HTTPS. Revise el DNS y ejecute:  cd $DEPLOY && docker compose logs --tail 50"
fi

verde "7/7 Copias de seguridad diarias (03:15, se guardan 30 días)"
chmod +x "$DEPLOY/backup.sh"
LINEA="15 3 * * * $DEPLOY/backup.sh >> /var/log/pms-backup.log 2>&1"
# (crontab -l falla si aún no hay tareas programadas: no debe detener la instalación)
{ crontab -l 2>/dev/null | grep -v 'deploy/backup.sh' || true; echo "$LINEA"; } | crontab -
"$DEPLOY/backup.sh" || aviso "La primera copia ha fallado; revise /var/log/pms-backup.log"

verde "Instalación terminada"
cat <<EOF
  Dirección:        https://$DOMINIO
  Administrador:    ver $CRED  (léalo con: cat $CRED)
  Usuarios:         entran con 00000000 y deben cambiarla al entrar
  Copias:           /var/backups/pms  (diarias a las 03:15)
  Actualizar:       cd $DIR && git pull && bash $DEPLOY/instalar.sh

  PENDIENTE: active en Arsys el backup del servidor (copia fuera de esta máquina).
EOF
