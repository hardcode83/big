# Design: app-version-provenance

## Context

`app-version-visibility` ya genera una identidad pública limitada (`appVersion` y
`buildCommitShort`) en `frontend/lib/config/public.ts`; `RootLayout` la serializa
en todas las superficies y el `VersionBadge` la pinta en los shells. Esa ruta no
puede transportar procedencia privada. La sesión del frontend vive únicamente en
memoria (`frontend/lib/auth/session-store.ts`) y `AuthGuard` es una protección de
UX client-side, no una frontera de seguridad. El backend ya centraliza JWT, RBAC y
la regla de que cada endpoint declara `require(Permission...)`.

La frontera elegida será, por tanto, un endpoint backend protegido. El CD
producirá los valores de procedencia una vez; el deploy los entregará solo al
servicio backend mediante configuración privada; el backend verificará la
identidad antes de responder; y el panel autenticado los solicitará después del
login. No se consultará GitHub en runtime ni se incluirá esta información en el
build público del frontend.

## Decisions

### D1 — Frontera autenticada para la procedencia

**Chosen:** endpoint protegido `GET /api/v1/provenance`, servido por un módulo
backend de procedencia y protegido por `require(Permission.READ_BUILD_PROVENANCE)`.
La dependencia de autorización se ejecuta antes del handler y el proxy existente
(`frontend/app/api/[...path]/route.ts`) solo transporta la petición; no decide
autorización ni ve los metadatos.

Rejected: Route Handler/BFF como dueño de la autorización — la sesión actual no
usa cookies ni un servidor de sesión; hacer que el BFF traduzca o replique el JWT
añadiría una frontera sin autoridad propia y duplicaría el contrato del backend.

Rejected: hornear la procedencia privada en el frontend — `NEXT_PUBLIC_*`, el
RSC payload y los bundles son superficies públicas aunque exista `AuthGuard`.

### D2 — Transporte de la identidad privada desde CD hasta backend

**Chosen:** el job `provenance` de `.github/workflows/deploy-dev.yml` produce
`repository_url`, `pull_request_number`, `commit_sha` y `actions_run_id` como
outputs. El paso de deploy los escribe como variables `APP_PROVENANCE_*` en el
`.env` privado de la VM; `docker-compose.deploy.yml` las inyecta únicamente en
`backend`. `frontend`, `cloudflared`, `worker`, `beat` y `migrate` no reciben esas
variables.

Así la procedencia sigue naciendo en CD, pero no pasa por la imagen ni por la
configuración pública del frontend. Son identificadores y una URL, no secretos,
tokens ni credenciales; no se añade ninguna autorización de GitHub ni ninguna
consulta externa en runtime.

El mismo output `version` que alimenta `NEXT_PUBLIC_APP_VERSION` se escribe como
`APP_VERSION` únicamente en el `.env` privado del backend. El endpoint devuelve
esa identidad exacta, sin crear una segunda versión ni incluir la URL privada en
labels, build args o entorno de la imagen frontend.

`APP_PROVENANCE_REPOSITORY_URL` se deriva determinísticamente en CD como
`GITHUB_SERVER_URL/GITHUB_REPOSITORY` y después se valida antes de publicarse como
output. El backend vuelve a validar el valor recibido; ninguna de las dos
validaciones consulta GitHub en runtime.

Rejected: guardar la procedencia en base de datos — duplicaría una identidad
inmutable del deploy, exigiría migración y dejaría estado stale separado de la
imagen/ejecución que la produjo.

Rejected: pasarla como `NEXT_PUBLIC_*` o build arg del frontend — la compilación
la haría accesible en HTML, RSC o JavaScript anónimo.

### D3 — Contrato y validación de configuración en backend

**Chosen:** añadir campos opcionales y fail-closed a `backend/app/core/config.py`:
`app_provenance_repository_url`, `app_provenance_pull_request_number`,
`app_provenance_commit_sha` y `app_provenance_actions_run_id`. Los cuatro campos
forman una unidad atómica de provenance: un servicio de aplicación solo construye
el bloque privado utilizable si todos están presentes y tienen forma válida. Si
cualquiera falta o falla, el backend considera el bloque privado
`unavailable/unknown`, no devuelve ningún valor privado parcial y deja que el
frontend muestre la procedencia desconocida sin construir enlaces. `app_version`
se entrega desde `APP_VERSION`, que es la misma identidad pública producida por
`build-identity-contract`; solo en desarrollo local sin ese valor se usa la
versión base del paquete como fallback.

El esquema OpenAPI será explícito, con enteros para PR/run ID, SHA completo de 40
hexadecimales y URL HTTPS de GitHub. El endpoint responderá con
`Cache-Control: private, no-store` para impedir almacenamiento por intermediarios.

Rejected: devolver texto sin validar desde `Settings` — permitiría convertir una
variable de deploy malformada en un enlace o una salida no prevista.

### D4 — Permiso y roles

**Chosen:** añadir `READ_BUILD_PROVENANCE` al catálogo de permisos y concederlo
solo a `TENANT_OWNER` y `PROPERTY_MANAGER`. La ruta queda denegada por defecto a
limpiadoras y técnicos porque los enlaces al repositorio privado y a Actions son
información de operación/mantenimiento, no datos necesarios para ejecutar sus
tareas. Los tests de autorización cubrirán `401`, `403` y acceso permitido.

Rejected: permitirlo a cualquier usuario autenticado — autenticación sin
autorización no cumple el principio de mínimo privilegio de `steering/security.md`.

### D5 — Panel frontend y momento de lectura

**Chosen:** crear `frontend/features/provenance/` como isla client-side, visible
solo en `WorkspaceShell`, accesible desde el footer junto al `VersionBadge`. El
componente no recibe procedencia por props del layout: al abrirse, usa el cliente
HTTP existente con el bearer efímero y solicita `/api/v1/provenance`. Los datos
solo viven en el estado de la isla/query en memoria; el cliente no usa
`localStorage`, `sessionStorage`, cookies ni `NEXT_PUBLIC_*` para ellos.

El panel construye los tres enlaces a partir de la respuesta autenticada y
muestra estado desconocido si algún campo no está disponible. `/login`, el portal
`/guest/[token]`, los shells de campo y cualquier HTML server-rendered quedan sin
el panel y sin la petición. El enlace al panel no contiene valores privados antes
de la petición.

Rejected: hacer el panel parte del `RootLayout` o `PublicRuntimeConfig` — ambos
cruzan al navegador en superficies anónimas.

### D6 — Extracción del número de Pull Request

**Chosen:** crear `.github/scripts/extract-pr.sh`, invocable con un subject o con
un commit, que acepte únicamente `Merge pull request #N ...` y el sufijo
`título (#N)`. Un subject no reconocido produce salida vacía y estado válido de
procedencia desconocida; nunca se toma el primer número encontrado. El script
tendrá `--self-test` y cubrirá números de issue, formatos ambiguos, espacios y
subjects sin PR.

El job `provenance` ejecuta el extractor después de checkout y publica el valor
como output. `actions_run_id` procede de `GITHUB_RUN_ID`, `commit_sha` de
`GITHUB_SHA` y `repository_url` de la identidad del workflow; ninguno requiere
una llamada a la API de GitHub.

Rejected: consultar la API de GitHub durante el deploy — introduciría un token,
una dependencia de red y un camino de fallo runtime que el alcance excluye.

### D7 — Gate de paridad de versiones

**Chosen:** crear `scripts/check-version-parity.py` con biblioteca estándar
(`tomllib` y `json`) y el target de host `make check-version-parity`. Comparará
`VERSION`, `backend/pyproject.toml` y `frontend/package.json`, nombrará cada
desviación y devolverá código distinto de cero ante ausencia, vacío o diferencia.
El workflow `.github/workflows/frontend-tests.yml` ejecutará el target como señal
separada antes de las verificaciones frontend.

Rejected: hacer que el CD sea el único gate — el CD comprueba la identidad del
build, pero no debe ser el único lugar que detecte deriva en los manifiestos del
monorepo.

### D8 — Congruencia productor/consumidor

**Chosen:** mantener el contrato de inputs/outputs del job en un test explícito
del workflow y extender el test frontend de contrato para afirmar que ningún
campo privado entra en `PublicRuntimeConfig`, `RootLayout`, `NEXT_PUBLIC_*`,
assets ni bundles públicos. La prueba del extractor y el gate de paridad quedan
separados para que una regresión de CD tenga una señal diagnosticable.

Rejected: confiar solo en `npm test` sin una señal nombrada — una suite verde no
demuestra que el productor del workflow y el consumidor público siguen
compartiendo el límite de divulgación.

## Changes by area

| Área | Archivos | Cambio |
|---|---|---|
| Backend — configuración y contrato | `backend/app/core/config.py`, `backend/app/provenance/` | Configuración privada validada, servicio de lectura fail-closed, schemas y router `GET /api/v1/provenance`. Sin tabla ni migración. |
| Backend — integración | `backend/app/auth/domain/policy.py`, `backend/app/main.py`, `backend/openapi.json` | Nuevo permiso, registro del router y artefacto OpenAPI regenerado. Tests de permiso y contrato en `backend/tests/`. |
| Deploy | `.github/workflows/deploy-dev.yml`, `docker-compose.deploy.yml` | Outputs de provenance, extracción de PR y variables privadas solo para `backend`. Sin cambios a `NEXT_PUBLIC_*`. |
| Extractor CD | `.github/scripts/extract-pr.sh` | Parser fail-closed y self-test de subjects de merge. |
| Frontend autenticado | `frontend/features/provenance/`, `frontend/features/shell/components/shell-footer.tsx`, `frontend/features/shell/components/workspace-shell.tsx`, `frontend/locales/{es,en}/` | Panel client-side bajo interacción autenticada; el footer público y el `VersionBadge` no reciben metadatos privados. |
| Cliente API | `frontend/lib/api/generated/openapi.d.ts`, `frontend/lib/api/` | Tipo y llamada autenticada al nuevo endpoint mediante el transporte existente; sin leer `process.env` fuera de `lib/config`. |
| CI de frontend | `.github/workflows/frontend-tests.yml`, `frontend/package.json` | Gate nombrado de congruencia y señal separada del test de contrato. |
| Paridad | `scripts/check-version-parity.py`, `Makefile` | Comparación host-side de las tres declaraciones de versión. |
| Especificación | `sdd/specs/app-version-provenance.md` al archivar | Contrato permanente de procedencia privada y gate de paridad; los cambios vivos a specs se harán en `/sdd:archive`. |

## Data & interfaces

No hay cambios de esquema de base de datos ni eventos. La configuración privada de
deploy alimenta el backend con estas variables, no públicas:

```text
APP_PROVENANCE_REPOSITORY_URL
APP_PROVENANCE_PULL_REQUEST_NUMBER
APP_PROVENANCE_COMMIT_SHA
APP_PROVENANCE_ACTIONS_RUN_ID
```

El endpoint protegido devuelve un contrato equivalente a:

```text
GET /api/v1/provenance
Authorization: Bearer <access-token>

{
  "app_version": "0.1.0+2026-08-09.a2f3c1d",
  "provenance": {
    "repository_url": "https://github.com/autohostai-labs/AutoHostAI",
    "pull_request_number": 42,
    "commit_sha": "<40 hex characters>",
    "actions_run_id": 123456789
  }
}
```

Los cuatro campos privados forman una unidad atómica. Solo cuando
`repository_url`, `pull_request_number`, `commit_sha` y `actions_run_id` están
presentes y son válidos el backend devuelve un bloque `provenance` utilizable.
Si cualquiera falta o es inválido, el bloque privado completo es
`unavailable/unknown`: no se devuelve ningún valor privado parcial y el frontend
no construye ningún enlace. `app_version` puede seguir devolviéndose y
mostrándose independientemente, porque pertenece al contrato público existente.

`repository_url` se deriva determinísticamente de
`GITHUB_SERVER_URL/GITHUB_REPOSITORY` en el job de CD y se valida antes de
publicarse como output; el backend valida de nuevo la configuración recibida.
Ninguna validación consulta GitHub en runtime. La respuesta autenticada no se
serializa en props del root layout ni en ningún snapshot público; cuando el
bloque está disponible, el frontend genera los enlaces a PR, commit y run a
partir del bloque completo ya entregado.

## Risks & mitigations

- **Divulgación por una nueva ruta pública:** la dependencia `require(...)`, el
  test estructural de permisos y pruebas anónimas de `GET /api/v1/provenance`
  deben demostrar rechazo antes del handler.
- **Divulgación accidental en el frontend:** mantener la procedencia fuera de
  `NEXT_PUBLIC_*`, `PublicRuntimeConfig`, RootLayout y props; probar HTML de
  `/login` y `/guest/[token]`, y revisar el bundle de producción buscando el
  repository URL, SHA, PR y run ID.
- **Intermediario cacheando respuesta autenticada:** `Cache-Control: private,
  no-store`, cliente sin persistencia y no usar el endpoint desde Server
  Components.
- **Deploy incompleto o metadata ausente:** configuración opcional fail-closed;
  la unidad atómica completa se marca `unavailable/unknown`, no se devuelven
  metadatos privados parciales, el panel muestra desconocido y no fabrica
  enlaces. `app_version` continúa independiente.
- **Derivación o validación inconsistente de la URL privada:** CD deriva
  `repository_url` solo de `GITHUB_SERVER_URL/GITHUB_REPOSITORY`, lo valida antes
  del output y el backend vuelve a validarlo; ninguna ruta consulta GitHub en
  runtime.
- **Confundir issue con PR:** parser con patrones positivos únicamente,
  self-test y regresión versionada.
- **Deriva entre productores y consumidores:** outputs tipados del job, test de
  contrato explícito y regeneración de OpenAPI/frontend types.
- **Paridad falsa por parsing frágil:** script host-side con `tomllib`/`json`,
  errores por archivo y tests con valores ausentes y divergentes.
- **Filtración por el contenedor frontend:** `docker-compose.deploy.yml` no
  declara las variables `APP_PROVENANCE_*` en `frontend`; la revisión debe
  verificar que no se añadan como entorno o build arg.

## Open questions

Ninguna decisión de implementación queda pendiente para `/sdd:tasks`: la
frontera backend protegida, el permiso owner/manager, el transporte privado por
configuración de deploy y el panel client-side son decisiones cerradas en este
diseño. Los nombres exactos de componentes visuales y la redacción final de
traducciones quedan como detalle de implementación, no como decisiones de
seguridad o arquitectura.
