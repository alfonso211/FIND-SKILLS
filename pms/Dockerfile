FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# la aplicación no se ejecuta como root
RUN useradd --system --uid 10001 pms && chown -R pms /app
USER pms

EXPOSE 8000
# Un solo proceso: el bloqueo por intentos fallidos se lleva en memoria y la carga es baja.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
