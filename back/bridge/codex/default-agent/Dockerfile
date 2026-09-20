FROM python:3.14-slim-trixie

ARG APP_UID=10001
ARG APP_GID=10001

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git make ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/codex-harness
COPY requirements.txt ./
RUN pip install --upgrade --no-cache-dir --requirement requirements.txt \
    && pip freeze > requirements-resolved.txt
COPY server.py stream_trace.py ./

RUN mkdir -p /workspace /var/lib/codex \
    && chown -R "${APP_UID}:${APP_GID}" /workspace /var/lib/codex /opt/codex-harness

ENV HOME=/var/lib/codex
USER ${APP_UID}:${APP_GID}
EXPOSE 8787

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
