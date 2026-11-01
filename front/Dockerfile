# Dev stage - used for development (code mounted as volume)
FROM node:26-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94 as dev-stage

# The node:alpine image already has a 'node' user with UID 1000
# which matches the typical host user UID. We use it directly.
WORKDIR /app
COPY package*.json ./
RUN npm ci

# Accept build args for Vite environment variables
ARG VITE_APP_ENV=prod
ARG VITE_APP_NAME
ARG GALARIS_BUILD_VERSION=unknown
ENV GALARIS_BUILD_VERSION=${GALARIS_BUILD_VERSION}
ENV VITE_APP_ENV=${VITE_APP_ENV}
ENV VITE_APP_NAME=${VITE_APP_NAME}

# Change ownership to node user (UID 1000)
RUN chown -R node:node /app

# Switch to node user
USER node

# Code is mounted as volume in docker-compose, don't COPY here
EXPOSE 8484
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "8484"]

# Build stage - used only for production build
FROM node:26-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94 as build-stage
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Accept build args for Vite environment variables
ARG VITE_APP_ENV=prod
ARG VITE_APP_NAME
ARG GALARIS_BUILD_VERSION=unknown
ENV GALARIS_BUILD_VERSION=${GALARIS_BUILD_VERSION}
ENV VITE_APP_ENV=${VITE_APP_ENV}
ENV VITE_APP_NAME=${VITE_APP_NAME}
RUN npm run build

# Production stage
FROM nginx:stable-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949 as prod-stage
RUN apk upgrade --no-cache
ENV APP_NAME=galaris
COPY --from=build-stage /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Support running as non-root
RUN chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    chown -R nginx:nginx /etc/nginx/templates && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid

USER nginx
EXPOSE 8484
CMD ["nginx", "-g", "daemon off;"]
