FROM ubuntu:26.04@sha256:6a06111c3b0a8600feadb270aec771dc239bf407b25625f93f44ab00e11f4d3c AS base

# Reserve the development UID for the existing app user contract.
RUN if id ubuntu >/dev/null 2>&1; then userdel -r ubuntu; fi

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
    python3.14 python3.14-venv python-is-python3 ca-certificates curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /bin/uv

# Install Atlas
COPY --from=arigaio/atlas@sha256:bafdd9c5921bd717626b5411fd0895e723702e638186e3f71bfb8299c043fa3a /atlas /bin/atlas

# Install system dependencies
# Keep dump/restore tools on the server's PostgreSQL major version.
RUN install -d /usr/share/keyrings \
    && curl --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/keyrings/pgdg.asc \
    && echo '0144068502a1eddd2a0280ede10ef607d1ec592ce819940991203941564e8e76  /usr/share/keyrings/pgdg.asc' | sha256sum -c - \
    && printf '%s\n' 'deb [signed-by=/usr/share/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt resolute-pgdg main' > /etc/apt/sources.list.d/pgdg.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    libasound2-plugins \
    libpq5 \
    pulseaudio \
    pulseaudio-utils \
    postgresql-client-17 \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-draw \
    pandoc \
    fonts-liberation \
    fonts-dejavu-core \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
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
COPY --from=code_executor Dockerfile runtime.py profiles.py provision-credential.py deploy.py /opt/galaris-code-deployment/
COPY --from=code_executor extension/ /opt/galaris-code-deployment/extension/
COPY --from=code_executor security-deps/ /opt/galaris-code-deployment/security-deps/
COPY --from=product_docs . /opt/galaris-documentation/docs/
COPY --from=project_docs decisions/ /opt/galaris-documentation/project/decisions/
COPY --from=project_docs plans/ /opt/galaris-documentation/project/plans/

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
    mkdir -p /data /tmp/galaris-cache && \
    chown app:app /data /tmp/galaris-cache

# Override venv location to be outside /app (avoid volume mount overwrite)
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    XDG_CACHE_HOME=/tmp/galaris-cache

# Copy the completed environment; production never installs build dependencies.
COPY --from=prod-builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app . /app/
# Only distributable files, never host .env, instances or local environments.
COPY --from=harness_manager main.py update.py Makefile pyproject.toml uv.lock README.md .env.example /opt/galaris-harness-manager/
COPY --from=code_executor Dockerfile runtime.py profiles.py provision-credential.py deploy.py /opt/galaris-code-deployment/
COPY --from=code_executor extension/ /opt/galaris-code-deployment/extension/
COPY --from=code_executor security-deps/ /opt/galaris-code-deployment/security-deps/
COPY --from=product_docs . /opt/galaris-documentation/docs/
COPY --from=project_docs decisions/ /opt/galaris-documentation/project/decisions/
COPY --from=project_docs plans/ /opt/galaris-documentation/project/plans/

# The distribution interpreter has no global pip; uv owns the application venv.
RUN chmod +x /app/entrypoint.sh

USER app

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
