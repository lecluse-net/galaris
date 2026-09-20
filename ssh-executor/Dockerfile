FROM debian:trixie-20260623-slim@sha256:28de0877c2189802884ccd20f15ee41c203573bd87bb6b883f5f46362d24c5c2

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        coreutils \
        curl \
        git \
        jq \
        openssh-client \
        openssh-server \
        procps \
        python3 \
        python3-dev \
        python3-venv \
        rsync \
        tini \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY sshd_config /etc/ssh/sshd_config
COPY executord.py /opt/galaris-executor/executord.py
COPY --from=console_assets galaris-exec /usr/local/bin/galaris-exec
COPY entrypoint.sh /usr/local/bin/galaris-executor-entrypoint

RUN chmod 0755 \
        /opt/galaris-executor/executord.py \
        /usr/local/bin/galaris-exec \
        /usr/local/bin/galaris-executor-entrypoint \
    && mkdir -p \
        /data/ssh-executor/home \
        /data/ssh-executor/run \
        /data/ssh-executor/state/authorized_keys \
        /data/ssh-executor/state/host_keys

EXPOSE 22

ENTRYPOINT ["/usr/local/bin/galaris-executor-entrypoint"]
