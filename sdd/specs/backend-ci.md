# Integración continua del backend

## Purpose

Esta capacidad ejecuta en GitHub Actions, sobre un entorno limpio y en cada Pull Request,
la misma verificación que `sdd/project.md` manda ejecutar en local: migraciones, coherencia
esquema↔modelos y la suite completa del backend. Existe para que "la suite está verde" sea
un hecho reproducible por cualquiera y no una afirmación de la máquina de quien la ejecutó.

Es una capacidad separada del despliegue (`app-deploy-dev`): valida, no publica ni despliega.

## Requirements

### Disparadores y alcance

- WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL
  ejecutar el workflow `backend-tests`.
- THE SYSTEM SHALL ejecutarlo **sin filtro de rutas**, aunque el diff no toque `backend/**`.
  Un check requerido con filtro de rutas no se ejecuta en los PR que no las tocan, y GitHub
  deja esos PR bloqueados esperando indefinidamente un check que no va a llegar.
- THE SYSTEM SHALL cancelar la ejecución anterior de la misma referencia cuando llega una
  nueva (`concurrency` con `cancel-in-progress`), y limitar el job a 20 minutos.
- THE SYSTEM SHALL conceder al workflow solo `contents: read`.

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
