# Design: frontend-api-contract-consumer

## Context

El backend ya versiona `backend/openapi.json`, generado de forma determinista por
`api-contract-export`. El frontend todavía tiene un transporte genérico en
`frontend/lib/api/client.ts` cuya API pública devuelve `unknown` y cuyos tests usan rutas
inventadas como `/things`; `frontend/lib/api/errors.ts` conserva además la guarda runtime del
envelope de errores. `frontend/package.json` no tiene hoy un generador OpenAPI ni scripts para
derivar tipos, y `.github/workflows/frontend-tests.yml` cubre la calidad general del frontend,
pero el roadmap mantiene este gate de contrato separado de `frontend-ci`.

El diseño añade únicamente la frontera de consumo: un artefacto de tipos generado desde el
contrato commiteado, helpers de tipos para que el transporte genérico infiera operación, cuerpo y
respuesta, y un workflow reproducible que detecte deriva. No introduce endpoints, SDKs,
repositorios, servicios de dominio ni conexión funcional del dashboard.

## Decisions

### D1 — Generador oficial OpenAPI → TypeScript

**Chosen:** `openapi-typescript`, fijado como `devDependency` exacta en
`frontend/package.json` y `frontend/package-lock.json`. Se invocará mediante un único script
versionado del frontend, que recibe siempre `backend/openapi.json` como fuente y escribe
`frontend/lib/api/generated/openapi.d.ts`.

La herramienta genera declaraciones TypeScript a partir del documento sin crear runtime,
clientes ni wrappers por endpoint. Eso encaja con el alcance y permite que el transporte existente
conserve sus hooks de headers, `401`, `fetch` inyectable y `parseApiError`.

Rejected: Orval o Hey API — generan superficies de cliente adicionales y convenciones por
endpoint que exceden el límite de este change. Un esquema TypeScript escrito a mano — duplicaría
la fuente de verdad y permitiría deriva silenciosa. Ejecutar una herramienta no fijada con `npx` —
haría que cada máquina pudiera obtener una salida distinta.

### D2 — Script único y artefacto generado

**Chosen:** crear `frontend/scripts/generate-api-types.mjs` como única implementación del flujo de
generación. El script resolverá la ruta del contrato relativa al repositorio, invocará la API de
`openapi-typescript`, normalizará los saltos de línea a LF y garantizará un salto final antes de
escribir `frontend/lib/api/generated/openapi.d.ts`. `npm run api:generate` será el comando
documentado para regenerar; `npm run api:check` generará en un directorio temporal y comparará
bytes sin modificar el artefacto versionado.

El script no arrancará el backend ni leerá `/openapi.json` por HTTP: solo leerá el fichero
versionado. La normalización explícita evita diferencias de plataforma, mientras que el lockfile
y Node 22 (la misma versión declarada por `frontend/devops/Dockerfile` y `frontend-tests`) fijan
el entorno de generación.

Rejected: usar directamente un comando shell con rutas relativas (`npx ... -o ...`) como única
implementación — depende del directorio actual y de convenciones de quoting distintas entre
macOS, Linux y CI. Generar el fichero durante `next build` — oculta la deriva y mezcla un artefacto
de revisión con el proceso de empaquetado.

### D3 — Tipado del transporte sin wrappers por endpoint

**Chosen:** `frontend/lib/api/client.ts` importará los tipos generados y expondrá un método
genérico ligado a `paths` y a los métodos presentes en cada ruta. Helpers de tipos internos
extraerán de la operación seleccionada:

- el cuerpo JSON aceptado, cuando exista;
- la respuesta JSON de éxito;
- `undefined` para respuestas `204` o sin cuerpo.

La firma conceptual será `request<Path, Method>(path, options): Promise<ResponseFor<Path, Method>>`,
con `Path` y `Method` restringidos por el documento OpenAPI. El cliente seguirá resolviendo URL,
headers, serialización, respuesta no-OK y el hook de `401`; solo cambia la información estática
disponible al llamador. `frontend/lib/api/index.ts` reexportará los tipos públicos necesarios,
incluido el tipo `paths`, sin crear una API por dominio.

`Method` no será un `string` ni aceptará verbos arbitrarios: se inferirá exclusivamente de la
operación declarada en `paths` para el `Path` seleccionado. Por tanto, cada ruta solo admitirá los
métodos HTTP que existen en el documento OpenAPI; un verbo no declarado para esa ruta fallará en
typecheck y no podrá llegar al cliente como una opción válida.

No se crearán `ReservationsApi`, `CleaningApi`, `UserApi`, repositorios, servicios de dominio,
funciones por endpoint ni un runtime SDK. El flujo termina en `OpenAPI → tipos generados → cliente
HTTP genérico`.

Rejected: integrar un cliente runtime generado — impondría wrappers, manejo de errores y opciones
de transporte que duplican el cliente existente. Mantener `Promise<unknown>` con casts en cada
llamada — no elimina el `unknown` deliberado ni permite que el compilador relacione ruta y
método con el contrato.

### D4 — Compatibilidad del contrato público y de los tests

**Chosen:** conservar `ApiClientOptions`, los hooks `getHeaders`/`onUnauthorized`, el `fetchImpl`,
`joinUrl`, el envelope de errores y el tratamiento de `204`. `RequestOptions` pasará a ser
genérico para aceptar el cuerpo de la operación seleccionada, pero permitirá opciones sin cuerpo
cuando el contrato no declara uno. Los tests de `client.ts` sustituirán las rutas ficticias por
rutas reales del contrato (por ejemplo `/health` y las rutas de autenticación) sin ejecutar un
backend ni cambiar el escenario que validan.

`errors.ts` seguirá haciendo validación runtime de respuestas no-OK; no se convierte en un
generador de errores por endpoint. Los ajustes a mocks y fixtures se limitarán a satisfacer las
nuevas firmas.

Los tipos generados solo tiparán operaciones válidas y sus respuestas de éxito. El tratamiento de
errores continuará pasando por `ApiError` y `parseApiError`, sin generar tipos de error específicos
por endpoint ni cambiar la estrategia runtime existente.

Rejected: relajar las rutas a `string` y volver a `unknown` solo para mantener los tests actuales
— ocultaría precisamente la deriva que este change debe detectar. Conectar tests a un servidor
real — añadiría una dependencia funcional del backend fuera de alcance.

### D5 — Gate de deriva separado de `frontend-ci`

**Chosen:** crear `.github/workflows/frontend-api-contract.yml`, con los mismos disparadores,
permisos mínimos, Node 22, `npm ci`, concurrencia y actions fijadas por SHA que el workflow del
frontend. El job ejecutará `npm run api:check` desde `frontend/`, sin PostgreSQL, Redis ni filtro
de paths. Ante diferencias, el script imprimirá un diff legible y el comando `npm run api:generate`
que las resuelve; el job fallará.

El gate comparte la instalación reproducible del frontend pero no se inserta en
`frontend-tests.yml`: son señales distintas y este change no amplía la responsabilidad de
Vitest, ESLint, typecheck o build.

Rejected: un paso adicional dentro de `frontend-tests.yml` — mezcla la señal de deriva con las
verificaciones generales y hace que una falle antes de que las demás reporten. Un filtro por
`frontend/**` o `backend/openapi.json` — deja PRs sin el check visible y contradice la política de
gates sin filtros del repositorio.

### D6 — Reproducibilidad entre macOS, Linux y CI

**Chosen:** el contrato de reproducción será la combinación de Node 22, lockfile de npm,
generador exacto, rutas resueltas desde la ubicación del script y serialización normalizada a LF
con newline final. El README documentará que `npm ci` y `npm run api:generate` son el único flujo
oficial, y el workflow usará exactamente `npm run api:check`. El check comparará bytes, no una
representación tolerante que pueda ocultar diferencias.

Esto garantiza que el mismo `backend/openapi.json` y el mismo árbol de dependencias producen el
mismo `openapi.d.ts` en macOS, Linux y CI; las diferencias de entorno no se convierten en diffs
espurios.

Rejected: confiar solo en el lockfile — no controla saltos de línea, directorio actual ni la
versión de Node. Comparar el AST generado — podría ocultar diferencias textuales en un artefacto
versionado y hacer menos visible una deriva real.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Generación | `frontend/scripts/generate-api-types.mjs` *(nuevo)*, `frontend/package.json`, `frontend/package-lock.json` | Un generador oficial fijado; scripts `api:generate` y `api:check`; Node 22 documentado como entorno reproducible. |
| Tipos | `frontend/lib/api/generated/openapi.d.ts` *(nuevo)* | Artefacto TypeScript generado y versionado desde `backend/openapi.json`. |
| Transporte | `frontend/lib/api/client.ts` | Helpers genéricos ligados a `paths`; elimina el `unknown` deliberado sin añadir wrappers por endpoint. |
| API pública | `frontend/lib/api/index.ts` | Reexport de los tipos generados que forman parte de la API pública del frontend. |
| Tests | `frontend/lib/api/client.test.ts` y fixtures afectados | Mantener cobertura del transporte y de `ApiError` usando rutas del contrato y tipos compilables, sin backend real. |
| CI | `.github/workflows/frontend-api-contract.yml` *(nuevo)* | Ejecuta `npm ci` + `npm run api:check` sin servicios ni filtros de paths. |
| Documentación | `frontend/README.md` | Fuente, artefacto, Node 22 y comandos de generación/check. |
| Especificaciones | `sdd/specs/api-contract.md`, `sdd/specs/frontend-foundation.md` | Reflejar el consumo tipado y el gate contrato↔tipos al archivar. |

## Data & interfaces

- **Fuente:** `backend/openapi.json`, solo lectura para el frontend.
- **Artefacto:** `frontend/lib/api/generated/openapi.d.ts`, versionado y regenerable.
- **Tipos públicos:** `paths` y helpers de operación exportados desde `frontend/lib/api`.
- **Transporte:** `ApiClient.request` queda genérico sobre ruta y método; no aparece ningún
  endpoint como clase, repositorio o servicio.
- **Dependencias:** una única herramienta OpenAPI→TypeScript (`openapi-typescript`) como
  `devDependency`, fijada en `package.json` y `package-lock.json`.
- **Configuración/runtime:** ninguna variable de entorno nueva, migración, cambio de backend ni
  llamada de red durante la generación.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| El generador produce un diff distinto por versión o plataforma. | Versión exacta en lockfile, Node 22, script único, rutas absolutas derivadas de su ubicación y normalización LF/newline final; `api:check` compara bytes. |
| El mapeo de respuestas OpenAPI no cubre correctamente una operación. | Helpers de tipos con pruebas de compilación/runtime sobre rutas reales; el typecheck falla si una ruta o método no existe en `paths`. |
| El transporte vuelve a degradar a `unknown` mediante un cast genérico sin relación con la ruta. | La firma liga `Path` y `Method` a `paths`; no se añade una sobrecarga pública de `string → unknown`. |
| El cambio deriva en un SDK por endpoint. | D3 fija explícitamente el límite y el diseño no introduce clases, repositorios, servicios ni funciones de endpoint. |
| El artefacto generado contiene una fuente o ruta local no reproducible. | El script escribe solo tipos derivados del documento, resuelve entradas desde el repositorio y normaliza la salida antes de persistirla. |
| Un cambio en el contrato backend requiere regenerar tipos pero alguien olvida hacerlo. | El workflow independiente `frontend-api-contract` ejecuta `api:check` en PR y push a `main`, sin filtro de paths, y muestra el comando correctivo. |
| La dependencia nueva rompe instalación o build del frontend. | `npm ci`, lint, typecheck, Vitest y build permanecen gates de verificación; el lockfile se actualiza junto con el manifest. |
| Una futura versión del estándar OpenAPI o del generador cambia la salida aunque el contrato siga siendo válido. | Fijar la versión del generador, conservar el lockfile, validar la salida mediante `api:check` y exigir una revisión explícita antes de actualizar el generador. |

## Open questions

Ninguna. La elección del generador, la forma del artefacto, el límite del cliente genérico y el
workflow de deriva quedan decididos aquí; `/sdd:tasks` puede descomponerlos en tareas verificables.
