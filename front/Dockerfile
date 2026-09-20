# Dev stage - used for development (code mounted as volume)
FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 as dev-stage

# The node:alpine image already has a 'node' user with UID 1000
# which matches the typical host user UID. We use it directly.
WORKDIR /app
COPY package*.json ./
RUN npm ci

# Accept build args for Vite environment variables
ARG VITE_APP_ENV=prod
ARG VITE_APP_NAME
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
FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 as build-stage
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Accept build args for Vite environment variables
ARG VITE_APP_ENV=prod
ARG VITE_APP_NAME
ENV VITE_APP_ENV=${VITE_APP_ENV}
ENV VITE_APP_NAME=${VITE_APP_NAME}
RUN npm run build

# Production stage
FROM nginx:stable-alpine@sha256:dc5069ad14f19660b141b21236140b91656bf89bbc3e2417c70ae650cd66104c as prod-stage
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
