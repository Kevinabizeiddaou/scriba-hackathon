# Scriba Executive Desk frontend.
#
# Targets:
#   dev   Vite dev server with hot reload (source bind-mounted by docker-compose).
#   test  Unit tests + typecheck (`docker build --target test frontend`).
#   prod  Static build served by nginx.
#
# Node 22 on Debian (glibc): Vite 8 / Rolldown ship native bindings, and the lockfile
# was generated on Windows, so a glibc image is the least surprising match.

FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- dev -----------------------------------------------------------------------------
FROM deps AS dev
ENV NODE_ENV=development
COPY . .
EXPOSE 5173
# --host so the server is reachable from outside the container. The port stays 5173:
# Scriba's API only trusts credentialed requests from http://localhost:5173.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# --- build ---------------------------------------------------------------------------
FROM deps AS build
# Vite inlines VITE_* variables at build time, so they are build args, not runtime env.
ARG VITE_API_BASE_URL=""
ARG VITE_DESK_MODE=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_DESK_MODE=$VITE_DESK_MODE
COPY . .
RUN npm run build

# --- test ----------------------------------------------------------------------------
FROM build AS test
RUN npm test

# --- prod ----------------------------------------------------------------------------
FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
