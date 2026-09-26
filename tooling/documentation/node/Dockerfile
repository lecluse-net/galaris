FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3
WORKDIR /tooling
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && ln -s /tooling/node_modules /node_modules
WORKDIR /repo/front
