FROM mcr.microsoft.com/playwright:v1.62.0-noble@sha256:baed2032d533817f3dbe6425de795788430ba345e819a1201337009ba17c9d07

ENV NODE_ENV=production
WORKDIR /opt/galaris-browser

COPY package.json package-lock.json ./
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && npm install --global npm@12.0.2 --no-audit --no-fund \
    && npm --prefix /usr/lib/node_modules/npm pkg delete devDependencies \
    && npm --prefix /usr/lib/node_modules/npm update --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm ci --omit=dev --no-audit --no-fund \
    && npm cache clean --force

COPY *.mjs ./

USER pwuser
EXPOSE 3000

CMD ["node", "server.mjs"]
