# Keep the upstream MIT notices in the image. Upgrade tag and digest together.
FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS node-runtime
WORKDIR /security-deps
COPY security-deps/package*.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
FROM ghcr.io/coder/code-server:4.144.0@sha256:b9e8056bb74bd0c4f90284c7559eddeccd38400cfedc28e64c9d3ca50fef1f83 AS runtime

USER root
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends bubblewrap python3 python3-aiohttp git openssh-client tini \
    && rm -rf /var/lib/apt/lists/*

# The editor uses this bundled Node path. Keep its security fixes independent of
# the upstream editor release. Our supervisor owns identities; fixuid is unused.
COPY --from=node-runtime /usr/local/bin/node /usr/lib/code-server/lib/node
COPY --from=node-runtime /security-deps/node_modules/undici /usr/lib/code-server/lib/vscode/node_modules/undici
RUN rm -f /usr/local/bin/fixuid

COPY runtime.py /opt/galaris-code/runtime.py
COPY profiles.py /opt/galaris-code/profiles.py
COPY provision-credential.py /opt/galaris-code/provision-credential.py
COPY extension /usr/lib/code-server/lib/vscode/extensions/galaris.galaris-repository
# Console uploads are private (0600/0700). Editor accounts must be able to load
# the immutable built-in extension after Docker copies that deployment bundle.
RUN chmod 755 /usr/lib/code-server/lib/vscode/extensions/galaris.galaris-repository \
    && chmod 644 /usr/lib/code-server/lib/vscode/extensions/galaris.galaris-repository/*
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["python3", "/opt/galaris-code/runtime.py"]

# Test-only SSH forge. Production Compose explicitly selects the runtime target.
FROM runtime AS qualification
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 20000 -m -s /bin/bash developer \
    && echo 'developer:synthetic-unused-password' | chpasswd
