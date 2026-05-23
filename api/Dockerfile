# =====================================================================
# ETAPA 1: Compilación y descarga de dependencias (Builder)
# =====================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Instalar herramientas de compilación básicas si fuesen necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Compilar ruedas (wheels) en un directorio aislado
RUN pip install --no-cache-dir --user -r requirements.txt

# =====================================================================
# ETAPA 2: Entorno de ejecución optimizado y seguro (Runtime)
# =====================================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copiar las dependencias instaladas desde la etapa anterior
COPY --from=builder /root/.local /root/.local
COPY ./app ./app
# Nueva linea para permitir testing desde el contenedor
COPY ./tests ./tests

# Asegurar que los binarios instalados en .local entren en el PATH ejecutable
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Exponer el puerto interno por defecto de FastAPI
EXPOSE 8000

# Lanzar el servidor ASGI Uvicorn apuntando al bucle asíncrono
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
