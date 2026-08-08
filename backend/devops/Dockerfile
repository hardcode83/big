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
# Both proxy flags are pinned, and `--forwarded-allow-ips` is pinned SPECIFICALLY to close
# an environment channel: uvicorn falls back to the `FORWARDED_ALLOW_IPS` env var when the
# flag is absent (`uvicorn/config.py:356`, verified in the installed 0.51.0 — it is not
# only a gunicorn name, as this change's design first claimed). `docker-compose.yml` hands
# the backend the whole `.env` via `env_file`, and publishes 8000 on every interface, so
# somebody adding the famous `FORWARDED_ALLOW_IPS=*` to their `.env` while debugging would
# let anyone on the LAN choose their own rate-limit bucket and their own `actor_ip`. The
# CLI flag wins over the env var, so writing it here makes that impossible by accident.
#
# `127.0.0.1` means "trust nobody but this container's own loopback", which is the local
# posture design D7 wants. Precisely: a caller arriving through the published port does not
# present as loopback, so nothing off-box is trusted. In-container callers DO — the
# healthcheck (`urlopen('http://localhost:8000/health')`) is one — and that is harmless:
# `/health` never resolves a client address, and the deployed `command:` trusts only the
# frontend's static IP, not loopback.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]

# --- prod: lean image for remote deployment, no dev deps, no bind mount ---
FROM base AS builder

RUN uv sync --frozen --no-dev --no-editable
COPY . .

FROM python:3.12-slim AS prod

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
# `--proxy-headers` is uvicorn's DEFAULT (Config.__init__ has it True) and is written out
# anyway, because leaving it implicit is what let two mechanisms rewrite the client
# address at once: this middleware, and a header reader that used to live in
# `get_client_ip` (change `api-ingress-routing`, design D3). One is now chosen on purpose.
#
# The environment-specific trusted address is NOT baked in here — that would stop the image
# being the same one for every environment at a given IMAGE_TAG. It arrives by the `command:`
# of the `backend` service in `docker-compose.deploy.yml`, which replaces this CMD entirely
# and sits next to the `ipv4_address` it must equal.
#
# But the flag is still pinned to a trust-nobody value, because an ABSENT flag is not
# neutral: uvicorn then reads the `FORWARDED_ALLOW_IPS` env var (`uvicorn/config.py:356`,
# verified in the installed 0.51.0). Leaving it out would mean anyone who can set an
# environment variable on this container decides who is believed about client addresses —
# including `*`. So this is the safe floor for running the prod image without the compose
# override, and the compose override is the only way to widen it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
