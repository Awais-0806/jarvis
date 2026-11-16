# syntax=docker/dockerfile:1

# ---------- Stage 1: build the SPA ----------
FROM node:20-alpine AS build

WORKDIR /app

# Dependency layer first so source edits do not reinstall packages.
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build


# ---------- Stage 2: serve it ----------
FROM nginx:1.27-alpine AS runtime

# The stock default server listens on :80 as root; this stack runs read-only as UID 10001,
# so it listens on 8080 and uses the rendered config below instead.
RUN rm -f /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/jarvis.conf.template
COPY docker-entrypoint.sh /usr/local/bin/jarvis-entrypoint.sh
RUN chmod 0755 /usr/local/bin/jarvis-entrypoint.sh

EXPOSE 8080

# Renders /tmp/nginx.conf with the bearer token from /run/secrets/core_api_token, then execs
# nginx. The token exists only in the container's process environment — never in the bundle.
ENTRYPOINT ["/usr/local/bin/jarvis-entrypoint.sh"]
