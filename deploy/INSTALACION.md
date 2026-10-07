# Instalación del PMS en el servidor de Arsys

## Instalación rápida (sin conocimientos técnicos)

El guion `deploy/instalar.sh` hace automáticamente todo lo de los apartados 2 a 8: actualizaciones, cortafuegos,
Docker, claves, arranque, HTTPS y copias diarias. Solo hay que:

1. Entrar al servidor por SSH como root.
2. Pegar el **bloque A**, que crea la clave de acceso al repositorio, y añadir esa clave en GitHub
   (*Settings → Deploy keys*, sin marcar *Allow write access*).
3. Pegar el **bloque B**, que descarga el PMS y ejecuta el instalador.

**Bloque A**
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/pms_deploy -N "" -C pms-arsys -q
printf 'Host github-pms\n  HostName github.com\n  IdentityFile ~/.ssh/pms_deploy\n  StrictHostKeyChecking accept-new\n' >> ~/.ssh/config
cat ~/.ssh/pms_deploy.pub
```

**Bloque B**
```bash
apt-get update -qq && apt-get install -y -qq git && git clone -b main git@github-pms:alfonso211/FIND-SKILLS.git /opt/pms && bash /opt/pms/deploy/instalar.sh
```

El guion se puede repetir sin riesgo: no borra datos ni cambia las claves. Las credenciales del administrador técnico
quedan en `/root/pms-credenciales.txt`.

---

## Instalación manual paso a paso (referencia técnica)

Tiempo estimado: unos 45 minutos.

## 0. Requisitos del servidor

| Elemento | Mínimo | Recomendado |
|---|---|---|
| Producto Arsys | **Servidor Cloud o VPS con acceso root** (un *hosting* compartido **no** sirve) | |
| Sistema operativo | Ubuntu Server 22.04 LTS | **Ubuntu Server 24.04 LTS** |
| CPU / RAM | 2 vCPU / 4 GB | 4 vCPU / 8 GB |
| Disco | 40 GB SSD | 80 GB SSD |
| Red | IP pública fija | |
| Copias | | Servicio de backup de Arsys (instantánea diaria del servidor) |

## 1. DNS

En el panel donde se gestiona el dominio `inversiete.es`, cree un **registro A**:

```
pms.inversiete.es   A   <IP pública del servidor>
```

Compruébelo con `ping pms.inversiete.es` antes de seguir. Hace falta para que se emita el certificado HTTPS.

## 2. Acceso y cortafuegos

Haga lo siguiente en el panel de Arsys y en el propio servidor:

```bash
# Entrar al servidor (desde su ordenador)
ssh root@<IP>

# Actualizaciones automáticas de seguridad
apt update && apt -y upgrade && apt -y install unattended-upgrades ufw git
dpkg-reconfigure -plow unattended-upgrades

# Cortafuegos: solo SSH, HTTP y HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Recomendado: entrar por SSH solo con clave y desactivar la contraseña de root
(`PasswordAuthentication no` en `/etc/ssh/sshd_config`). Si la oficina tiene IP fija, limite el puerto 22 a esa IP
en el cortafuegos del panel de Arsys.

## 3. Docker

```bash
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

## 4. Código del PMS

El repositorio es privado. Cree una **clave de despliegue** de solo lectura:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/pms_deploy -N "" -C "pms-arsys"
cat ~/.ssh/pms_deploy.pub
```

En GitHub, entre en *alfonso211/FIND-SKILLS → Settings → Deploy keys → Add deploy key*, pegue la clave y **no** marque
"Allow write access". Después:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-pms
  HostName github.com
  IdentityFile ~/.ssh/pms_deploy
EOF
git clone git@github-pms:alfonso211/FIND-SKILLS.git /opt/pms
cd /opt/pms && git checkout main
```

## 5. Configuración

```bash
cd /opt/pms/deploy
cp .env.example .env
chmod 600 .env
# generar las tres claves:
for i in 1 2 3; do openssl rand -base64 48 | tr -d '/+=' | cut -c1-40; done
nano .env
```

En `.env` hay que rellenar:
- `PMS_DOMINIO`: `pms.inversiete.es`.
- `DB_PASSWORD`: la primera clave generada.
- `PMS_SECRET_KEY`: la segunda clave generada.
- `PMS_ADMIN_PASSWORD`: la tercera clave. Es la del administrador técnico; guárdela en el gestor de contraseñas de la empresa.

## 6. Arranque

```bash
cd /opt/pms/deploy
docker compose up -d --build
docker compose ps          # los tres servicios en estado "running" / "healthy"
docker compose logs -f app # Ctrl+C para salir
```

Abra `https://pms.inversiete.es`. El certificado tarda unos segundos la primera vez.

## 7. Primer acceso

| Usuario | Contraseña inicial |
|---|---|
| `admin@inversiete.es` (administrador técnico) | la indicada en `PMS_ADMIN_PASSWORD` |
| Dirección y recepciones (ver README) | `00000000`; el sistema obliga a cambiarla al entrar |

**Importante:** cualquiera que conozca un usuario puede entrar con `00000000` hasta que su titular cambie la
contraseña. Avise a cada usuario el mismo día de la puesta en marcha. Compruebe después en
*Administración → Usuarios* que ninguno sigue con la marca "contraseña provisional".

## 8. Copias de seguridad

**Copia diaria de la base de datos**, a las 03:15, conservando 30 días en el servidor:

```bash
crontab -e
# añadir:
15 3 * * * /opt/pms/deploy/backup.sh >> /var/log/pms-backup.log 2>&1
```

**Copia fuera del servidor (obligatoria):** una copia que solo está en el mismo servidor no protege ante la pérdida
del servidor. `backup.sh` sube cada copia, **cifrada**, a Google Drive (carpeta `CopiasPMS`, 90 días) si existe el
remoto de rclone `pmscopia`. Configuración, una sola vez:

```bash
apt install -y rclone
# desde el ordenador, entrar con un túnel para la autorización de Google:  ssh -L 53682:localhost:53682 root@<IP>
rclone config create pmsdrive drive scope drive.file
#   → abrir en el navegador del ordenador el enlace http://127.0.0.1:53682/auth?... y autorizar con la cuenta de Google
read -s -p "Contraseña de cifrado de las copias: " P && rclone config create pmscopia crypt remote pmsdrive:CopiasPMS \
  filename_encryption off directory_name_encryption false password "$P" --obscure > /dev/null && unset P
/opt/pms/deploy/backup.sh     # debe terminar con «subida a Google Drive OK»
```

En Drive los ficheros se ven con su fecha (`pms_AAAAMMDD_HHMM.dump.bin`) pero su contenido está cifrado: sin la
**contraseña de cifrado de las copias** no se pueden abrir. Guárdela en papel junto a `PMS_DOCS_KEY`.

**Recuperar desde Google Drive** (servidor nuevo: instalar rclone y repetir la configuración con la misma contraseña):

```bash
rclone copy pmscopia: /var/backups/pms --include "*AAAAMMDD_HHMM*"
```

**Restaurar una copia:**

```bash
cd /opt/pms/deploy
docker compose stop app
docker compose exec -T db dropdb -U pms pms
docker compose exec -T db createdb -U pms pms
docker compose exec -T db pg_restore -U pms -d pms --no-owner < /var/backups/pms/pms_AAAAMMDD_HHMM.dump
docker compose start app
# documentos escaneados (cifrados con PMS_DOCS_KEY), con la aplicación ya arrancada:
docker compose exec -T app tar xzf - -C /data < /var/backups/pms/documentos_AAAAMMDD_HHMM.tar.gz
```

Haga una restauración de prueba al menos una vez al trimestre.

## 8 bis. Clave de cifrado de documentos de identidad

Las copias escaneadas de DNI y pasaportes se guardan **cifradas** con la clave `PMS_DOCS_KEY` del fichero `.env`.
El instalador la genera automáticamente y la deja en `/root/pms-credenciales.txt`.

- **Guárdela fuera del servidor**, en el gestor de contraseñas de la empresa, y borre después ese fichero.
- **Sin esa clave no se pueden recuperar las copias de los documentos**, ni siquiera desde las copias de seguridad.
- **No la cambie** una vez haya documentos guardados.

Las copias de seguridad diarias incluyen la carpeta de documentos (`/var/backups/pms/documentos_*.tar.gz`).

## 8 ter. Avisos por correo

El PMS envía avisos de **OT urgentes** al momento y un **resumen diario** (recibos impagados, contratos que vencen y
revisiones normativas próximas). Para ello necesita un buzón de correo desde el que enviar, por ejemplo
`avisos@inversiete.es` (créelo en el proveedor de correo de la empresa).

1. Edite el fichero de configuración:
   ```bash
   nano /opt/pms/deploy/.env
   ```
2. Rellene las líneas `PMS_SMTP_...` con los datos del buzón:

   | Proveedor del correo | PMS_SMTP_HOST | PMS_SMTP_PORT | PMS_SMTP_SEGURIDAD |
   |---|---|---|---|
   | IONOS | `smtp.ionos.es` | 587 | starttls |
   | Microsoft 365 / Outlook | `smtp.office365.com` | 587 | starttls |
   | Arsys | `smtp.servidor-correo.net` | 587 | starttls |

   ```
   PMS_SMTP_HOST=smtp.ionos.es
   PMS_SMTP_PORT=587
   PMS_SMTP_USER=avisos@inversiete.es
   PMS_SMTP_PASSWORD=la-contraseña-del-buzón
   PMS_SMTP_FROM=avisos@inversiete.es
   PMS_SMTP_SEGURIDAD=starttls
   PMS_AVISOS_HORA=07:30
   ```
   Guarde con `Ctrl + O`, `Intro` y salga con `Ctrl + X`.
3. Aplique el cambio: `cd /opt/pms/deploy && docker compose up -d`
4. En el PMS, *Administración → Avisos por correo → Enviarme un correo de prueba*. Si falla, el mensaje indica el
   motivo (usuario o contraseña incorrectos, servidor...).

En Microsoft 365 el buzón debe tener activado «SMTP autenticado» (centro de administración de Microsoft 365 →
usuario → Correo → Administrar aplicaciones de correo).

Cada usuario elige qué avisos recibe en *Mi perfil*.

## 8 quater. Registro de viajeros, encuesta del INE y firma en tablet

- **SES.HOSPEDAJE:** en *Activos → Editar* de cada Suite, indique el **código de establecimiento** que asigna el
  Ministerio del Interior. El fichero que genera *Parte de viajeros (SES)* se carga en
  https://hospedajes.ses.mir.es (*Comunicaciones → Carga de ficheros*). Plazo: 24 horas desde la llegada.
- **INE:** *Informes Excel → Encuesta del INE* prepara el cuestionario mensual de ocupación en apartamentos
  turísticos para trasladarlo a IRIA. Para que las plazas sean correctas, indique la capacidad de cada apartamento.
- **Firma en tablet:** la imagen Docker incluye LibreOffice para convertir el contrato a PDF (la primera
  actualización tarda unos minutos más en construirse). El enlace de descarga que recibe el cliente usa el dominio
  del PMS (`PMS_URL`, ya configurado en `docker-compose.yml`). El envío por correo usa la
  configuración del apartado 8 ter; el de WhatsApp abre WhatsApp en la tablet con el mensaje y el enlace preparados
  (caduca a los 7 días).

## 8 quinquies. Mantenimiento diario automático

Cada día a las **06:00 (hora de Madrid)** `mantenimiento.sh` revisa el servidor y el PMS, arregla solo lo que puede
y avisa por correo a `PMS_MANTENIMIENTO_EMAIL` (por defecto alfonso@inversiete.es). Activarlo una sola vez:

```bash
/opt/pms/deploy/mantenimiento.sh --instalar   # lo programa en cron
/opt/pms/deploy/mantenimiento.sh              # primera revisión a mano: muestra el informe
```

| Revisa | Si falla, lo arregla solo | Si no puede: correo URGENTE |
|---|---|---|
| Docker y contenedores db, app, caddy | arranca Docker, reinicia el contenedor | no arranca |
| Acceso https y certificado | reinicia el proxy, fuerza la renovación | no responde, caduca en menos de 7 días |
| Disco y memoria | borra imágenes, registros y paquetes antiguos | disco al 90 % o más |
| Copias de seguridad (servidor y Google Drive) | programa la copia diaria, hace la copia que falte | sin copia de 24 h o sin subir a Drive |
| Base de datos y su versión | aplica las migraciones pendientes | la migración falla |
| Documentos cifrados (presentes y legibles) | — | falta alguno o no se descifra |
| Correo de avisos | — | el servidor de correo rechaza la conexión |
| Seguridad: cortafuegos, permisos del .env | activa ufw (SSH, 80, 443), pone el .env en 600 | — |

Son **avisos** (correo normal, solo la primera vez que aparecen): actualizaciones automáticas desactivadas, reinicio
pendiente por actualizaciones, puertos abiertos no previstos, SSH con contraseña sin fail2ban, usuarios con contraseña
provisional, cuelgues, errores en el registro y ficheros modificados a mano en `/opt/pms`. Si arregla algo, también
lo comunica. Los **lunes** envía un resumen aunque todo esté bien, para confirmar que el mantenimiento sigue en marcha.
Nunca reinicia el servidor ni instala programas por su cuenta.

- Último informe: `cat /var/lib/pms-mantenimiento/ultimo.txt`. Histórico: `/var/log/pms-mantenimiento.log`.
- Si no llega ningún correo un lunes, revisar el histórico y la configuración del correo (apartado 8 ter).

## 9. Actualizaciones del PMS

```bash
cd /opt/pms && git pull
cd deploy && /opt/pms/deploy/backup.sh && docker compose up -d --build
```

## 10. Comprobación final

- [ ] `https://pms.inversiete.es` abre con candado (HTTPS válido).
- [ ] `http://pms.inversiete.es` redirige a HTTPS.
- [ ] Desde fuera del servidor no responden los puertos 5432 (base de datos) ni 8000 (aplicación).
- [ ] El administrador técnico entra correctamente.
- [ ] `backup.sh` se ha ejecutado a mano una vez y ha generado un fichero en `/var/backups/pms`.
- [ ] La copia fuera del servidor está configurada.
- [ ] Todos los usuarios iniciales han cambiado su contraseña.

## Si el PMS se cuelga

El PMS se vigila solo. Si deja de responder, guarda un diagnóstico y se reinicia en menos de 3 minutos, sin perder datos.

- Comprobar que responde: `docker ps`. La aplicación debe salir como `(healthy)`.
- Ver los avisos del vigilante: `cd /opt/pms/deploy && docker compose logs app | grep -E "COLGADO|lenta|Sin turno|Base de datos"`.
- Leer los diagnósticos guardados: `docker compose exec app ls /data/documentos/_diagnostico`. Para ver uno: `docker compose exec app cat /data/documentos/_diagnostico/<fichero>`.
- Reinicio manual si hiciera falta: `docker compose restart app`.
