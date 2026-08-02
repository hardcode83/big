# Proposal: api-contract-export

## Why

`steering/documentation.md` ya declara que **el contrato para el frontend es el OpenAPI
auto-generado por FastAPI** (sección Audiencias) y que todo endpoint nuevo debe llegar a él con
sus modelos de respuesta anotados. Pero ese contrato **no existe como artefacto**: vive solo en
memoria del proceso, servido en `/docs` de un backend que hoy escucha en `127.0.0.1:8000` de la
VM y al que el túnel de Cloudflare no enruta — verlo exige un túnel SSH (`RUNBOOK §7.4`).

Mientras tanto el backend ya expone cinco routers reales bajo `/api/v1` (`auth`, `users`,
`tenants`, `reservations`, `integrations`, 18 rutas) y Marta desarrolla el frontend contra
`frontend/lib/api/client.ts`, que devuelve `unknown` a propósito y delega en cada feature la
validación de su contrato (design D12 de `frontend-foundation`). **Hoy no hay ninguna fuente
compartida de la forma de esos endpoints.**

Hay además una discrepancia ya presente: los handlers de `app/core/errors.py` traducen
`RequestValidationError` al envoltorio `{error:{code,message,details}}` de PRD §23, pero el
OpenAPI generado sigue documentando el `HTTPValidationError` por defecto de FastAPI. El contrato
que hoy se serviría **describe mal los errores de todos los endpoints**. Ese defecto es real se
genere el fichero o no.

### Lo que este change NO es, y por qué importa decirlo

Es tentador justificarlo como red de seguridad contra breaking changes. **No lo es, y el
razonamiento hay que dejarlo escrito para no repetirlo mal más adelante.** En un monorepo donde
ambos lados viajan en el mismo commit y el compose pinea los cuatro servicios al mismo
`${IMAGE_TAG}` no existe *version skew* — es el mismo argumento con el que la decisión D6 de
`app-version-visibility` **descartó** (no aplazó) la detección de deriva frontend↔backend.

Y el gate de R2 no atrapa una rotura: comparar el contrato regenerado con el commiteado solo
detecta *"se olvidó regenerarlo"*. Renombrar un campo de un `response_model` deja el check en
verde en cuanto se regenera, y el frontend sigue compilando porque `client.ts` devuelve
`unknown`. **Lo que atrapa esa rotura es `tsc` contra los tipos derivados del contrato, y eso vive
en `frontend-ci`, no aquí.**

Lo que este change compra, entonces, es concreto y acotado:

1. **Señal de revisión**: el diff del contrato aparece en el Pull Request que lo provoca, así que
   quien revisa ve que una respuesta cambió de forma sin leerse el router. Es revisión, no
   prevención.
2. **Frontera de artefacto entre los dos CI**: con el contrato en el repositorio, el job del
   frontend deriva sus tipos sin instalar Python, `uv` ni las dependencias del backend. Sin
   fichero, `frontend-ci` sería un job de Node que arranca el backend entero.
3. **Corregir la forma de error documentada** (R3), que está mal hoy.

## What changes

Tras este change el repositorio contiene el documento OpenAPI **commiteado**, generado de forma
determinista desde `create_app()` por un target de Makefile, y un check en CI cuyo único cometido
es mantener ese fichero veraz: falla cuando no corresponde al código, para que el diff del
contrato aparezca en el Pull Request que lo provoca. Se corrige además la forma documentada de
los errores para que coincida con la que el backend devuelve de verdad, y se documenta cómo
derivar tipos de él — sin tocar `frontend/**`.

## Requirements

### R1 — Generación determinista del contrato

**As a** desarrollador de backend, **I want** un comando que vuelque el OpenAPI a un fichero
versionado, **so that** el contrato sea un artefacto reproducible y no el estado de un proceso.

Acceptance criteria:

1. WHEN se ejecuta el target de Makefile de generación, THE SYSTEM SHALL escribir el documento
   OpenAPI de `create_app()` en una ruta versionada del repositorio.
2. THE SYSTEM SHALL producir una salida **byte-idéntica** en ejecuciones sucesivas sobre el mismo
   código (orden de claves estable, indentación fija, newline final). Sin esto el check de R2
   sería inestable y se leería como test flaky.
3. THE SYSTEM SHALL generar el documento **sin** base de datos, Redis ni red: importando la
   aplicación y serializando su esquema, nunca arrancando el servidor ni emitiendo una petición
   HTTP.
4. IF importar la aplicación exige configuración con apariencia de secreto (la clave JWT de ≥32
   caracteres que `app/core/config.py` valida al importar), THEN THE SYSTEM SHALL usar un valor de
   usar y tirar generado en el momento, sin versionar ninguno — mismo criterio que
   `specs/backend-ci.md` aplica al job de tests (regla 8 de `steering/security.md`).
5. THE SYSTEM SHALL dejar el fichero generado legible en un diff de Pull Request (JSON indentado,
   una clave por línea), no minificado.

### R2 — El fichero commiteado no puede quedarse obsoleto

**As a** revisor de un Pull Request, **I want** que CI falle cuando el contrato commiteado no
corresponde al código, **so that** el diff que leo en el PR describa la API real y no una foto
vieja.

**Alcance real de este requisito, explícito**: detecta *"se olvidó regenerar el fichero"* y nada
más. Un cambio incompatible (renombrar un campo, estrechar un tipo) deja este check en verde en
cuanto se regenera. Quien lo atrapa es el typecheck del frontend contra los tipos derivados, en
`frontend-ci`. Este requisito existe para que la señal de revisión del punto 1 de §Why sea
fiable, no para prevenir roturas.

Acceptance criteria:

1. WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL regenerar
   el contrato y compararlo con el fichero commiteado.
2. IF ambos difieren, THEN THE SYSTEM SHALL fallar la verificación mostrando la diferencia y el
   comando exacto que la resuelve.
3. THE SYSTEM SHALL ejecutar la comprobación **sin filtro de rutas**, aunque el diff no toque
   `backend/**` — mismo motivo que `specs/backend-ci.md` documenta para `backend-tests`: un check
   con filtro de rutas deja bloqueados indefinidamente los PR que no las tocan.
4. THE SYSTEM SHALL reutilizar exactamente el mismo generador que R1, no una segunda
   implementación en el workflow.

### R3 — El contrato describe lo que el backend devuelve de verdad

**As a** consumidor del contrato, **I want** que los esquemas de respuesta y de error coincidan
con las respuestas reales, **so that** tipar contra el contrato no produzca código que falla en
runtime.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en el contrato la forma de error de PRD §23
   (`{error:{code,message,details}}`) como esquema, y referenciarla en las respuestas de error de
   los endpoints bajo `/api/v1`, **incluida la de validación (422)** — que hoy el OpenAPI
   describe con el `HTTPValidationError` por defecto de FastAPI, forma que
   `app/core/errors.py` no devuelve nunca.
2. THE SYSTEM SHALL fallar la verificación si un endpoint registrado bajo `/api/v1` cuyo código de
   éxito no es `204 No Content` carece de modelo de respuesta declarado. Es una guarda de
   regresión, no trabajo de remediación: las 18 rutas actuales ya cumplen (las tres sin
   `response_model` son `POST /auth/logout`, `DELETE /users/{id}` y
   `DELETE /reservations/{id}`, las tres `204` legítimas).
3. THE SYSTEM SHALL verificar la coherencia de forma estructural sobre las rutas registradas en la
   aplicación, no contra una lista de endpoints mantenida a mano — mismo patrón que
   `backend/tests/test_route_authorization.py`.

### R4 — Consumo documentado

**As a** desarrolladora de frontend, **I want** saber dónde está el contrato y cómo derivar tipos
de él, **so that** no tenga que adivinar la forma de la API ni pedir un túnel SSH.

Acceptance criteria:

1. THE SYSTEM SHALL documentar la ruta del fichero, el comando que lo regenera y el comando
   recomendado para derivar tipos TypeScript a partir de él.
2. WHERE `steering/documentation.md` describe el contrato para el frontend, THE SYSTEM SHALL
   actualizar esa referencia para que apunte al artefacto versionado y no solo al `/docs` servido.

## Out of scope

- **Prevenir cambios incompatibles de la API.** Ningún requisito de este change lo hace, y R2 dice
  explícitamente por qué no puede: el gate solo mantiene veraz el fichero. La verificación que
  rompe ante un cambio incompatible es el typecheck del frontend contra los tipos derivados del
  contrato, asignada a `frontend-ci`. Registrado aquí para que nadie lea este change como una red
  de seguridad que no es.
- **Detección de deriva frontend↔backend en tiempo de despliegue.** Descartada, no aplazada, por
  la decisión D6 de `app-version-visibility`: el monorepo construye ambas imágenes del mismo
  commit y el compose pinea los cuatro servicios al mismo `${IMAGE_TAG}`.
- **Cablear los tipos generados en el frontend** (script npm, `.d.ts`, tipar `createApiClient` o
  las features). Este change no modifica ningún fichero bajo `frontend/**`: el consumo es un
  change propio del lado de Marta, que este habilita. **Tiene dueño asignado**: la entrada
  `frontend-ci` del roadmap, ampliada el 2026-08-01 para cubrir el lado consumidor (derivar los
  tipos del `openapi.json` que deja este change, cablearlos en `frontend/lib/api/` y comprobar en
  el workflow que no han derivado). No queda huérfano.
- **Exponer el contrato o la API públicamente.** Depende de `api-ingress-routing`, la siguiente
  entrada del roadmap. Este change hace el contrato accesible *desde el repositorio*, que es
  precisamente lo que lo desacopla de esa dependencia.
- **Versionado semántico del contrato o política de deprecación** (`/api/v2`, cabeceras de
  versión, ventana de compatibilidad). El MVP tiene un solo consumidor y ambos lados viajan en el
  mismo commit del monorepo; abrir esto ahora es ceremonia sin destinatario.
- **Generar clientes SDK** para otros lenguajes o publicar el contrato fuera del repositorio.
- **Marcar el check como obligatorio.** El repositorio es privado en un plan sin protección de
  rama (`specs/backend-ci.md` §Estado): se ejecuta y reporta, igual que `backend-tests`.

## Affected specs

- `sdd/specs/api-contract.md` — *(no existe aún — se creará al archivar)*: generación, gate de
  deriva y garantías de forma del contrato.
- `sdd/specs/backend-ci.md` — se modificará si el gate de R2 vive como paso de
  `backend-tests.yml` en lugar de como workflow propio (decisión de `/sdd:design`). Su sección
  §Estado también menciona hoy que el frontend tiene comandos que ningún workflow ejecuta.
- `sdd/steering/documentation.md` — R4.2 actualiza la referencia al contrato en §Audiencias.
