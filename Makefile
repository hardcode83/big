SERVICE ?=

.PHONY: up down logs ps sh bootstrap openapi db-clean-test

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

# Regenera backend/openapi.json, el contrato que consume el frontend. Ejecútalo cuando
# cambies la forma de una respuesta: el workflow api-contract lo comprueba en cada PR y
# falla si el fichero commiteado ya no corresponde al código.
#
# `run --rm --no-deps` y no `exec`: no necesita el stack levantado, y `--no-deps` es lo
# que lo hace cierto — sin él, `depends_on` arranca postgres, redis y migrate para una
# generación que no toca base de datos, Redis ni red (design D6).
openapi:
	docker compose run --rm --no-deps -T backend python -m app.cli.openapi

# Cada ejecución de pytest crea su propia base (`<db>_test_<pid>`, ver
# backend/tests/db_names.py) y la borra al terminar. Una suite matada a lo bruto deja
# la suya atrás: esto barre las huérfanas sin tocar la base de desarrollo.
db-clean-test:
	@docker compose exec -T postgres psql -U $${POSTGRES_USER:-autohostai} -d postgres -tAc \
		"select datname from pg_database where datname ~ '_(test|migrations)_[0-9a-z]+$$'" \
		| while read -r db; do \
			[ -n "$$db" ] || continue; \
			echo "→ borrando $$db"; \
			docker compose exec -T postgres psql -U $${POSTGRES_USER:-autohostai} -d postgres \
				-c "DROP DATABASE IF EXISTS \"$$db\" WITH (FORCE)" >/dev/null </dev/null; \
		done; echo "listo"

down:
	docker compose down $(SERVICE)

logs:
	docker compose logs -f $(SERVICE)

ps:
	docker compose ps

sh:
	docker compose exec $(if $(SERVICE),$(SERVICE),backend) sh
