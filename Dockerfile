# Multi-stage Dockerfile for Knowledge Distillation Telegram AI Bot

# Stage 1: Builder - compile wheels and install dependencies
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --extra-index-url https://download.pytorch.org/whl/cpu torch -r requirements.txt

# Stage 2: Runtime - minimal image with non-root user
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home appuser

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser . .

USER appuser

CMD ["python", "main.py"]

