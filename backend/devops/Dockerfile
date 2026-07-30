# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./

# --- dev: used by docker-compose (target: dev), hot reload via bind mount ---
FROM base AS dev

RUN uv sync --frozen
COPY . .

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- prod: lean image for remote deployment, no dev deps, no bind mount ---
FROM base AS builder

RUN uv sync --frozen --no-dev --no-editable
COPY . .

FROM python:3.12-slim AS prod

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

# Identidad de build, horneada por el CD (change app-version-visibility, R1.2). Va al FINAL
# de la etapa a propósito: cambia en cada commit, así que declararla antes invalidaría la
# caché de las capas de dependencias en cada build.
#
# Los seis ARG tienen default vacío para que un `docker build` a mano siga funcionando; el
# lado Python los lee vía Settings, donde TODOS tienen default (design D4), así que una
# imagen construida sin estos build-args arranca igual y reporta null.
ARG APP_VERSION=""
ARG BUILD_COMMIT=""
ARG BUILD_PR=""
ARG BUILT_AT=""
ARG BUILD_RUN_ID=""
ARG BUILD_REF=""
ENV APP_VERSION=${APP_VERSION} \
    BUILD_COMMIT=${BUILD_COMMIT} \
    BUILD_PR=${BUILD_PR} \
    BUILT_AT=${BUILT_AT} \
    BUILD_RUN_ID=${BUILD_RUN_ID} \
    BUILD_REF=${BUILD_REF}

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
