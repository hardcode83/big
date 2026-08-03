# Integración continua del backend

## Purpose

Esta capacidad ejecuta en GitHub Actions, sobre un entorno limpio y en cada Pull Request,
la misma verificación que `sdd/project.md` manda ejecutar en local: migraciones, coherencia
esquema↔modelos y la suite completa del backend. Existe para que "la suite está verde" sea
un hecho reproducible por cualquiera y no una afirmación de la máquina de quien la ejecutó.

Es una capacidad separada del despliegue (`app-deploy-dev`): valida, no publica ni despliega.

No es el único workflow que valida el backend en cada PR: `api-contract` comprueba que
`backend/openapi.json` corresponde al código (`specs/api-contract.md`). Vive aparte porque no
necesita PostgreSQL ni Redis y da señal en segundos, y porque mezclar ambas señales haría que
olvidar regenerar el contrato cortara la ejecución antes de la suite.

## Requirements

### Disparadores y alcance

- WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL
  ejecutar el workflow `backend-tests`.
- THE SYSTEM SHALL **reportar siempre un resultado del check `backend-tests`**, toque el diff
  el backend o no. Este es el invariante del que dependen los demás: un check requerido que
  *no se ejecuta* deja el Pull Request bloqueado esperando indefinidamente uno que no va a
  llegar, mientras que uno que se ejecuta y reporta verde en segundos no bloquea a nadie.
- THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`**. La prohibición sigue en pie y por el
  motivo original: un filtro de rutas a nivel de disparador no produce check alguno en los PR
  que no tocan esas rutas. El filtrado ocurre **dentro** del workflow, no en su disparador.
- THE SYSTEM SHALL estructurarlo en tres jobs: `backend-tests-detect` decide el área a partir
  del diff, `backend-tests-suite` corre la verificación completa **solo si** la detección dice
  que el diff toca el backend, y `backend-tests` publica el resultado con `if: always()` — que
  es lo que garantiza el invariante incluso cuando la suite se salta.
- THE SYSTEM SHALL cancelar la ejecución anterior de la misma referencia cuando llega una
  nueva (`concurrency` con `cancel-in-progress`), y limitar cada job a su propio tope: 5
  minutos para detección y publicación, 20 para la suite.
- THE SYSTEM SHALL conceder al workflow solo `contents: read`.

### Detección del área y camino corto

- THE SYSTEM SHALL derivar del diff una decisión booleana sobre si el cambio afecta al backend,
  y exponerla junto a un **motivo legible** como salidas del job de detección.
- WHEN la detección concluye que el diff **no** toca el backend, THE SYSTEM SHALL saltarse la
  suite y publicar el check en verde con ese motivo, de modo que un PR que solo toca
  documentación o `sdd/` obtenga su resultado en segundos en lugar de esperar la suite entera.
- WHEN la detección concluye que **sí** lo toca, THE SYSTEM SHALL ejecutar la verificación
  completa descrita abajo **sin recortarla**: el camino corto es una vía rápida para diffs
  ajenos al backend, nunca una versión reducida de la verificación.
- IF la detección falla o no puede determinar el área, THEN THE SYSTEM SHALL decidir a favor de
  ejecutar la suite: la decisión **arranca en «sí toca»** y solo una comprobación afirmativa la
  baja. Equivocarse hacia «ejecuta» cuesta minutos; equivocarse hacia «salta» publica un verde
  que no verificó nada.
- THE SYSTEM SHALL leer el diff con las rutas **sin escapar** (`core.quotePath=false`) y
  separadas por NUL (`-z`). Por defecto git escapa las rutas no ASCII y las entrecomilla, con lo
  que un patrón anclado en `backend/` no casaría: un PR cuyo único cambio de backend fuera un
  fichero con acento se saltaría la suite y el check saldría **verde**.
- THE SYSTEM SHALL leer el diff **sin detección de renombrados** (`--no-renames`). Con
  renombrados activos un movimiento colapsa a la ruta destino, así que un PR que **saca** un
  módulo de `backend/` se juzgaría «no toca el backend» y publicaría verde con código del
  backend desaparecido.
- THE SYSTEM SHALL comparar cada ruta individualmente en lugar de aplicar una expresión regular
  sobre el conjunto concatenado, para que un acierto parcial no pueda decidir por el conjunto.

### Servicios de los que depende

- THE SYSTEM SHALL levantar PostgreSQL 16 **y** Redis 7 como services, ambos con
  healthcheck.
- Redis no es opcional: los tests del adaptador de throttle (la única implementación de
  producción del límite por IP y del bloqueo por cuenta) están escritos deliberadamente
  **sin** `skip`, así que sin ese servicio fallan en rojo en lugar de desaparecer en el
  contador de omitidos.

### Pasos verificados

- THE SYSTEM SHALL aplicar `alembic upgrade head` sobre una base de datos PostgreSQL recién
  creada. La suite construye su esquema con `Base.metadata.create_all`, así que por sí sola
  no probaría la cadena real de migraciones.
- THE SYSTEM SHALL ejecutar `alembic check`, que falla si los modelos y el esquema migrado
  han divergido.
- THE SYSTEM SHALL ejecutar la suite completa (`pytest -q -rs`), que incluye autenticación,
  rotación y reutilización concurrente de tokens, RBAC, aislamiento por tenant y el test
  estructural de autorización de rutas. El flag `-rs` deja en el log el motivo de cada test
  omitido, para que el recuento de omitidos sea auditable y no un número opaco.
- THE SYSTEM SHALL ejecutar `alembic downgrade base`, que ningún test cubre y es lo que
  ejecuta un operador cuando un deploy sale mal.

### Secretos y dependencias

- WHEN el job arranca, THE SYSTEM SHALL generar una clave JWT de usar y tirar con
  `openssl rand -hex 32`. La configuración exige una clave de al menos 32 caracteres al
  importar, pero esa clave no firma nada que salga del job — así no hay ningún valor con
  apariencia de secreto versionado (regla 8 de `steering/security.md`).
- THE SYSTEM SHALL instalar las dependencias con `uv sync --frozen`, que falla si
  `uv.lock` no está sincronizado con `pyproject.toml`.
- THE SYSTEM SHALL pinear cada action de terceros por SHA de commit, siguiendo la
  convención de los demás workflows del repo.

### Aislamiento entre ejecuciones concurrentes

- THE SYSTEM SHALL dar a cada proceso de pytest sus propias bases de datos, con un sufijo
  por proceso (`<db>_test_<pid>`, `<db>_migrations_<pid>`), y borrarlas al cerrar la sesión.
- Es un requisito, no una comodidad: la fixture de migraciones abre con
  `DROP DATABASE IF EXISTS`, así que con nombres fijos una segunda ejecución concurrente
  borraría la base de datos que la primera está usando, y el fallo se leería como un test
  inestable en lugar de como una colisión.
- WHERE `PYTEST_DB_SUFFIX` está definida, THE SYSTEM SHALL usar ese sufijo en lugar del pid,
  para que un job de CI pueda fijar un nombre reproducible.
- `make db-clean-test` borra las bases huérfanas que deje una ejecución interrumpida, sin
  tocar la base de datos de desarrollo.

## Coste

- **Medido el 2026-08-03**: la suite tarda **~6m15s** y el workflow completo **~7m05s**; el paso
  dominante es `pytest`. El camino corto —diff que no toca el backend— cuesta **segundos**,
  porque el job de detección no levanta `services:` ni instala dependencias: solo necesita git.
- La cifra se registra **fechada y con el paso dominante identificado** a propósito. Una versión
  anterior de la cabecera del workflow afirmaba «~1 minuto», y sobre esa cifra obsoleta se tomó
  una decisión de pipeline. Cualquier decisión futura sobre este gate debe partir de una medición
  con fecha, no de la anterior heredada.
- **Reducir esos 6m15s queda fuera de esta capacidad**: es la palanca mayor y la única que ayuda
  también a los PR que **sí** tocan el backend, pero es trabajo sobre la suite, no sobre el
  workflow.

## Estado

- **Limitación conocida**: el repositorio es privado en un plan que no permite protección de
  rama (la API responde `403: Upgrade to GitHub Pro or make this repository public`), así
  que este check **no puede marcarse como obligatorio** todavía. Se ejecuta y reporta en
  cada PR, pero nada impide fusionar con él en rojo. Convertirlo en gate real exige GitHub
  Pro o hacer público el repositorio; queda como decisión pendiente.
- No hay comando de lint ni de typecheck en el proyecto: `sdd/project.md` no declara ninguno
  y este workflow no inventa uno.
- El frontend tiene su workflow independiente `frontend-tests`, descrito en
  `sdd/specs/frontend-ci.md`; `backend-tests` no duplica sus verificaciones.

## Key files

- `.github/workflows/backend-tests.yml`.
- `backend/tests/db_names.py` — sufijo por ejecución de las bases de datos desechables.
- `backend/tests/conftest.py` — creación y borrado de la base de datos de la suite.
- `backend/tests/test_migrations.py` — cadena de migraciones contra una base desechable.
- `Makefile` — target `db-clean-test`.
