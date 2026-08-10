# Sin comillas en las recetas a propósito: vacío tiene que significar «todos los servicios», y
# entrecomillarlo pasaría un argumento vacío. Es seguro mientras lo escriba una persona en su propia
# terminal — `make up SERVICE='x; ...'` es auto-inyección sin ganancia de privilegio, en un shell que
# ya podía ejecutar cualquier cosa. Lo que lo convertiría en un problema real: que lo suministre algo
# que no sea humano (un job de CI interpolando `${{ github.* }}`, un wrapper, un agente). Si eso
# pasa, hay que entrecomillarlo y validarlo aquí.
SERVICE ?=

# ¿Estamos en un worktree enlazado (`git worktree add`) o en el principal?
#
# En el principal `--git-dir` y `--git-common-dir` apuntan al mismo sitio; en un worktree enlazado
# el primero es `<común>/.git/worktrees/<nombre>`. Se comparan en una sola invocación de shell y no
# con `$(filter ...)`, que parte por espacios y daría un falso "principal" en una ruta que los
# tenga. `--path-format=absolute` (git >= 2.31) es lo que hace la comparación honesta: sin él, en el
# principal las dos salidas son relativas y en el worktree absolutas.
#
# Si git no contesta (no hay git, no es un repositorio, es un tarball), las dos salidas quedan
# vacías, la desigualdad es falsa y nos comportamos como el principal: publicar. Es deliberado —
# una colisión de puertos aborta nombrando el puerto, mientras que no publicar en silencio se
# manifiesta como "la app no carga".
IS_WORKTREE := $(shell test "$$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)" != "$$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" && echo yes)

# El worktree principal invoca `docker compose` desnudo, exactamente como antes de que este fichero
# supiera de worktrees: así lo que Compose descubre por sí solo sigue siendo la postura de red real
# del proyecto. Un worktree enlazado añade el overlay que retira la publicación de puertos.
COMPOSE_ARGS := $(if $(IS_WORKTREE),-f docker-compose.yml -f docker-compose.worktree.yml,)
COMPOSE := $(strip docker compose $(COMPOSE_ARGS))


.PHONY: up down logs ps sh bootstrap openapi check-version-parity db-clean-test

up:
	@if [ -n "$(IS_WORKTREE)" ] && [ ! -f docker-compose.worktree.yml ]; then \
		echo "error: falta docker-compose.worktree.yml, que es lo que evita que este worktree"; \
		echo "       choque de puertos con el principal."; \
		echo "       Esta rama es anterior al change worktree-parallel-stack: rebasa sobre main,"; \
		echo "       o levanta el stack desde el worktree principal."; \
		exit 1; \
	fi
	@if [ -n "$(IS_WORKTREE)" ]; then \
		echo "→ worktree enlazado: stack SIN puertos publicados (no habrá UI ni API en el navegador del host)"; \
	else \
		echo "→ worktree principal: stack CON puertos publicados (postgres/redis en 127.0.0.1; 8000 y 3000 en todas las interfaces)"; \
	fi
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
# Una clave Fernet NO es `openssl rand -hex 32`: es base64 de 32 bytes, y `-hex 32` da 64
# caracteres que decodifican a 48, así que el validador de `app/core/config.py` la rechaza al
# arrancar. El `tr '+/' '-_'` produce la forma **url-safe canónica**; NO es lo que hace válida la
# clave — medido: `urlsafe_b64decode` traduce `-_` a `+/` y luego llama al `b64decode` permisivo, y
# `Fernet` usa ese mismo decodificador, así que también aceptaría el alfabeto estándar. Se
# canonicaliza porque un `/` dentro de un valor de `.env` es una fuente de sorpresas gratuita.
# El `tr -d '\n'` sí es necesario: `base64` cierra con salto de línea y una clave con `\n` dentro
# falla de una forma que no se lee como "clave mal formada".
# La comprobación es de longitud EXACTA (44) y no `.{44,}`: una clave truncada pasaría un mínimo y
# reventaría después dentro de Fernet, que es justo el fallo tardío que este generador evita.
# Y a diferencia de la clave JWT, esta NO se regenera si ya hay un valor: regenerar la clave de
# firma solo invalida sesiones, pero regenerar la de cifrado deja **indescifrable todo el
# ciphertext ya almacenado** (`app/core/crypto.py` lo dice: una clave distinta es un
# `SecretDecryptionError` por fila). Así que solo se genera cuando falta o está vacía; si hay un
# valor con forma incorrecta —un `.env` con CRLF, una clave truncada a mano— se PARA y se avisa,
# porque sustituirlo en silencio sería destruir dato sin preguntar.
	@current=$$(sed -n 's/^ENCRYPTION_KEY=//p' .env | head -1); \
	if [ -z "$$current" ]; then \
		umask 077; key=$$(openssl rand 32 | base64 | tr '+/' '-_' | tr -d '\n'); \
		grep -v '^ENCRYPTION_KEY=' .env > .env.tmp; \
		printf 'ENCRYPTION_KEY=%s\n' "$$key" >> .env.tmp; \
		mv .env.tmp .env; \
		chmod 600 .env; \
		echo "→ ENCRYPTION_KEY generada en .env (local, nunca versionada)"; \
	elif [ $${#current} -ne 44 ]; then \
		echo "ERROR: ENCRYPTION_KEY en .env tiene $${#current} caracteres y debe tener 44."; \
		echo "       NO se sustituye sola: si ya has cifrado algo con otra clave, cambiarla lo"; \
		echo "       deja indescifrable. Revísala a mano (¿saltos de línea CRLF? ¿copiada a medias?)."; \
		echo "       Para empezar de cero a sabiendas: borra la línea de .env y vuelve a lanzar make up."; \
		exit 1; \
	fi
# Comprobar ANTES de intentar el bind, y después de crear `.env` (tres servicios declaran
# `env_file: .env`, así que `config` no resuelve sin él). Caza dos cosas de una: un servicio con
# `ports:` que nadie añadió al overlay, y un Docker Compose anterior a 2.24, que ignora el tag
# `!reset` y dejaría los cuatro mapeos en pie. Sin esto el síntoma sería un "port is already
# allocated" que se lee como otra cosa.
#
# El estado de salida de `config` se comprueba APARTE y el contenido con `case`, no con un pipe a
# `grep`: en un pipe el estado de salida es el del último comando, así que un `config` que falla
# (un `.env` a mano sin JWT_SECRET_KEY, por ejemplo) daría cero coincidencias y la comprobación
# pasaría en verde sin haber comprobado nada. Cualquier fallo de la cadena es rojo con mensaje
# propio; nunca se degrada a verde.
#
# Y se busca la clave `"ports"`, no `"published"`. Medido: hay dos formas legales de declarar un
# mapeo que NO producen `published` ni `host_ip` —la corta con solo el puerto del contenedor
# (`ports: ["5432"]`) y la larga sin `published` (`{target: 6379, mode: ingress}`)— y Docker las
# publica en un puerto EFÍMERO y en todas las interfaces. Buscar `published` las dejaba pasar en
# verde mientras el stack publicaba. Con el overlay aplicado no queda ninguna clave `ports` en la
# configuración resuelta (medido: 4 sin overlay, 0 con él), así que ausencia de `ports` es la
# aserción correcta y además cubre formas de mapeo que aún no existen.
	@if [ -n "$(IS_WORKTREE)" ]; then \
		cfg=$$($(COMPOSE) config --format json) || { \
			echo "error: 'docker compose config' falló, así que no se ha podido comprobar que este"; \
			echo "       worktree no publica puertos. Se aborta en rojo a propósito: sin esa"; \
			echo "       comprobación, arrancar puede chocar con el stack del principal."; \
			exit 1; \
		}; \
		case "$$cfg" in *'"ports"'*) \
			echo "error: a este worktree le queda algún mapeo de puertos, así que publicaría en el host y"; \
			echo "       chocaría con el principal. Causas: un servicio con 'ports:' que falta en"; \
			echo "       docker-compose.worktree.yml, o un Docker Compose anterior a 2.24, que ignora el"; \
			echo "       tag !reset (aquí: $$($(COMPOSE) version --short))."; \
			exit 1;; \
		esac; \
	fi
	$(COMPOSE) up -d --build $(SERVICE)

# Deliberately NOT part of `up`: it needs the BOOTSTRAP_* values a person has to
# choose, and `up` must keep starting with no manual steps (DoD §28.20).
#
# `python -m`, not `uv run`: the venv is on PATH in every stage of
# backend/devops/Dockerfile, while `uv` exists only in the dev stage. The same command
# therefore works against the deployed prod image — see RUNBOOK §6.5.
bootstrap:
	$(COMPOSE) exec backend python -m app.cli.bootstrap

# Regenera backend/openapi.json, el contrato que consume el frontend. Ejecútalo cuando
# cambies la forma de una respuesta: el workflow api-contract lo comprueba en cada PR y
# falla si el fichero commiteado ya no corresponde al código.
#
# `run --rm --no-deps` y no `exec`: no necesita el stack levantado, y `--no-deps` es lo
# que lo hace cierto — sin él, `depends_on` arranca postgres, redis y migrate para una
# generación que no toca base de datos, Redis ni red (design D6).
openapi:
	$(COMPOSE) run --rm --no-deps -T backend python -m app.cli.openapi

check-version-parity:
	python3 scripts/check-version-parity.py

# Cada ejecución de pytest crea su propia base (`<db>_test_<pid>`, o
# `<db>_test_<pid>_gw0` por worker si se corre con `-n`; ver backend/tests/db_names.py) y
# la borra al terminar. Una suite matada a lo bruto deja la suya atrás: esto barre las
# huérfanas sin tocar la base de desarrollo.
#
# El guion bajo de la clase es el del id del worker: sin él, `_test_ci_gw0` no encaja y el
# barrido dejaría huérfanas justo las bases que el paralelismo crea. La clase es la misma
# que valida `run_suffix()` en db_names.py, y las dos se ensanchan juntas o ninguna.
#
# ⚠️ NO lo ejecutes con una suite corriendo. Borra con `WITH (FORCE)` toda base que encaje el
# patrón, y no sabe distinguir una huérfana de una viva. Medido a propósito: lanzado a mitad de
# una ejecución con `-n 4`, convirtió una suite verde en **771 errores** de
# `InvalidCatalogNameError`, y el síntoma se lee como tests inestables en vez de como lo que es.
# El paralelismo lo agrava, porque ahora hay cuatro bases por ejecución en vez de una.
#
# Filtrar por conexiones vivas (`pg_stat_activity`) **no lo arregla** y se probó: la fixture usa
# `NullPool` y desecha el engine entre tests, así que toda base viva tiene ventanas de cero
# conexiones y el barrido cae en una de ellas (medido: 144 errores en vez de 771, que es peor
# que no filtrar, porque parece seguro y no lo es). Cerrarlo de verdad pide que la ejecución
# marque su base como en uso de una forma que sobreviva a esas ventanas — trabajo de otro
# change, no de este.
db-clean-test:
	@$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-autohostai} -d postgres -tAc \
		"select datname from pg_database where datname ~ '_(test|migrations)_[0-9a-z_]+$$'" \
		| while read -r db; do \
			[ -n "$$db" ] || continue; \
			echo "→ borrando $$db"; \
			$(COMPOSE) exec -T postgres psql -U $${POSTGRES_USER:-autohostai} -d postgres \
				-c "DROP DATABASE IF EXISTS \"$$db\" WITH (FORCE)" >/dev/null </dev/null; \
		done; echo "listo"

down:
	$(COMPOSE) down $(SERVICE)

logs:
	$(COMPOSE) logs -f $(SERVICE)

ps:
	$(COMPOSE) ps

sh:
	$(COMPOSE) exec $(if $(SERVICE),$(SERVICE),backend) sh
