# Instalación del PMS en el servidor de Arsys

Guía para el técnico que instale el PMS. Tiempo estimado: unos 45 minutos.

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

**Copia fuera del servidor (obligatoria):** active el servicio de backup de Arsys o copie a diario
`/var/backups/pms` a otro almacenamiento (p.ej. almacenamiento de objetos de Arsys o el NAS de la oficina).
Una copia que solo está en el mismo servidor no protege ante la pérdida del servidor.

**Restaurar una copia:**

```bash
cd /opt/pms/deploy
docker compose stop app
docker compose exec -T db dropdb -U pms pms
docker compose exec -T db createdb -U pms pms
docker compose exec -T db pg_restore -U pms -d pms --no-owner < /var/backups/pms/pms_AAAAMMDD_HHMM.dump
docker compose start app
```

Haga una restauración de prueba al menos una vez al trimestre.

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
