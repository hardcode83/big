SERVICE ?=

.PHONY: up down logs ps sh bootstrap db-clean-test version-check

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

# La versión base del producto vive en VERSION (change app-version-visibility, D1).
# Los dos manifiestos la declaran también porque sus ecosistemas lo esperan, así que
# esto comprueba que no han divergido. Lo invoca el gate de CI (backend-tests.yml).
#
# Corre en el HOST a propósito, no dentro de un contenedor: el servicio backend monta
# solo ./backend en /app, así que desde dentro no se ven ni VERSION ni
# frontend/package.json. Un test de pytest aquí sería inejecutable con el comando que
# sdd/project.md manda usar.
version-check:
	@base=$$(tr -d '[:space:]' < VERSION); \
	py=$$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' backend/pyproject.toml | head -1); \
	js=$$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' frontend/package.json | head -1); \
	[ -n "$$base" ] || { echo "✗ VERSION está vacío o no existe"; exit 1; }; \
	[ -n "$$py" ] || { echo "✗ no se pudo leer 'version' de backend/pyproject.toml"; exit 1; }; \
	[ -n "$$js" ] || { echo "✗ no se pudo leer 'version' de frontend/package.json"; exit 1; }; \
	if [ "$$base" != "$$py" ] || [ "$$base" != "$$js" ]; then \
		echo "✗ versión divergente — VERSION=$$base pyproject.toml=$$py package.json=$$js"; \
		echo "  la fuente de verdad es VERSION; alinea los dos manifiestos con ella"; \
		exit 1; \
	fi; \
	echo "✓ versión base coherente en los tres ficheros: $$base"

down:
	docker compose down $(SERVICE)

logs:
	docker compose logs -f $(SERVICE)

ps:
	docker compose ps

sh:
	docker compose exec $(if $(SERVICE),$(SERVICE),backend) sh
