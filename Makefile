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

# Desplazamiento de los cuatro puertos publicados: `make up PORT_OFFSET=10` levanta este stack en
# 5442/6389/8010/3010 en vez de 5432/6379/8000/3000. Existe para recuperar el navegador que
# `worktree-parallel-stack` costó —un worktree enlazado no publica nada— sin reintroducir el choque
# de puertos que aquella decisión eliminó.
#
# `make` toma sus variables del entorno, así que un `export PORT_OFFSET=10` en la shell de un
# worktree desplaza todos sus `make up` sin repetirlo. Lo que NO puede hacer es mover a la guardia
# de puertos: `check-compose-ports` no pasa por `$(COMPOSE)` y su script construye el entorno del
# hijo por lista blanca, así que un `PORT_OFFSET` exportado no cambia su veredicto.
#
# El valor pasa por dos pasos, y el ORDEN entre ellos es la parte que importa: primero se rechaza
# lo que no es un entero, y solo después se normaliza. Al revés —que es como estuvo escrito—, la
# normalización podía convertir un valor inservible en uno válido y el rechazo nunca llegaba.
PORT_OFFSET ?=
#
# Sin `$(strip …)`, y es deliberado: estuvo ahí y era un tercer agujero de la misma familia que los
# otros dos. `$(strip)` corre ANTES de la puerta de abajo, así que un `PORT_OFFSET=' 10'` llegaba
# convertido en `10` y se aceptaba en silencio — cuando el mensaje de la propia puerta promete «sin
# espacios» y `parse_offset()` de `scripts/compose-offset.py` rechaza ese mismo ` 10` por dedazo. Dos
# capas que se contradicen sobre el mismo valor es justo lo que este bloque existe para no tener.
# Ahora el valor llega crudo a la puerta y un espacio lo rechaza, se llame como se llame.
#
# Consecuencia aceptada: un `PORT_OFFSET` de solo espacios ya no equivale a vacío (R3.3 habla de
# vacío y de `0`, no de blancos), y aborta nombrándolo. El mensaje dice cómo salir.
OFFSET_RAW := $(value PORT_OFFSET)

# Paso 1: solo dígitos, comprobado en tiempo de parseo y ANTES de que el valor llegue a ninguna
# receta.
#
# No es defensa en profundidad ni desconfianza del validador del script: es que `make` interpola la
# variable en el TEXTO de la línea que ejecuta `/bin/sh`, así que entrecomillarla NO contiene un
# valor que lleve una comilla dentro —la cierra, y lo que venga detrás se ejecuta—. Medido: con
# `PORT_OFFSET='1"; echo PWNED; "'` la receta ejecutaba el `echo` y al validador del script le
# llegaba un `1` inofensivo. Y a diferencia de `$(SERVICE)`, cuya exención de la cabecera se apoya
# en que lo escribe una persona en su propia terminal, este valor se toma **del entorno** a
# propósito (ver arriba), que es justo el canal no humano que aquella exención excluye — así que
# aquí toca lo que la cabecera manda: entrecomillar **y validar**.
#
# Se hace con `subst` y no con `$(shell … grep …)`: comprobar el valor pasándolo por un shell es
# exactamente el agujero que se quiere cerrar. Esto no ejecuta nada, es sustitución de texto de
# `make`, y por eso puede correr en tiempo de parseo.
#
# `$(value PORT_OFFSET)` y NO `$(PORT_OFFSET)`, que es la parte que menos se ve y la que de verdad
# cierra el agujero. Una variable de entorno es para `make` una variable de expansión diferida, así
# que nombrarla la expande — y si su texto lleva un `$(shell …)` dentro, `make` ejecuta ese comando
# ANTES de que exista nada que comparar, y encima lo hace para CUALQUIER target, porque esta
# asignación es de nivel superior. `$(value …)` devuelve el texto **sin expandir**, así que el
# `$(shell …)` llega entero a la comprobación de abajo y se rechaza sin haberse ejecutado. Medido
# con un `touch` como carga: por entorno no se crea el fichero; el valor sale rechazado.
#
# Residual declarado, porque no lo puede cerrar ningún constructo de este fichero: una definición
# en la LÍNEA DE COMANDOS (`make up 'PORT_OFFSET=$(shell …)'`) la expande `make` al parsear sus
# argumentos, antes de leer este Makefile. Ahí sí se ejecuta — y es exactamente el caso que la
# cabecera de este fichero ya acepta para `$(SERVICE)`: auto-inyección de quien escribe en su
# propia terminal, sin ganancia de privilegio. Lo que la cabecera señala como problema real es el
# canal no humano —un `.envrc`, un wrapper, un agente, un job de CI—, y ése es el entorno, que es
# el que `$(value …)` cierra.
#
# El centinela `x…x` de la comparación es cinturón y tirantes, y conviene decirlo sin adornar:
# medido con GNU Make 3.81, la forma desnuda `ifneq ($(OFFSET_NOT_DIGITS),)` también rechaza un
# `1 0` —cuyo residuo tras quitar dígitos es un espacio—. El centinela hace que el veredicto no
# dependa de cómo trate los espacios de sus argumentos la versión de `make` que toque.
#
# Solo la CLASE de caracteres se decide aquí. El rango, el techo de 57535 y el mensaje que nombra
# el puerto culpable siguen viviendo en `scripts/compose-offset.py`, que es su única sede.
OFFSET_NOT_DIGITS := $(subst 0,,$(subst 1,,$(subst 2,,$(subst 3,,$(subst 4,,$(subst 5,,$(subst 6,,$(subst 7,,$(subst 8,,$(subst 9,,$(OFFSET_RAW)))))))))))
ifneq (x$(OFFSET_NOT_DIGITS)x,xx)
$(error PORT_OFFSET tiene que ser un entero no negativo en decimal, y recibí `$(value PORT_OFFSET)`. Sin signo, sin espacios y sin hexadecimal. Esta comprobación corre en CUALQUIER target, así que si lo tienes exportado en la shell con un valor malo y solo quieres bajar el stack: `PORT_OFFSET= make down`.)
endif

# Paso 2: «vale cero» y «no se pasó» son lo mismo (R3.3). La prueba es que al valor no le quede
# nada tras quitarle los ceros, y no que la palabra sea exactamente `0`: un `PORT_OFFSET=00` es
# cero igual, y con la comprobación por palabra se colaba por la rama del desplazamiento generando
# un overlay que publica los puertos SIN desplazar (5432/6379/8000/3000) — es decir, justo la
# colisión que este change existe para evitar, a partir de un dedazo que no parece nada.
OFFSET := $(if $(subst 0,,$(OFFSET_RAW)),$(OFFSET_RAW),)

# Ruta ESTABLE y conocida en tiempo de parseo, que es lo que permite que `COMPOSE_ARGS` siga siendo
# una sola definición: con un fichero temporal habría que construir la invocación dentro de cada
# receta, es decir una segunda definición. Vive en `.make/` (gitignorado) y NO se llama
# `docker-compose.override.yml`. Queda PROHIBIDO moverlo a la raíz, renombrarlo así o añadirlo con
# `-f` al target de la guardia: las tres cosas lo meten en lo que Compose descubre por sí solo, y
# entonces el desplazamiento cambiaría el veredicto de `check-compose-ports`, que tiene que ser
# función solo del repositorio.
OFFSET_FILE := .make/docker-compose.offset.yml

# Una sola definición y tres ramas, en este orden de prioridad:
#
# 1. Con desplazamiento: fichero base + overlay generado. NO se carga `docker-compose.worktree.yml`,
#    porque el overlay usa `ports: !override`, que SUSTITUYE la lista del base — la fusión de
#    Compose concatena arrays, así que hace falta el tag para reemplazarla, y con él el overlay vale
#    igual aquí y en el principal sin depender del orden de los `-f`. Esta rama no mira
#    `IS_WORKTREE` a propósito: es lo que permite que el worktree principal también se aparte en vez
#    de obligar a bajarlo.
# 2. Worktree enlazado sin desplazamiento: el overlay que retira la publicación de puertos.
# 3. Worktree principal sin desplazamiento: `docker compose` DESNUDO, exactamente como antes de que
#    este fichero supiera de worktrees, para que lo que Compose descubre por sí solo siga siendo la
#    postura de red real del proyecto.
COMPOSE_ARGS := $(if $(OFFSET),-f docker-compose.yml -f $(OFFSET_FILE),$(if $(IS_WORKTREE),-f docker-compose.yml -f docker-compose.worktree.yml,))
COMPOSE := $(strip docker compose $(COMPOSE_ARGS))


.PHONY: up down logs ps sh ports bootstrap seed-demo demo-reset openapi check-version-parity check-frontend-build compose-stacks check-compose-ports check-rule11-ownership db-clean-test

# El guard del overlay de worktree queda acotado a la rama SIN desplazamiento, y no por higiene:
# con desplazamiento ese fichero no se carga (lo sustituye el overlay generado, ver COMPOSE_ARGS),
# así que exigirlo ahí sería pedir un fichero que la invocación no va a usar.
up:
	@if [ -z "$(OFFSET)" ] && [ -n "$(IS_WORKTREE)" ] && [ ! -f docker-compose.worktree.yml ]; then \
		echo "error: falta docker-compose.worktree.yml, que es lo que evita que este worktree"; \
		echo "       choque de puertos con el principal."; \
		echo "       Esta rama es anterior al change worktree-parallel-stack: rebasa sobre main,"; \
		echo "       o levanta el stack desde el worktree principal."; \
		exit 1; \
	fi
	@if [ -n "$(OFFSET)" ]; then \
		:; \
	elif [ -n "$(IS_WORKTREE)" ]; then \
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
# Comprobar ANTES de intentar el bind. Queda después de crear `.env` por orden de la receta, no
# porque haga falta: con las dos banderas de abajo `config` sale con código 0 sin `.env` de ninguna
# clase (medido). La redacción anterior decía que sin `.env` no resolvía —cierto de `config` a
# secas, que es lo que esta línea usaba antes de `compose-ports-guard`—. Caza dos cosas de una: un servicio con
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
#
# Las dos banderas de `config` son obligatorias por la regla que `compose-ports-guard` (2026-08-18)
# dejó escrita en specs/local-environment.md: inspeccionar la postura con `config` exige
# `--no-interpolate --no-env-resolution`. Aquí no era un riesgo teórico — sin ellas esta línea
# materializa el `.env` entero resuelto (JWT_SECRET_KEY, POSTGRES_PASSWORD, ENCRYPTION_KEY) en
# `$$cfg`, y bastaría un `set -x` o un `echo` de depuración para volcarlo. Medido al añadirlas: el
# `!reset []` sigue dejando CERO claves `ports` con y sin banderas, así que la aserción no cambia.
	@if [ -z "$(OFFSET)" ] && [ -n "$(IS_WORKTREE)" ]; then \
		cfg=$$($(COMPOSE) config --no-interpolate --no-env-resolution --format json) || { \
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
# La rama con desplazamiento, en el orden exacto del diseño y TODA antes de levantar:
# generar -> asertar la configuración resuelta -> sondear los binds -> anunciar -> levantar.
#
# Ese orden no es indiferente. Sondear antes de asertar diría "el puerto está libre" sobre una
# configuración que quizá no publica lo que creemos; y sondear después de levantar es justamente
# el síntoma ilegible que esto existe para evitar —Compose fallando a medio arrancar con un "port
# is already allocated" y contenedores a medias— en vez de un error que nombra puerto y servicio.
#
# `check` es también lo que cubre "el overlay no se pudo combinar": si `!override` no se aplicó,
# la configuración resuelta trae los dos mapeos y la aserción sale en rojo. NUNCA se degrada a
# levantar publicando lo que salga.
#
# `$(OFFSET)` va ENTRECOMILLADO, al contrario que `$(SERVICE)`: aquí no hay ninguna razón para
# querer que un valor con espacios se parta en varios argumentos, y entrecomillarlo hace que un
# valor inservible llegue entero al validador, que lo rechaza nombrándolo, en vez de degradar a un
# error de uso del script.
	@if [ -n "$(OFFSET)" ]; then \
		python3 scripts/compose-offset.py generate "$(OFFSET)" || exit 1; \
		python3 scripts/compose-offset.py check "$(OFFSET)" || exit 1; \
		python3 scripts/compose-offset.py announce "$(OFFSET)" $(if $(IS_WORKTREE),--worktree,) || exit 1; \
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

# The demo dataset of PRD §27. Requires `bootstrap` first — it completes the tenant that
# command created and refuses to run without it. Not part of `up` for the same reason
# `bootstrap` is not (DoD §28.20), and `python -m` for the same reason too.
seed-demo:
	$(COMPOSE) exec backend python -m app.cli.seed_demo

# El tenant de demostración: lo aprovisiona si no existe y lo resetea si existe, por la misma
# secuencia de fases en los dos casos (change `demo-user`, design D1). Fuera de `up` por el motivo
# de `bootstrap` y `seed-demo` (DoD §28.20), y `python -m` en vez de `uv run` por el mismo también:
# el venv está en el PATH de todas las etapas de backend/devops/Dockerfile y `uv` sólo en la de
# desarrollo, así que este comando literal funciona igual contra la imagen desplegada.
#
# Necesita `DEMO_ACCOUNT_PASSWORD` en el `.env` —una sola variable, sin valor por defecto en el
# árbol— y se niega a escribir nada si falta o tiene menos de PASSWORD_MIN_LENGTH caracteres. En el
# entorno remoto la sirve el OCI Vault y la pasa el workflow; aquí la pones tú. Cómo rotarla:
# `docs/demo-tenant.md`.
#
# Imprime la URL del portal de huésped de la estancia activa. Es la única credencial que este
# comando emite a propósito (R2.5 tiene una excepción y es ésta): su valor en claro existe una
# sola vez, así que si no se imprime se pierde.
demo-reset:
	$(COMPOSE) exec backend python -m app.cli.demo_reset

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

# Corre el build de producción del frontend, que es lo ÚNICO que valida las fronteras
# Server/Client de React. Ni `tsc` ni Vitest ni ESLint las ven: un Client Component que
# importa `server-only` type-checkea, pasa sus tests y rompe el build. Eso llegó a `main`
# en `notifications-inbox-web` (PR #136) porque el build vivía sólo en el job
# `provenance-contract` de CI y no había forma de invocarlo aquí — el defecto se descubrió
# después de abrir el PR, no antes.
#
# Los cuatro APP_PROVENANCE_* son centinelas de relleno, los mismos que exporta ese job: el
# build los exige presentes, y sus valores no importan porque este target no comprueba la
# divulgación de procedencia, sólo que la aplicación compila. Para eso está
# `npm run test:public-artifacts` dentro del propio job.
#
# `exec` y no `run`: el servicio de frontend usa `target: dev` en todos los compose, así que
# el build se hace dentro del contenedor ya levantado, contra el mismo node_modules que usa
# el desarrollo. Requiere el stack arriba (`make up`).
check-frontend-build:
	$(COMPOSE) exec -T \
		-e APP_PROVENANCE_REPOSITORY_URL=https://github.com/local/check \
		-e APP_PROVENANCE_PULL_REQUEST_NUMBER=0 \
		-e APP_PROVENANCE_COMMIT_SHA=0000000000000000000000000000000000000000 \
		-e APP_PROVENANCE_ACTIONS_RUN_ID=0 \
		frontend npm run build

# Lista los stacks de Compose vivos en la máquina y marca los huérfanos (su directorio de
# origen ya no está registrado en `git worktree list`). Informa; no baja nada.
#
# Deliberadamente **fuera de `$(COMPOSE)`**, y es el segundo target que no lo usa: el ámbito
# de este diagnóstico es la máquina y no este proyecto, así que pasarlo por `$(COMPOSE)` lo
# acotaría a los ficheros de este directorio y dejaría fuera justo los stacks que busca.
#
# Y queda prohibido «mejorarlo» con `docker compose config` SIN `--no-interpolate
# --no-env-resolution`, o con un `docker inspect` sin `--format`: el primero, desnudo, resuelve e
# imprime los valores del `.env` (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `ENCRYPTION_KEY`) y la
# salida por defecto del segundo incluye `.Config.Env`. La primera mitad se acotó por forma en el
# change `compose-ports-guard`, cuando la guardia de puertos necesitó `config` como única fuente
# correcta; este script sigue sin necesitarlo, porque le basta `docker compose ls`.
compose-stacks:
	python3 scripts/compose-stacks.py

# Comprueba la postura de red del compose local: ningún puerto publicado fuera de 127.0.0.1,
# salvo los dos pares servicio+puerto exentos a propósito (backend:8000, frontend:3000). Es la
# guardia que sostiene la exención de POSTGRES_PASSWORD de steering/security.md regla 8, y corre
# también en CI (.github/workflows/compose-ports.yml).
#
# Deliberadamente **fuera de $(COMPOSE)**, y es el tercero de los cinco targets host-side que no
# lo usan (`check-version-parity`, `compose-stacks`, éste, `ports` y `check-rule11-ownership`) — pero
# por un motivo distinto del de compose-stacks, así que no se lee del de arriba. Aquí no es que
# el ámbito sea la máquina: es que pasar por $(COMPOSE) añadiría docker-compose.worktree.yml en
# un worktree enlazado, que retira los cuatro mapeos, y entonces la guardia vería CERO claves
# `ports` y daría verde sin haber comprobado nada. Invocando Compose desnudo da el mismo
# veredicto en el principal, en un worktree enlazado y en CI, que es lo que la hace función solo
# del repositorio.
#
# El script invoca `docker compose config` con `--no-interpolate --no-env-resolution` SIEMPRE, y
# eso es lo que lo saca de la prohibición de más arriba: con las dos banderas la salida no
# contiene ningún valor del `.env` (medido), así que no hace falta `.env` ni lo hay que crear.
check-compose-ports:
	python3 scripts/compose-ports.py

# Comprueba que la propiedad de un sumidero de la regla 11 se declara en la tabla de
# steering/security.md y en ningún otro sitio: recorre la prosa y los docstrings del alcance que
# declara `SCOPE` y se pone en rojo nombrando fichero, línea y frase. Corre también en CI
# (.github/workflows/rule11-ownership.yml), y ahí está el motivo de que exista este target: hasta
# `rule11-guard-trigger-and-scope` la guardia vivía en `backend/tests/`, así que un commit de sola
# prosa —la forma de todo commit de `/sdd:archive`— no la ejecutaba.
#
# Fuera de $(COMPOSE), y es el **quinto** target host-side que no lo usa (`check-version-parity`,
# `compose-stacks`, `check-compose-ports`, `ports` y éste). El motivo es el suyo propio y no se lee
# de los otros cuatro: es una herramienta de stdlib que sólo lee ficheros del árbol, así que no
# necesita el stack — y meterla en $(COMPOSE) la ataría a un contenedor que ya no monta el árbol de
# prosa, porque este mismo change retira esos dos bind mounts.
#
# **Requiere Python >= 3.11** en el `python3` del host: la guardia usa `enum.StrEnum`. Por debajo de
# eso este target no da veredicto, muere con un `ImportError` — el suelo está declarado en
# specs/rule11-ownership-guard.md § Independencia del entorno. En CI da igual: ubuntu-latest trae 3.12.
check-rule11-ownership:
	python3 scripts/rule11-ownership.py

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

# Informa del desplazamiento vigente y de los cuatro mapeos efectivos, sin volver a arrancar nada.
#
# Lo DERIVA del stack vivo (`docker compose ps`) y no del overlay generado, y esa es la decisión:
# el fichero describe la última *intención* —la del último `make up` que pasó un número—, mientras
# que el stack describe lo que está corriendo. Así la respuesta es verdad aunque alguien levantara
# con otro número, y existe también en el worktree principal, donde no hay overlay ninguno.
#
# El stack parado y el stack sin puertos publicados son estados NORMALES: se informan y salen en
# verde. Un stack con desplazamientos incoherentes entre servicios se informa como tal, sin
# inventar un número que lo describa.
#
# Es el **cuarto** de los cinco targets host-side fuera de `$(COMPOSE)`, y aquí el motivo es otro
# más: pasar por
# `$(COMPOSE)` no cambiaría la respuesta —`ps` direcciona el proyecto por su nombre— pero ataría
# la consulta al conjunto de ficheros de la invocación, y entonces preguntar por el desplazamiento
# exigiría saberlo ya.
ports:
	@python3 scripts/compose-offset.py show

# `down`, `logs`, `ps` y `sh` NO necesitan que se les repita `PORT_OFFSET`, y conviene saberlo
# porque la lectura ingenua dice lo contrario. Direccionan el proyecto por su NOMBRE —que Compose
# saca del directorio, y el de cada worktree es distinto—, no por sus puertos, así que dan con el
# mismo stack con desplazamiento y sin él, y nunca acaban hablando con otro.
#
# Consecuencia que se lee mal si no está escrita: un `up` al que se le pasó `PORT_OFFSET` y un
# `down` posterior al que no operan sobre CONJUNTOS DE FICHEROS distintos. Es seguro precisamente
# porque el segundo no crea contenedores: `down` los para y los borra por proyecto. El único
# target que necesita el número es `up`, porque es el único que CREA los mapeos — y por eso un
# `make up SERVICE=<x>` parcial sin repetir el desplazamiento recrearía ese servicio sin puertos.
down:
	$(COMPOSE) down $(SERVICE)

logs:
	$(COMPOSE) logs -f $(SERVICE)

ps:
	$(COMPOSE) ps

sh:
	$(COMPOSE) exec $(if $(SERVICE),$(SERVICE),backend) sh
