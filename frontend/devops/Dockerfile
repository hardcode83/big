# syntax=docker/dockerfile:1
FROM node:22-slim AS deps

WORKDIR /app
COPY package.json package-lock.json ./
# npm ci: instalacion determinista y reproducible a partir del lockfile.
# Guardamos el hash del lockfile para que el entrypoint de dev sepa si el
# volumen persistente de node_modules esta al dia.
RUN npm ci && sha256sum package-lock.json | cut -d' ' -f1 > node_modules/.lock-hash

# --- dev: usado por docker-compose (target: dev), hot reload via bind mount ---
# node_modules vive en /app (junto al codigo, como exige Turbopack) sobre un
# volumen persistente. El entrypoint reinstala automaticamente si el lockfile
# cambia, asi que anadir dependencias no requiere pasos manuales.
FROM deps AS dev

COPY devops/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
COPY . .
EXPOSE 3000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["npm", "run", "dev"]

# --- prod: standalone output for remote deployment, no bind mount ---
FROM deps AS builder

COPY . .
RUN npm run build

FROM node:22-slim AS prod

WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
