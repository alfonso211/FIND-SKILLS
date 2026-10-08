# INVERPMS · Guía de emergencia: recuperar y reparar el sistema

**Grupo INVERSIETE · Dirección Técnica.** Imprima esta guía y guárdela en papel junto al sobre de claves. Si el
servidor se cae, la versión que está dentro del servidor no se podrá consultar.

---

## 0. Antes de que pase nada: el «kit de emergencia»

Sin estos datos no se puede recuperar el sistema. Guárdelos **fuera del servidor**, en dos sitios: el gestor de
contraseñas de la empresa y un sobre cerrado en la caja fuerte. **Esta guía no contiene ninguna clave.**

| # | Dato | Para qué sirve | Si se pierde |
|---|---|---|---|
| 1 | Acceso al **panel de Arsys** (usuario y contraseña) | Reiniciar el servidor, crear uno nuevo, ver la consola | Llamar a Arsys con el CIF de la empresa |
| 2 | Contraseña de **root** del servidor | Entrar por SSH | Se cambia desde el panel de Arsys |
| 3 | Acceso a **GitHub** (cuenta `alfonso211`) | Descargar el programa (repositorio `alfonso211/FIND-SKILLS`) | Recuperar la cuenta con GitHub |
| 4 | Acceso al **panel del dominio** `inversiete.es` (IONOS) | Apuntar `pms.inversiete.es` a un servidor nuevo | Llamar al proveedor del dominio |
| 5 | Cuenta de **Google** donde están las copias (carpeta `CopiasPMS`) | Descargar las copias fuera del servidor | Recuperar la cuenta con Google |
| 6 | **Contraseña de cifrado de las copias** (rclone) | Abrir las copias guardadas en Google Drive | **Las copias de Drive no se pueden abrir. Nunca.** |
| 7 | **`PMS_DOCS_KEY`** (fichero `.env`) | Abrir los documentos escaneados (DNI, facturas, contratos firmados) | **Los documentos escaneados no se pueden abrir. Nunca.** |
| 8 | El resto del fichero **`.env`** (`DB_PASSWORD`, `PMS_SECRET_KEY`, `PMS_ADMIN_PASSWORD`, datos `PMS_SMTP_…`) | Configuración del servidor | Se generan de nuevo (los usuarios vuelven a entrar) |

> **Los datos 6 y 7 son los únicos imprescindibles.** Todo lo demás se puede regenerar o pedir al proveedor.
> Compruebe hoy mismo que los tiene fuera del servidor. Para ver el `.env` actual (desde el servidor):
> `cat /opt/pms/deploy/.env` → cópielo al gestor de contraseñas. No lo envíe por correo ni por WhatsApp.

### Cómo se protege el sistema solo (ya funcionando)

- **Copia diaria automática** de la base de datos y de los documentos, de madrugada. Se guarda en el servidor
  (`/var/backups/pms`, 30 días) y, **cifrada**, en Google Drive (`CopiasPMS`, 90 días).
- **Copia antes de cada actualización** (el comando de despliegue ejecuta `backup.sh` antes de nada).
- **Mantenimiento diario a las 06:00**: revisa todo, arregla lo que puede y envía un **correo URGENTE** si hay un fallo
  grave. Los lunes llega un resumen aunque todo esté bien. **Si un lunes no llega, algo pasa.**
- Recomendado: activar en Arsys la **copia del servidor completo** (instantánea diaria). Es otra red de seguridad.

---

## 1. ¿Qué ha pasado? Elija su caso

| Lo que ve | Caso | Vaya a |
|---|---|---|
| La web no carga, pero el servidor existe | **A. El PMS no responde** | Apartado 2 |
| Funciona, pero se han borrado o estropeado datos | **B. Datos dañados o borrados** | Apartado 3 |
| El servidor no arranca, no existe o Arsys lo ha perdido | **C. Servidor perdido** | Apartado 4 |
| Virus, ransomware, accesos extraños, datos cifrados, cambios que nadie ha hecho | **D. Ataque o virus** | Apartado 5 |

Ante la duda, **no borre nada** y empiece por el apartado 2.

---

## 2. Caso A · El PMS no responde (el servidor sigue ahí)

Es lo más habitual y casi siempre se arregla en 5 minutos.

1. Abra una terminal en su ordenador y entre al servidor:
   ```
   ssh root@31.70.155.45
   ```
   (Pide la contraseña de root. Si no deja entrar, vaya al punto 6.)
2. Mire cómo están las tres piezas del PMS:
   ```
   cd /opt/pms/deploy && docker compose ps
   ```
   Deben salir `db`, `app` y `caddy` como **running** o **healthy**.
3. Si alguna está parada o *unhealthy*, vuelva a arrancarlo todo:
   ```
   docker compose up -d
   ```
   Espere 1 minuto y pruebe la web: `https://pms.inversiete.es`.
4. Si sigue sin funcionar, mire el motivo:
   ```
   docker compose logs --tail=60 app
   ```
   Copie lo que salga (sin claves) para el soporte técnico.
5. Ejecute el mantenimiento a mano: revisa y arregla lo habitual (disco lleno, contenedores, certificado):
   ```
   /opt/pms/deploy/mantenimiento.sh
   ```
6. **Si no puede entrar por SSH**: en el **panel de Arsys** → su servidor → **Reiniciar**. Espere 3 minutos y repita
   desde el paso 1. El PMS arranca solo con el servidor.
7. Si el disco está lleno (`df -h /` muestra 100 %):
   ```
   docker image prune -af && docker builder prune -af && journalctl --vacuum-size=200M
   ```

Si nada de esto funciona en 30 minutos, pase al **caso C** (montar un servidor nuevo con la última copia).

---

## 3. Caso B · Datos borrados o estropeados (el sistema funciona)

Se vuelve a la copia de una fecha anterior al problema. **Se pierde lo que se registró después de esa copia.**

1. Entre al servidor (`ssh root@31.70.155.45`) y vea las copias disponibles (fecha y hora en el nombre):
   ```
   ls -lh /var/backups/pms/
   ```
   Ejemplo: `pms_20261007_0315.dump` = 7 de octubre de 2026 a las 03:15 (hora del servidor, UTC).
2. **Haga primero una copia del estado actual**, por si hay que volver atrás:
   ```
   /opt/pms/deploy/backup.sh
   ```
3. Avise al equipo de que el PMS estará parado unos minutos y restaure la copia elegida (cambie la fecha por la suya):
   ```
   cd /opt/pms/deploy
   COPIA=/var/backups/pms/pms_AAAAMMDD_HHMM.dump
   docker compose stop app
   docker compose exec -T db dropdb -U pms pms
   docker compose exec -T db createdb -U pms pms
   docker compose exec -T db pg_restore -U pms -d pms --no-owner < $COPIA
   docker compose start app
   ```
4. Solo si también se perdieron **documentos escaneados**, restaure su carpeta (misma fecha):
   ```
   docker compose exec -T app tar xzf - -C /data < /var/backups/pms/documentos_AAAAMMDD_HHMM.tar.gz
   ```
5. Compruebe en el PMS que los datos están y que un documento escaneado se abre. Vuelva a registrar lo que se hizo
   después de la hora de la copia.

Si la copia que necesita ya no está en el servidor (más de 30 días), descárguela de Google Drive como en el apartado 4.5.

---

## 4. Caso C · Servidor perdido: montar uno nuevo y recuperar los datos

Tiempo: unas 2 horas. Necesita el **kit de emergencia** (apartado 0).

### 4.1 Servidor nuevo

1. En el **panel de Arsys**, cree un servidor **Ubuntu Server 24.04 LTS** (mínimo 2 vCPU, 4 GB de RAM y 40 GB de disco;
   recomendado 4 vCPU y 8 GB). Anote su **IP pública**.
2. En el **panel del dominio** (IONOS), cambie el registro **A** de `pms.inversiete.es` a la IP nueva. Si existe un
   registro **AAAA** (IPv6) para `pms`, bórrelo. El cambio tarda entre 5 minutos y 1 hora.
3. Entre al servidor nuevo:
   ```
   ssh root@<IP nueva>
   ```

### 4.2 Descargar el programa

4. Cree la clave de acceso al repositorio y muéstrela:
   ```
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   ssh-keygen -t ed25519 -f ~/.ssh/pms_deploy -N "" -C pms-arsys -q
   printf 'Host github-pms\n  HostName github.com\n  IdentityFile ~/.ssh/pms_deploy\n  StrictHostKeyChecking accept-new\n' >> ~/.ssh/config
   cat ~/.ssh/pms_deploy.pub
   ```
   En GitHub: `alfonso211/FIND-SKILLS` → **Settings → Deploy keys → Add deploy key**. Pegue la línea que empieza por
   `ssh-ed25519`, **sin** marcar *Allow write access*. **Borre la clave antigua** del servidor perdido.
5. Descargue el programa (todavía **no** lo instale):
   ```
   apt-get update -qq && apt-get install -y -qq git && git clone -b main git@github-pms:alfonso211/FIND-SKILLS.git /opt/pms
   ```

### 4.3 Poner las claves de siempre (antes de instalar)

6. Cree el fichero de configuración con los datos del kit de emergencia:
   ```
   cd /opt/pms/deploy && cp .env.example .env && chmod 600 .env && nano .env
   ```
   - `PMS_DOCS_KEY`: **la de siempre** (dato 7). **No invente una nueva**, o los documentos escaneados no se abrirán.
   - `PMS_DOMINIO=pms.inversiete.es`.
   - `DB_PASSWORD`, `PMS_SECRET_KEY` y `PMS_ADMIN_PASSWORD`: los de siempre o, si no los tiene, claves nuevas (genere
     tres con `for i in 1 2 3; do openssl rand -base64 48 | tr -d '/+=' | cut -c1-40; done`).
   - Datos del correo `PMS_SMTP_…` y `PMS_MANTENIMIENTO_EMAIL=alfonso@inversiete.es`.

   Guarde con `Ctrl + O`, `Intro` y salga con `Ctrl + X`.

### 4.4 Instalar

7. Ejecute el instalador. Respeta el `.env` que acaba de crear y deja el PMS arrancado, con HTTPS y la copia diaria
   programada:
   ```
   bash /opt/pms/deploy/instalar.sh
   ```
   Al terminar, el PMS funciona pero **vacío**. Ahora se recuperan los datos.

   Si en el servidor había **otras webs** (por ejemplo INVERGESTION en `gestion.inversiete.es`), vuelva a crear su
   fichero en `/opt/pms/deploy/sitios/` (ver `LEEME.md` de esa carpeta) y reinicie Caddy:
   `cd /opt/pms/deploy && docker compose restart caddy`. La aplicación de INVERGESTION se recupera con su propia guía.

### 4.5 Recuperar las copias desde Google Drive

8. Instale rclone y conéctelo a la cuenta de Google de las copias (dato 5). Hace falta un túnel desde **su ordenador**:
   abra **otra** terminal en su ordenador y escriba `ssh -L 53682:localhost:53682 root@<IP nueva>`. En esa terminal:
   ```
   apt install -y rclone
   rclone config create pmsdrive drive scope drive.file
   ```
   Abra en el navegador de su ordenador el enlace `http://127.0.0.1:53682/auth?...` que aparece y autorice con la cuenta
   de Google de las copias.
9. Conecte la carpeta cifrada con la **contraseña de cifrado de las copias** (dato 6):
   ```
   read -s -p "Contraseña de cifrado de las copias: " P && rclone config create pmscopia crypt remote pmsdrive:CopiasPMS filename_encryption off directory_name_encryption false password "$P" --obscure > /dev/null && unset P
   ```
10. Vea las copias disponibles (las más recientes, al final) y descargue la última:
    ```
    rclone ls pmscopia: | sort -k2 | tail -6
    mkdir -p /var/backups/pms
    rclone copy pmscopia: /var/backups/pms --include "*AAAAMMDD_HHMM*"
    ls -lh /var/backups/pms
    ```
    Deben aparecer `pms_AAAAMMDD_HHMM.dump` y `documentos_AAAAMMDD_HHMM.tar.gz`. Si sale un error de contraseña, el
    dato 6 no es correcto.

### 4.6 Restaurar

11. Restaure la base de datos y los documentos (cambie la fecha por la descargada):
    ```
    cd /opt/pms/deploy
    F=AAAAMMDD_HHMM
    docker compose stop app
    docker compose exec -T db dropdb -U pms pms
    docker compose exec -T db createdb -U pms pms
    docker compose exec -T db pg_restore -U pms -d pms --no-owner < /var/backups/pms/pms_$F.dump
    docker compose start app
    sleep 20
    docker compose exec -T app tar xzf - -C /data < /var/backups/pms/documentos_$F.tar.gz
    ```
12. Active el mantenimiento diario y haga una revisión completa:
    ```
    /opt/pms/deploy/mantenimiento.sh --instalar
    /opt/pms/deploy/mantenimiento.sh
    ```
    Todo debe salir **OK** o **ARREGLADO**. Si sale «No se pueden descifrar» en Documentos, la `PMS_DOCS_KEY` del
    `.env` no es la de siempre: corríjala y ejecute `docker compose up -d`.

### 4.7 Comprobar y avisar

13. Entre en `https://pms.inversiete.es` (candado en el navegador) y compruebe:
    - Que las últimas reservas, facturas y órdenes de trabajo están.
    - Que un documento escaneado (por ejemplo, un DNI de un huésped) se abre.
    - Que llega el correo de prueba: **Administración → Avisos por correo → Enviarme un correo de prueba**.
14. Avise al equipo: los datos son los de la hora de la copia. Lo hecho después hay que volver a registrarlo.
    Si cambió `PMS_SECRET_KEY`, todos tendrán que volver a iniciar sesión.

---

## 5. Caso D · Virus, ataque o sospecha de intrusión

**Regla de oro: no se arregla un servidor infectado. Se aísla y se monta uno nuevo y limpio.**

### 5.1 En los primeros minutos

1. **No apague ni borre el servidor** (sirve como prueba), pero **aíslelo**: en el **panel de Arsys** desconecte la red
   pública o bloquee todo el tráfico en el cortafuegos del panel.
2. **No pague ningún rescate.** Las copias de Google Drive están cifradas y fuera del servidor: el atacante no las puede
   usar.
3. Anote la hora en que se detectó y lo que se ha visto (mensajes, ficheros cifrados, usuarios extraños).

### 5.2 Montar el sistema limpio

4. Siga el **caso C completo** en un **servidor nuevo**. Hay dos diferencias:
   - En los apartados 4.5 y 4.6, elija una copia **de antes del ataque**. Si no está claro cuándo empezó, coja la de 2 o 3 días antes.
   - En el apartado 4.3, ponga **claves nuevas** en todo **salvo** `PMS_DOCS_KEY`, que es imprescindible para abrir los
     documentos.

### 5.3 Cambiar todas las contraseñas

5. Desde un ordenador limpio, cambie:
   - La contraseña de **root** del servidor nuevo y la del **panel de Arsys**.
   - La contraseña de **GitHub**. Revise *Settings → Deploy keys* y *SSH keys* y borre todo lo que no reconozca.
   - La contraseña de la cuenta de **Google** de las copias. Revoque el acceso de **rclone** en
     *myaccount.google.com → Seguridad → Aplicaciones con acceso* y vuelva a autorizar (apartado 4.5).
   - La contraseña del **buzón de correo** de avisos (`PMS_SMTP_PASSWORD`).
   - Las contraseñas de **todos los usuarios del PMS**: en *Administración → Usuarios*, póngalas provisionales para que
     cada uno la cambie al entrar.
6. **Protección de datos (RGPD)**: el PMS guarda datos de huéspedes e inquilinos. Si hay sospecha de que se han robado
   o expuesto, hay **72 horas** para notificarlo a la **Agencia Española de Protección de Datos** (sede.aepd.gob.es).
   Consulte al asesor jurídico ese mismo día.
7. Denuncie el incidente (Policía Nacional o Guardia Civil, delitos telemáticos) y, si se quiere, comuníquelo a
   **INCIBE** (017, línea gratuita de ayuda en ciberseguridad).

### 5.4 Después

8. Revise con el soporte técnico cómo entraron. Lo más habitual es una **contraseña de root débil o filtrada**.
   Recomendado: entrar por SSH solo con clave (sin contraseña) e instalar `fail2ban`. El mantenimiento diario avisa si
   faltan.

---

## 6. Simulacro: una vez al trimestre

Una copia que nunca se ha probado no es una copia. Cada tres meses:

1. Cree en Arsys un servidor de prueba pequeño, o use un ordenador con Docker.
2. Siga el **caso C** sin cambiar el DNS. Para entrar, use la IP del servidor de prueba (aunque el navegador avise del
   certificado).
3. Compruebe que los datos y los documentos se abren.
4. **Borre el servidor de prueba** y anote en la tabla la fecha y el resultado.

| Fecha | Copia usada | ¿Datos OK? | ¿Documentos OK? | Responsable |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |

---

## 7. Datos de referencia (sin claves)

| Concepto | Valor |
|---|---|
| Web | `https://pms.inversiete.es` |
| Servidor actual | Arsys · `31.70.155.45` · Ubuntu · usuario `root` |
| Programa | GitHub `alfonso211/FIND-SKILLS`, rama `main` · en el servidor: `/opt/pms` |
| Configuración y claves | `/opt/pms/deploy/.env` (copia en el gestor de contraseñas) |
| Copias en el servidor | `/var/backups/pms` · 30 días · registro en `/var/log/pms-backup.log` |
| Copias fuera | Google Drive, carpeta `CopiasPMS`, cifradas (rclone `pmscopia:`) · 90 días |
| Mantenimiento diario | 06:00 (Madrid) · `/opt/pms/deploy/mantenimiento.sh` · informe en `/var/lib/pms-mantenimiento/ultimo.txt` |
| Actualizar el PMS | `cd /opt/pms && git pull && cd deploy && /opt/pms/deploy/backup.sh && docker compose up -d --build` |
| Avisos urgentes | `alfonso@inversiete.es` |
