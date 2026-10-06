# Manual de uso (mantenimiento del texto)

- Cada fichero es una sección del menú **Manual de uso** (ver `SECCIONES` en `app/routers/manual.py`).
- **Con cada actualización del programa**: añada arriba en `novedades.md` un apartado
  `## AAAA-MM-DD · Versión X.Y · resumen` con una viñeta por cambio (**puesto afectado**: qué cambia) y
  ajuste el manual del puesto afectado. El primer `## ` es la versión: al cambiar, cada usuario ve
  una vez el aviso «Novedades de esta actualización».
- Formato admitido: `#`, `##`, `###`, viñetas `- ` (con sangría para sub-viñetas), listas `1. `,
  citas `> `, **negrita**, *cursiva*.
