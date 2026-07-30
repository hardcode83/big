SERVICE ?=

.PHONY: up down logs ps sh bootstrap db-clean-test version-check pr-extract-check ci-checks

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

# Parsers reales (tomllib + json, ambos de la stdlib desde 3.11) en vez de sed/grep.
# Motivo, del panel de QA: un `sed` no es consciente de secciones TOML, así que una clave
# `version` bajo otra tabla ANTES de [project] enmascaraba una divergencia real en
# [project].version si su valor coincidía con VERSION — un falso negativo, justo lo que
# R6.2 prohíbe ("fallar en CI, no en silencio"). Lo mismo vale para una clave "version"
# anidada en package.json. Con parsers reales la clase entera de fragilidad desaparece.
define VERSION_CHECK_PY
import json, pathlib, sys, tomllib

def fail(message):
    print("✗ " + message)
    sys.exit(1)

try:
    base = pathlib.Path("VERSION").read_text().strip()
except OSError as exc:
    fail("no se pudo leer VERSION: %s" % exc)
if not base:
    fail("VERSION esta vacio")

try:
    py = tomllib.loads(pathlib.Path("backend/pyproject.toml").read_text())["project"]["version"]
except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
    fail("no se pudo leer [project].version de backend/pyproject.toml: %r" % (exc,))

try:
    js = json.loads(pathlib.Path("frontend/package.json").read_text())["version"]
except (OSError, KeyError, ValueError) as exc:
    fail("no se pudo leer version de frontend/package.json: %r" % (exc,))

if base != py or base != js:
    fail(
        "version divergente - VERSION=%s pyproject.toml=%s package.json=%s\n"
        "  la fuente de verdad es VERSION; alinea los dos manifiestos con ella"
        % (base, py, js)
    )

print("✓ version base coherente en los tres ficheros: " + base)
endef
export VERSION_CHECK_PY

# La versión base del producto vive en VERSION (change app-version-visibility, D1).
# Los dos manifiestos la declaran también porque sus ecosistemas lo esperan, así que
# esto comprueba que no han divergido. Lo invoca el gate de CI (backend-tests.yml).
#
# Corre en el HOST a propósito, no dentro de un contenedor: el servicio backend monta
# solo ./backend en /app, así que desde dentro no se ven ni VERSION ni
# frontend/package.json. Un test de pytest aquí sería inejecutable con el comando que
# sdd/project.md manda usar.
version-check:
	@python3 -c "$$VERSION_CHECK_PY"

# La extracción del PR del subject del commit es lo que sostiene el pareo pantalla↔PR, y
# vive en un script justamente para poder testearla. Sin este target, un cambio en el `sed`
# volvería a leer un número de ISSUE como número de PR sin que ningún gate lo detecte
# (hallazgo del panel de QA, sección 3).
pr-extract-check:
	@.github/scripts/extract-pr.sh --self-test

# Las comprobaciones de repo que no encajan en la suite de un componente: ninguna se puede
# ejecutar dentro de un contenedor, porque backend y frontend montan solo su propio
# directorio y no ven la raíz. Las invoca el gate de CI.
ci-checks: version-check pr-extract-check

down:
	docker compose down $(SERVICE)

logs:
	docker compose logs -f $(SERVICE)

ps:
	docker compose ps

sh:
	docker compose exec $(if $(SERVICE),$(SERVICE),backend) sh
