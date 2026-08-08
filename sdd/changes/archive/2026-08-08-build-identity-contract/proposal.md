# Proposal: build-identity-contract

## Why

La identidad pública del build cruza hoy tres contratos que evolucionan por separado:
`VERSION`, la composición del job `provenance` en `.github/workflows/deploy-dev.yml` y la
frontera de divulgación de `frontend/lib/config/public.ts`. El frontend falla cerrado y
descarta cualquier forma inesperada, pero nada comprueba que el CD siga produciendo una forma
admitida; ensanchar el SHA corto, alterar la fecha o relajar `VERSION` convertiría el badge en
«versión desconocida» sin hacer fallar ningún check.

Este cambio convierte esa congruencia implícita —registrada como deuda en
`sdd/specs/app-version-visibility.md` y en la entrada homónima del roadmap— en un contrato
ejecutable. Sirve al operador y al mantenimiento del pipeline: no amplía la identidad que se
publica ni la funcionalidad visible del producto.

## What changes

El repositorio tendrá una verificación automática que enfrenta la identidad realmente
compuesta por el CD con las formas que la frontera pública admite. La verificación cubrirá la
forma de producción (`X.Y.Z+YYYY-MM-DD.<7 hex>` y su commit pareado), preservará la excepción
local (`local` sin commit) y hará fallar el check antes de construir imágenes cuando productor
y consumidor diverjan. La frontera pública seguirá descartando valores no admitidos.

## Requirements

### R1 — Contrato único y verificable de identidad de producción

**As a** operador, **I want** que la identidad compuesta por el CD satisfaga el contrato
público del frontend, **so that** un despliegue válido no degrade silenciosamente a «versión
desconocida».

Acceptance criteria:

1. WHEN el job `provenance` compone una identidad de producción, THE SYSTEM SHALL verificar
   el valor final contra la forma `X.Y.Z+YYYY-MM-DD.<7 hex minúsculos>`, usando una fecha UTC
   de calendario válida.
2. WHEN el job `provenance` compone `version` y `commit_short`, THE SYSTEM SHALL verificar que
   el sufijo de commit de `version` sea exactamente el mismo valor de 7 hexadecimales
   minúsculos que `commit_short`.
3. IF `VERSION`, la fecha, el SHA corto o la identidad final no satisfacen el contrato, THEN
   THE SYSTEM SHALL finalizar `provenance` con error antes de publicar sus outputs y antes de
   que se construya imagen alguna.
4. THE SYSTEM SHALL comprobar los valores finales que consumen los builds, no solo validar
   por separado las entradas con las que se componen.

### R2 — Detección automática de deriva productor-consumidor

**As a** persona mantenedora, **I want** que los cambios en el productor o en el consumidor
se comprueben juntos, **so that** modificar uno sin actualizar deliberadamente el otro rompa
un check y no el badge desplegado.

Acceptance criteria:

1. WHEN una verificación automatizada evalúa el contrato, THE SYSTEM SHALL demostrar que una
   identidad de producción realmente compuesta por el CD es aceptada por la frontera pública
   del frontend junto con su `commit_short` pareado.
2. WHEN la forma de identidad producida por el CD deje de ser aceptada por el contrato público
   vigente del frontend, THE SYSTEM SHALL hacer fallar la verificación de congruencia.
3. WHEN un Pull Request incluya cambios que afecten al productor CD o al consumidor público de
   identidad, THE SYSTEM SHALL incluir una verificación obligatoria de congruencia entre los
   checks de CI aplicables al Pull Request.
4. THE SYSTEM SHALL mantener verificables como casos negativos, al menos, un SHA de longitud
   distinta de 7, una fecha fuera de la forma canónica y una base que no sea `X.Y.Z`.

### R3 — Excepción local acotada y límite de divulgación intacto

**As a** desarrolladora, **I want** conservar una identidad local explícita y segura,
**so that** el stack de desarrollo arranque sin fingir una procedencia de producción.

Acceptance criteria:

1. WHERE `docker-compose.yml` arranca el frontend sin identidad horneada de producción, THE
   SYSTEM SHALL seguir usando `appVersion = "local"` y `buildCommitShort = ""` como la única
   pareja local admitida.
2. WHEN la verificación automatizada evalúa la pareja local, THE SYSTEM SHALL aceptarla sin
   exigir fecha ni commit.
3. IF cualquier valor público queda fuera de la forma de producción o de la excepción local,
   THEN `buildPublicRuntimeConfig()` SHALL seguir reduciéndolo a cadena vacía; el nuevo gate
   no sustituye ni relaja esa frontera de divulgación.
4. THE SYSTEM SHALL NOT añadir al snapshot público el SHA completo, el número de Pull Request,
   el `run_id`, el `ref` ni la URL del repositorio.

## Out of scope

- Cambiar la forma canónica de la versión, la longitud de 7 hexadecimales o el badge visible;
  este cambio verifica el contrato vigente, no lo rediseña.
- El panel de procedencia y los enlaces a PR, commit o ejecución → `app-version-provenance`,
  bloqueado hasta que el frontend tenga autenticación.
- El gate de paridad entre `VERSION`, `backend/pyproject.toml` y `frontend/package.json` →
  `app-version-provenance`.
- Versionado con git tags, releases o CHANGELOG, y pineado de imágenes por digest.
- Detección de deriva entre frontend y backend o un endpoint `/version`.
- Cambios de despliegue en staging/prod; el único pipeline afectado es el de `dev`.

## Affected specs

- `sdd/specs/app-version-visibility.md` — modificar: sustituir el hueco conocido por el
  contrato ejecutable que enlaza la forma admitida con la identidad producida.
- `sdd/specs/app-deploy-dev.md` — modificar: el job `provenance` valida sus outputs finales y
  bloquea los builds ante cualquier deriva del contrato.
