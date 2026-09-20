FROM python:3.12-slim

ARG RUNTIME_UID=1000
ARG RUNTIME_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid "${RUNTIME_GID}" agent \
    && useradd --uid "${RUNTIME_UID}" --gid "${RUNTIME_GID}" --create-home agent

WORKDIR /opt/claude-agent
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade --no-cache-dir -r requirements.txt \
    && pip freeze > requirements-resolved.txt

COPY server.py.txt ./server.py
COPY stream_trace.py ./stream_trace.py
RUN mkdir -p /data/claude /data/skills /data/workspace \
    && chown -R agent:agent /data /opt/claude-agent

USER agent
EXPOSE 8642

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8642"]
