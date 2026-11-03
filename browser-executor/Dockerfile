FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e

ENV NODE_ENV=production
WORKDIR /opt/galaris-browser

COPY package.json package-lock.json ./
# Only Chromium is used; GStreamer Bad codecs belong to unused WebKit support.
RUN apt-get update && apt-get upgrade -y \
    && apt-get purge -y gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0 \
    && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/* \
    && npm install --global npm@12.0.2 --no-audit --no-fund \
    && npm --prefix /usr/lib/node_modules/npm pkg delete devDependencies \
    && npm --prefix /usr/lib/node_modules/npm update --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm ci --omit=dev --no-audit --no-fund \
    && npm cache clean --force

COPY *.mjs ./

USER pwuser
EXPOSE 3000

CMD ["node", "server.mjs"]
