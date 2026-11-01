FROM node:26-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94
WORKDIR /tooling
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && ln -s /tooling/node_modules /node_modules
WORKDIR /repo/front
