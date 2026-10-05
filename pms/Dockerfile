FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Lectura de documentos de identidad (OCR) y conversión de los contratos a PDF para firmarlos en tablet
# (LibreOffice), todo en el propio servidor. Fuentes compatibles con Arial.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
       libreoffice-writer-nogui fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY alembic.ini ./
COPY migrations ./migrations

# la aplicación no se ejecuta como root
RUN useradd --system --uid 10001 --create-home pms && mkdir -p /data/documentos && chown -R pms /app /data/documentos
USER pms

EXPOSE 8000
# Un solo proceso: el bloqueo por intentos fallidos se lleva en memoria y la carga es baja.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
