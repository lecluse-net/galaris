# Keep the upstream MIT notices in the image. Upgrade tag and digest together.
FROM ghcr.io/coder/code-server:4.141.0@sha256:72ab24b5680ee597dd647b30d82625752f40109b5f61bef90ffbf1ea1f02dbb8 AS runtime

USER root
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap python3 python3-aiohttp git openssh-client tini \
    && rm -rf /var/lib/apt/lists/*

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
