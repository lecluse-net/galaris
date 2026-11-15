FROM node:24-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libnss3 libatk-bridge2.0-0 libgtk-3-0 libasound2 libgbm1 \
    libxss1 xvfb xauth libfuse2 xz-utils binutils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/desktop
ENV ELECTRON_CACHE=/tmp/electron-cache ELECTRON_BUILDER_CACHE=/tmp/electron-builder-cache
COPY package*.json ./
RUN npm ci && chown -R node:node /workspace
USER node
CMD ["npm", "test"]
