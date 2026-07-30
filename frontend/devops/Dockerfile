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

# NEXT_PUBLIC_* se hornean en el bundle durante `npm run build` (Next standalone).
# El CD las pasa como build-args; declararlas aquí como ENV para que el build las vea.
ARG NEXT_PUBLIC_APP_ENV
ENV NEXT_PUBLIC_APP_ENV=${NEXT_PUBLIC_APP_ENV}

# Las dos únicas de la identidad que PUEDEN llegar al navegador (design D6): son lo que
# pinta el badge, y entran en PublicRuntimeConfig, que cruza al cliente.
#
# Nota de alcance, verificada y no supuesta: el badge es un Server Component, así que la
# cadena viaja en el HTML servido y NO queda inlineada en .next/static. Delata que el edge
# sirve una página cacheada antigua, pero no que sirva chunks JS antiguos con HTML fresco.
# Ver la tabla de "Data & interfaces" del design.
ARG NEXT_PUBLIC_APP_VERSION=""
ARG NEXT_PUBLIC_BUILD_COMMIT_SHORT=""
ENV NEXT_PUBLIC_APP_VERSION=${NEXT_PUBLIC_APP_VERSION} \
    NEXT_PUBLIC_BUILD_COMMIT_SHORT=${NEXT_PUBLIC_BUILD_COMMIT_SHORT}

COPY . .
RUN npm run build

FROM node:22-slim AS prod

WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Procedencia SIN prefijo NEXT_PUBLIC_, deliberadamente (design D6): horneada en la imagen
# —así que R1.3 se cumple, no es config de compose— pero legible SOLO por el servidor de
# Next a través de lib/config/server.ts. Alimenta el panel de procedencia sin que el número
# de PR ni la URL del repositorio entren en el bundle que recibe el navegador en /login o
# en el portal de huésped. Renombrar cualquiera de estas a NEXT_PUBLIC_* sería una fuga que
# ningún test detectaría.
#
# Al final de la etapa: cambian en cada commit y no deben invalidar las capas de arriba.
ARG BUILD_COMMIT=""
ARG BUILD_PR=""
ARG BUILT_AT=""
ARG BUILD_RUN_ID=""
ARG BUILD_REF=""
ARG REPO_URL=""
ENV BUILD_COMMIT=${BUILD_COMMIT} \
    BUILD_PR=${BUILD_PR} \
    BUILT_AT=${BUILT_AT} \
    BUILD_RUN_ID=${BUILD_RUN_ID} \
    BUILD_REF=${BUILD_REF} \
    REPO_URL=${REPO_URL}

EXPOSE 3000
CMD ["node", "server.js"]
