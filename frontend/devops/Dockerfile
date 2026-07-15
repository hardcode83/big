# syntax=docker/dockerfile:1
FROM node:22-slim AS deps

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

# --- dev: used by docker-compose (target: dev), hot reload via bind mount ---
FROM deps AS dev

COPY . .
EXPOSE 3000
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
