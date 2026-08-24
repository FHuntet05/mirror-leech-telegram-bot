# syntax=docker/dockerfile:1
FROM anasty17/mltb:latest

WORKDIR /app
RUN chmod 777 /app

# Instalar UV (motor ultra-rápido en Rust para instalaciones y caché instantáneos)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Crear venv
RUN uv venv mltbenv

# Copiar únicamente requirements.txt para maximizar el uso de caché de capas de Docker
COPY requirements.txt .

# Instalar dependencias con UV y caché persistente de BuildKit
# Al no cambiar requirements.txt, Docker salta este paso al 100% en 0 segundos.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python mltbenv/bin/python -r requirements.txt

# Copiar el resto del código fuente del proyecto
COPY . .

RUN sed -i 's/\r$//' *.sh

CMD ["bash", "start.sh"]
