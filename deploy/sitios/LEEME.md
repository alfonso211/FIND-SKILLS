# Otras webs del servidor

Cada fichero `*.caddy` de esta carpeta es una web más que atiende el mismo Caddy del PMS (con su certificado HTTPS).
Los ficheros `*.caddy` son propios del servidor: no se suben al programa y `git pull` no los toca.

Ejemplo, `invergestion.caddy`:

```
gestion.inversiete.es {
	encode gzip
	reverse_proxy invergestion:8000
}
```

Después de crear o cambiar uno: `cd /opt/pms/deploy && docker compose restart caddy`.
No modifique `deploy/Caddyfile`: las actualizaciones lo sobrescriben.
