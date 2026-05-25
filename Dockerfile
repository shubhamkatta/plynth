# syntax=docker/dockerfile:1.7
# ---------- base ----------
FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# ---------- deps ----------
FROM base AS deps
COPY pyproject.toml ./
RUN pip install --upgrade pip hatchling \
 && pip install --prefix=/install \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "gunicorn>=23" \
    "pydantic>=2.9" "pydantic-settings>=2.6" \
    "sqlalchemy[asyncio]>=2.0.36" "asyncpg>=0.30" "alembic>=1.14" \
    "redis>=5.2" "arq>=0.26" "argon2-cffi>=23.1" "pyjwt[crypto]>=2.10" \
    "httpx>=0.28" "structlog>=24.4" "python-multipart>=0.0.20" \
    "email-validator>=2.2" "orjson>=3.10" "tenacity>=9.0" "stripe>=11.4"

# ---------- runtime ----------
FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/bin:$PATH
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app && adduser --system --ingroup app app

COPY --from=deps /install /usr/local
COPY --chown=app:app . /app

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "2", "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-"]
