# Proposal: app-version-provenance

## Why

`app-version-visibility` ya muestra la identidad del build desplegado, pero no
permite responder desde la aplicación qué Pull Request produjo esa versión ni
abrir directamente su commit y su ejecución de GitHub Actions. Esa información
es útil para diagnóstico y rollback, pero hoy no puede publicarse en superficies
anónimas porque los enlaces revelarían el repositorio privado. Esta propuesta
retoma únicamente el panel de procedencia y la verificación de paridad que se
recortaron de `app-version-visibility`; parte de que el frontend ya dispone de
autenticación (`frontend-auth-session`) y de la identidad de build establecida
por `build-identity-contract`.

La fuente de alcance y decisiones previas es `sdd/roadmap/app-version-provenance.md`,
junto con `sdd/specs/app-version-visibility.md` y el cambio archivado
`2026-07-31-app-version-visibility`.

## What changes

Se añadirá a la superficie autenticada de operación un panel de procedencia que
relacione la versión visible con el Pull Request, commit y run de Actions que la
produjeron. El CD producirá la identidad de provenance y una frontera autenticada
la entregará al consumidor, después de aplicar autenticación antes de devolver
los metadatos privados. Esa frontera no consultará GitHub en runtime. El CD
extraerá de forma segura el número de PR desde los formatos soportados del
subject del merge commit. Se incorporará un self-test/regression test para esa
extracción y un gate ejecutable desde el host que detecte divergencias entre
`VERSION`, `backend/pyproject.toml` y `frontend/package.json`.

## Requirements

### R1 — Panel autenticado de procedencia

**Como** operador autenticado, **quiero** ver qué cambio produjo la versión
desplegada, **para** poder investigar o confirmar un rollback sin entrar en la
VM.

Acceptance criteria:

1. WHEN un usuario autenticado abre el panel de procedencia, THE SYSTEM SHALL
   mostrar la identidad de versión desplegada junto con enlaces al Pull Request,
   commit y ejecución de GitHub Actions que la produjeron.
2. THE SYSTEM SHALL entregar la URL privada del repositorio, el número de PR, el
   SHA completo y el run ID únicamente después de autenticación, mediante una
   frontera que aplique autenticación antes de devolverlos. La identidad SHALL
   seguir originándose en el CD, esos metadatos privados SHALL NOT hornearse
   directamente en el frontend y la frontera SHALL NOT consultar GitHub en
   runtime.
3. IF falta algún dato de procedencia o no tiene el formato admitido, THEN THE
   SYSTEM SHALL mostrar un estado localizado de procedencia desconocida y no
   renderizar enlaces rotos ni valores parciales.
4. THE SYSTEM SHALL mostrar el panel solo dentro de una superficie autenticada
   de operación. La URL privada del repositorio, el número de PR, el SHA
   completo y el run ID SHALL NOT aparecer en `NEXT_PUBLIC_*`,
   `PublicRuntimeConfig`, props del root layout, HTML anónimo, assets estáticos,
   bundles JS accesibles anónimamente, `/login` ni `/guest/[token]`.

### R2 — Extracción segura del Pull Request

**Como** mantenedor del CD, **quiero** extraer el número de PR de forma
determinista, **para** que la procedencia no confunda números de incidencias con
Pull Requests.

Acceptance criteria:

1. WHEN el CD procesa el subject de un merge commit, THE SYSTEM SHALL extraer el
   número únicamente de los formatos de merge de Pull Request soportados,
   incluido `Merge pull request #N ...` y el sufijo `título (#N)`.
2. IF el subject contiene solo un número de incidencia o un formato no
   soportado, THEN THE SYSTEM SHALL dejar la procedencia del PR desconocida y no
   inferir un enlace.
3. THE SYSTEM SHALL incluir un self-test ejecutable del extractor y una prueba
   de regresión que cubra los formatos válidos, números de incidencia y entradas
   ambiguas.

### R3 — Contrato de identidad de procedencia entre CD y frontend

**Como** mantenedor del proyecto, **quiero** que el productor del CD y el
consumidor del frontend compartan un contrato verificable, **para** evitar que
un cambio de formato publique enlaces incorrectos o filtre datos.

Acceptance criteria:

1. WHEN un Pull Request modifica el productor de identidad o el consumidor
   público de procedencia, THE SYSTEM SHALL ejecutar un gate de congruencia que
   verifique los campos, formatos y reglas de ausencia definidos por el contrato.
2. IF el productor genera un formato que el consumidor no admite, THEN THE
   SYSTEM SHALL fail the gate antes de permitir el merge.
3. THE SYSTEM SHALL mantener permanentemente fuera del snapshot público del
   frontend la URL del repositorio, el número de PR, el SHA completo y el run ID.
   La existencia de un `AuthGuard` o de autenticación client-side SHALL NOT
   permitir publicar esos datos en el contrato público; solo una frontera que
   aplique autenticación antes de devolverlos puede entregarlos al consumidor.

### R4 — Gate de paridad de versiones

**Como** mantenedor del monorepo, **quiero** detectar versiones declaradas que
divergen de `VERSION`, **para** que los manifiestos no contradigan la identidad
del build.

Acceptance criteria:

1. WHEN se ejecuta el gate de paridad desde el host, THE SYSTEM SHALL comparar la
   versión de `VERSION` con los campos `version` de `backend/pyproject.toml` y
   `frontend/package.json`.
2. IF alguno de los tres valores falta, está vacío o diverge, THEN THE SYSTEM
   SHALL devolver un código de salida distinto de cero y nombrar cada archivo
   problemático.
3. THE SYSTEM SHALL exponer el gate mediante un target de Makefile ejecutable
   desde la raíz, porque los contenedores de backend y frontend no montan la
   raíz completa del monorepo.

## Out of scope

- Crear el badge, la identidad base del build, los labels OCI o el contrato
  inicial de `VERSION`; pertenecen a `app-version-visibility` y
  `build-identity-contract`.
- Crear o modificar la autenticación del frontend; la propuesta consume la
  sesión autenticada existente.
- Publicar procedencia en `/login`, `/guest/[token]` o cualquier otra superficie
  anónima.
- Consultar GitHub en runtime o introducir secretos, tokens o credenciales para
  obtener la procedencia.
- Decidir si la frontera autenticada será un endpoint backend protegido, un
  Route Handler/BFF u otra frontera server-side equivalente; esa decisión
  corresponde a `/sdd:design`.
- Añadir un endpoint backend `/version` o detectar deriva entre las imágenes de
  backend y frontend; la decisión vigente lo descarta mientras ambas se
  construyan con el mismo commit y `IMAGE_TAG`.
- Git tags, releases, SemVer operativo, rollback automático o soporte de
  staging/producción.

## Affected specs

- `sdd/specs/app-version-provenance.md` — crear *(no existe aún — se creará al
  archivar)*: panel autenticado, contrato de procedencia, extractor y gate de
  paridad.
- `sdd/specs/app-version-visibility.md` — modificar: frontera entre identidad
  pública ya existente y procedencia privada autenticada.
- `sdd/specs/app-deploy-dev.md` — modificar: publicación de metadatos de PR,
  commit y ejecución de Actions.
- `sdd/specs/frontend-foundation.md` — modificar: superficie autenticada y
  configuración del panel de procedencia.
- `sdd/specs/frontend-ci.md` — modificar: gate de congruencia productor/
  consumidor.
