# Design: CI del frontend

## Contexto

El frontend ya define su contrato de verificación en `frontend/package.json`: `test` ejecuta `vitest run`, `lint` ejecuta `eslint .` y `typecheck` ejecuta `tsc --noEmit`. `frontend/package-lock.json` permite una instalación reproducible y `frontend/devops/Dockerfile` declara Node 22 (`node:22-slim`) tanto para dependencias como para producción; no existen `.nvmrc`, `.node-version` ni `package.json#engines` que establezcan otra versión. `.github/workflows/backend-tests.yml` aporta el patrón de CI general del repositorio, mientras `.github/workflows/multiarch-build-check.yml` y `.github/workflows/deploy-dev.yml` ya cubren construcción de imágenes y `npm run build`, pero no ejecutan la suite, lint ni typecheck del frontend.

## Decisiones

### D1 — Un job con tres verificaciones y resultado consolidado

**Elegido:** crear un único job `frontend-tests` con una sola preparación del entorno y tres pasos de verificación claramente nombrados: `Tests (Vitest)`, `Lint (ESLint)` y `Typecheck (TypeScript)`. Cada uno tendrá un `id`, conservará su `outcome` mediante `continue-on-error: true` y, tras ejecutar los tres, un paso final con `if: always()` resumirá sus resultados y fallará el job si cualquiera terminó en `failure`; los pasos de verificación solo se ejecutarán si la instalación tuvo éxito. Esto evita triplicar `checkout`, setup de Node y `npm ci`, a la vez que GitHub muestra por separado qué verificaciones pasaron o fallaron y permite detectar varios fallos en una sola ejecución.

Rechazada: tres jobs/checks separados — darían paralelismo e independencia total, pero repetirían tres veces la preparación e instalación para una suite pequeña y crearían tres checks cuando el repositorio todavía no puede hacerlos obligatorios.

Rechazada: tres pasos secuenciales con el comportamiento de fallo por defecto — el primer fallo omitiría las verificaciones posteriores y no ofrecería un resultado diferenciado de las tres en esa ejecución.

### D2 — Node 22 como selector exacto de CI

**Elegido:** configurar `actions/setup-node` con `node-version: "22"`. Es el selector exacto derivado de las dos imágenes `node:22-slim` de `frontend/devops/Dockerfile`: conserva la misma política de versión mayor y recibe el último parche disponible de Node 22, igual que una reconstrucción de esas imágenes. No se inventará un parche que el repositorio no declara.

Rechazada: usar la versión preinstalada de `ubuntu-latest` — no está controlada por el repositorio y ya se observó que un cambio de Node podía alterar el entorno de tests.

Rechazada: fijar una versión `22.x.y` solo en el workflow — crearía una segunda autoridad y podría divergir silenciosamente del Dockerfile.

### D3 — `npm ci` único y caché de descargas de npm

**Elegido:** ejecutar una vez `npm ci` con `working-directory: frontend` y activar la caché integrada de `actions/setup-node` mediante `cache: npm` y `cache-dependency-path: frontend/package-lock.json`. La caché almacena el caché de paquetes de npm, no `node_modules`; por tanto cada runner reconstruye dependencias desde el lockfile y `npm ci` sigue fallando cuando `package.json` y `package-lock.json` divergen.

Rechazada: `npm install` — puede actualizar la resolución y no impone la coherencia estricta del lockfile.

Rechazada: cachear `frontend/node_modules` — puede reutilizar árboles parcialmente incompatibles y elimina la garantía de instalación limpia que persigue R2.

Rechazada: ejecutar `npm ci` en cada verificación — no aporta aislamiento útil dentro del mismo runner y triplica trabajo.

### D4 — Disparadores globales y control de concurrencia

**Elegido:** declarar `pull_request: {}`, `push` limitado a `main` y `workflow_dispatch: {}`, sin ninguna clave `paths` ni `paths-ignore`. A nivel de workflow se usará `concurrency.group: frontend-tests-${{ github.ref }}` y `cancel-in-progress: true`, siguiendo el patrón de `.github/workflows/backend-tests.yml`: una actualización de la misma referencia sustituye trabajo obsoleto, mientras referencias distintas no se cancelan entre sí.

Rechazada: filtrar por `frontend/**` — impediría que el check apareciera en cambios de otras áreas y, si llega a ser obligatorio, podría dejar Pull Requests esperando un check que nunca se creó.

Rechazada: una concurrency global sin referencia — un Pull Request podría cancelar la verificación no relacionada de otro.

### D5 — Ejecución acotada y acciones inmutables

**Elegido:** usar `ubuntu-latest`, `timeout-minutes: 15` y `permissions: contents: read` a nivel de workflow. Las únicas actions serán `actions/checkout` pineada a `11d5960a326750d5838078e36cf38b85af677262` (v4, pin ya usado por los workflows endurecidos del repositorio) y `actions/setup-node` pineada a `49933ea5288caeca8642d1e84afbd3f7d6820020` (v4, SHA verificado contra el tag oficial al redactar este diseño).

Rechazada: referencias mutables como `@v4` — permiten que código distinto se ejecute sin un cambio revisable en el repositorio.

Rechazada: un timeout de 20 minutos por simetría literal con backend — el frontend no levanta servicios ni ejecuta migraciones; 15 minutos deja margen amplio sin prolongar runners bloqueados.

Rechazada: permisos implícitos — su alcance depende de defaults externos y es más amplio o menos auditable que declarar `contents: read`.

### D6 — Comandos del contrato real del frontend

**Elegido:** ejecutar desde `frontend/` exactamente los scripts versionados: `npm test`, `npm run lint` y `npm run typecheck`. Los nombres de paso y sus identificadores serán estables (`tests`, `lint`, `typecheck`) para que el resumen final y la interfaz de GitHub identifiquen cada fallo sin analizar un log combinado.

Rechazada: invocar directamente `vitest`, `eslint` o `tsc` con `npx` — duplicaría fuera de `package.json` opciones y convenciones que pertenecen al frontend.

Rechazada: crear un script agregado nuevo — modificaría `frontend/package.json` sin necesidad y ocultaría qué verificación concreta falló.

### D7 — CI de calidad separada de los builds existentes

**Elegido:** añadir `.github/workflows/frontend-tests.yml` como workflow independiente, sin `npm run build` y sin modificar `.github/workflows/multiarch-build-check.yml` ni `.github/workflows/deploy-dev.yml`. `frontend-tests` responde si tests, lint y tipos son correctos; los otros workflows conservan la responsabilidad de demostrar que las imágenes construyen para sus plataformas y de desplegarlas.

Rechazada: añadir las tres verificaciones al workflow multiarquitectura — está filtrado por paths, su coste y objetivo son distintos y acoplaría calidad del código a emulación/build de contenedores.

Rechazada: añadirlas a `deploy-dev.yml` — descubriría fallos demasiado tarde, solo tras cambios que disparan despliegue, y mezclaría validación con publicación y operación.

### D8 — Validación sin ampliar el alcance a producto

**Elegido:** separar la validación local de Run del gate remoto de Pull Request. Run se cierra comprobando la sintaxis YAML, la estructura compatible con GitHub Actions mediante revisión estática, los triggers, permissions, pins, concurrency y timeout, además de ejecutar `npm ci`, `npm test`, `npm run lint`, `npm run typecheck` con Node 22 y `git diff --check`. Si una verificación local revela un fallo preexistente, se registrará como bloqueo/hallazgo separado: este cambio no modificará tests, configuración de lint/typecheck ni código de producto para poner el check en verde.

La primera ejecución de `pull_request` es un gate remoto obligatorio de la fase PR, posterior al cierre local de `/sdd:run` y previo al merge: GitHub Actions debe aceptar el workflow, crear el check `frontend-tests`, ejecutarlo en el Pull Request y finalizar correctamente. Esta evidencia no se presume ni se marca como ejecutada durante Run.

Rechazada: corregir dentro de este cambio cualquier fallo que aparezca — mezclaría la incorporación del gate con cambios funcionales no contemplados y dificultaría distinguir un problema previo de un defecto del workflow.

Rechazada: considerar suficiente una ejecución local sobre la versión de Node del host — repetiría la falta de reproducibilidad que este cambio corrige.

## Cambios por área

| Área | Ficheros | Cambio |
|---|---|---|
| GitHub Actions | `.github/workflows/frontend-tests.yml` *(nuevo)* | Workflow con los tres disparadores, una única instalación reproducible, tres verificaciones diferenciadas, resultado consolidado, concurrencia, timeout y permisos mínimos. |

No se modificarán `frontend/package.json`, `frontend/package-lock.json`, `frontend/devops/Dockerfile`, los tests, el código de producto ni los workflows de build/deploy existentes.

## Datos e interfaces

No hay cambios de esquema, API, eventos, variables de entorno ni dependencias de aplicación. La interfaz operativa nueva es el workflow/check `frontend-tests` en GitHub Actions. Mientras el repositorio no disponga de protección de rama compatible, se ejecutará y reportará, pero no será obligatorio para fusionar.

## Cobertura de requisitos

| Requisito | Decisiones que lo cubren |
|---|---|
| R1 — PR, push a `main`, ejecución manual, concurrencia y ausencia de filtros | D4 |
| R2 — Node oficial e instalación reproducible desde lockfile | D2, D3 |
| R3 — tests, lint, typecheck y fallos diferenciados | D1, D6 |
| R4 — permisos, timeout, pins y check informativo | D5, D7 |

## Riesgos y mitigaciones

- **Los tags base `node:22-slim` y el selector `node-version: "22"` avanzan de parche.** Mitigación: ambos expresan la misma autoridad de versión mayor; una futura decisión de fijar parche deberá actualizar primero la fuente oficial del repositorio y después CI.
- **`continue-on-error` podría ocultar un fallo si no existe consolidación.** Mitigación: el paso final se ejecuta siempre, inspecciona explícitamente los tres `outcome` y devuelve error si cualquiera falla; la revisión verificará también este comportamiento.
- **Una instalación fallida no permite ejecutar verificaciones.** Mitigación: los tres pasos quedan visibles como omitidos y el consolidado falla señalando la instalación; no se generan fallos secundarios sin dependencias.
- **La caché podría confundirse con reutilización de dependencias instaladas.** Mitigación: documentar en el workflow que `setup-node` cachea descargas de npm y mantener `npm ci` en toda ejecución; nunca cachear `node_modules`.
- **La validación local no reproduce completamente el parser de GitHub Actions.** Mitigación: cerrar Run solo con evidencia local y exigir la ejecución satisfactoria del evento `pull_request` como gate remoto autoritativo antes del merge.

## Preguntas abiertas

Ninguna. Las decisiones necesarias quedan resueltas por la Proposal, las fuentes versionadas y los patrones existentes del repositorio.
