FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias del sistema operativo (necesarias para asyncpg y TruLens)
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del evaluador
COPY app/ ./app/

# El worker se ejecutará como un proceso continuo esperando llamadas del orquestador
CMD ["python", "-u",  "-m", "app.evaluator"]

