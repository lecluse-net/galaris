# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS dsh-builder

ARG DSH_REF
ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    git \
    python3 \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@11.7.0 --activate
RUN git init /src \
    && git -C /src remote add origin https://github.com/deepseek-ai/deepseek-harness.git \
    && git -C /src fetch --depth 1 origin "${DSH_REF}" \
    && git -C /src checkout --detach FETCH_HEAD

WORKDIR /src
RUN pnpm install --frozen-lockfile
RUN pnpm run build
RUN case "${TARGETARCH}" in \
        amd64) dsh_arch=x64 ;; \
        arm64) dsh_arch=arm64 ;; \
        *) echo "Unsupported DeepSeek Harness architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && pnpm exec tsx scripts/build-exe-for-python-sdk.ts \
        --skip-build \
        --targets="node24-linux-${dsh_arch}"


FROM python:3.14-slim-trixie

ARG RUNTIME_UID=1000
ARG RUNTIME_GID=1000

# The upstream single-file carrier cannot load node-pty's native addon from its
# virtual snapshot in this container build. The source build already stages the
# complete Node carrier, so run that supported carrier from the real filesystem.
COPY --from=dsh-builder /usr/local/bin/node /usr/local/bin/node

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/dsh/python \
    DSH_RUNTIME_MODE=node \
    DSH_CWD=/workspace \
    DSH_SESSION_ROOT=/sessions \
    DSH_CORDIS_CONFIG=/opt/galaris/cordis.yml \
    HOME=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    git \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir 'pydantic==2.13.5'

COPY --from=dsh-builder /src/python/sdk/src/deepseek_harness /opt/dsh/python/deepseek_harness
COPY --from=dsh-builder /src/python/sdk-runtime/src/deepseek_harness_runtime /opt/dsh/python/deepseek_harness_runtime
COPY runtime_adapter.py /opt/galaris/runtime_adapter.py
COPY cordis.yml /opt/galaris/cordis.yml

RUN groupadd --gid "${RUNTIME_GID}" dsh \
    && useradd --uid "${RUNTIME_UID}" --gid "${RUNTIME_GID}" --home-dir /workspace dsh \
    && mkdir -p /workspace /sessions /skills \
    && chown -R dsh:dsh /workspace /sessions /skills /opt/galaris /opt/dsh

USER dsh
WORKDIR /workspace

LABEL org.galaris.harness="deepseek-harness"

EXPOSE 8080
CMD ["python", "/opt/galaris/runtime_adapter.py"]
