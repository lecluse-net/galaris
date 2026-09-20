FROM python:3.14-slim-trixie@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS base

ARG GALARIS_BUILD_VERSION=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPYCACHEPREFIX=/tmp/pycache \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    TZ=UTC

RUN printf '%s\n' "$GALARIS_BUILD_VERSION" > /opt/galaris-version

# Apply available security updates to the pinned base before installing packages.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /bin/uv

# Install Atlas
COPY --from=arigaio/atlas@sha256:15cd73c56b2a8d8d7d5e8176df4d50bb190dc5ae4a12afd1043f1a5560dd7456 /atlas /bin/atlas

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    libasound2-plugins \
    libpq5 \
    pulseaudio \
    pulseaudio-utils \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Compilers stay in build stages, never in the production image.
FROM base AS build-tools

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Builder stage (for dev with build tools)
# -----------------------------
FROM build-tools AS builder

# Build argument for user ID (to match host user for dev volumes)
ARG USER_ID=1000

# Create app user with specified UID for dev
RUN addgroup --system app && \
    adduser --system --ingroup app --uid ${USER_ID} app && \
    chown -R app:app /app

# Install dependencies only (without project) for layer caching
COPY pyproject.toml ./
COPY uv.lock ./
RUN uv sync --frozen --no-cache --no-install-project --group dev

# Copy source and install project
COPY . .
RUN uv sync --frozen --no-cache

# Keep manager-only changes outside the dependency installation layers.
COPY --from=harness_manager main.py update.py Makefile pyproject.toml uv.lock README.md .env.example /opt/galaris-harness-manager/

# -----------------------------
# Production dependencies, cached independently of application source changes.
# -----------------------------
FROM build-tools AS prod-builder

ENV UV_PROJECT_ENVIRONMENT=/opt/venv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-cache --no-dev

# -----------------------------
# Production stage
# -----------------------------
FROM base AS prod-stage

# Create the non-root production user and pre-own the persistent data mount.
# Docker preserves this ownership when it initializes an empty named volume.
RUN addgroup --system app && \
    adduser --system --ingroup app app && \
    mkdir -p /data && \
    chown app:app /data

# Override venv location to be outside /app (avoid volume mount overwrite)
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Copy the completed environment; production never installs build dependencies.
COPY --from=prod-builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app . /app/
# Only distributable files, never host .env, instances or local environments.
COPY --from=harness_manager main.py update.py Makefile pyproject.toml uv.lock README.md .env.example /opt/galaris-harness-manager/

RUN chmod +x /app/entrypoint.sh && \
    /usr/local/bin/python -m pip uninstall -y pip

USER app

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
