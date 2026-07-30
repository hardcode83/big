SERVICE ?=

.PHONY: up down logs ps sh bootstrap

up:
	@umask 077; if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "→ .env creado desde .env.example (valores locales por defecto, edítalo si quieres otros)"; \
	fi
	@chmod 600 .env
	@if ! grep -qE '^JWT_SECRET_KEY=.{32,}' .env; then \
		umask 077; key=$$(openssl rand -hex 32); \
		grep -v '^JWT_SECRET_KEY=' .env > .env.tmp; \
		printf 'JWT_SECRET_KEY=%s\n' "$$key" >> .env.tmp; \
		mv .env.tmp .env; \
		chmod 600 .env; \
		echo "→ JWT_SECRET_KEY generada en .env (local, nunca versionada)"; \
	fi
	docker compose up -d --build $(SERVICE)

# Deliberately NOT part of `up`: it needs the BOOTSTRAP_* values a person has to
# choose, and `up` must keep starting with no manual steps (DoD §28.20).
#
# `python -m`, not `uv run`: the venv is on PATH in every stage of
# backend/devops/Dockerfile, while `uv` exists only in the dev stage. The same command
# therefore works against the deployed prod image — see RUNBOOK §6.5.
bootstrap:
	docker compose exec backend python -m app.cli.bootstrap

down:
	docker compose down $(SERVICE)

logs:
	docker compose logs -f $(SERVICE)

ps:
	docker compose ps

sh:
	docker compose exec $(if $(SERVICE),$(SERVICE),backend) sh
