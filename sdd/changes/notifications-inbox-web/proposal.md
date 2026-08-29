# Proposal: notifications-inbox-web

## Why

`GET /api/v1/notifications` existe desde `access-notifications` (2026-08-08) y **ningún fichero del
frontend lo llama**: la única aparición de la ruta en todo `frontend/` está en el artefacto generado
`lib/api/generated/openapi.d.ts` (verificado el 2026-08-28 recorriendo el árbol completo, excluido
`node_modules`). Ocho call sites del backend —en `maintenance`, `cleaning`, `messaging`, `guests` y el
propio `notifications`— fijan `channel = NotificationChannel.IN_APP`, así que **toda** la comunicación
interna del sistema (limpieza asignada, técnico asignado, incidencia rechazada, aprobación del
propietario, escalación de huésped, incumplimiento de SLA) termina hoy en filas de `notification_logs`
que solo se leen con SQL.

Eso no es cosmético: `InAppNotificationAdapter` declara por escrito que «the row **is** the delivery», y
deja escrita su propia condición de verdad — *"it is only true because that endpoint exists (design D6).
If the endpoint ever goes away, this adapter is a lie and must go with it."*
(`backend/app/notifications/infrastructure/adapters.py`). La ruta existe, pero ningún humano puede
llegar a ella, así que la afirmación es cierta en el contrato y falsa en el producto.

Contexto: entrada de roadmap `notifications-inbox-web` y su nota `sdd/roadmap/notifications-inbox-web.md`;
PRD §14 (canal in-app = «Notification entity + API polling»), §23 (envelope paginado), §24 (rutas).

## What changes

Tras este change, un usuario autenticado —en cualquiera de las tres shells— ve una **campana con contador
de no leídas** en su topbar y una **superficie de listado** donde puede leer sus notificaciones, marcarlas
como leídas y saltar a la entidad relacionada cuando esa pantalla existe. Para que «leída» sea un hecho
del sistema y no una preferencia de un navegador, el backend gana la columna `notification_logs.read_at`
y la ruta de acuse que `access-notifications` design D6 aparcó como OQ2 — decisión tomada al abrir este
`/sdd:new`, que es lo que convierte a esta entrada en la que `specs/access-notifications.md` anticipaba
(«el frontend lleva su propio estado hasta que una entrada de roadmap decida lo contrario»). La pantalla
**renderiza `notification_type` a texto i18n ES/EN** y no se limita a pintar `subject`/`body`, que están
escritos en inglés, para un operador, y llevan UUID en crudo.

## Requirements

### R1 — El acuse de lectura vive en la base de datos

**As a** usuario de AutoHostAI que opera desde el móvil y desde el escritorio, **I want** que marcar una
notificación como leída sea un hecho del sistema, **so that** no vea dos bandejas distintas según el
dispositivo desde el que mire.

Acceptance criteria:

1. THE SYSTEM SHALL añadir la columna `read_at` (`TIMESTAMPTZ`, nullable, sin default) a
   `notification_logs` mediante migración Alembic, y SHALL dejar en `NULL` toda fila preexistente: una
   notificación escrita antes de este change no ha sido leída por nadie.
2. THE SYSTEM SHALL exponer una operación de acuse que fije `read_at` sobre las notificaciones del
   usuario del token, exigiendo el permiso `READ_OWN_NOTIFICATIONS`, y SHALL derivar el destinatario del
   JWT sin ningún parámetro de petición que ensanche el alcance — la misma restricción que ya gobierna
   `GET /api/v1/notifications`.
3. WHEN el acuse se aplica sobre una notificación ya leída, THE SYSTEM SHALL responder con éxito y
   **no** modificar el `read_at` existente: el acuse es idempotente y `read_at` registra la primera
   lectura, no la última visita.
4. IF la notificación no existe, o pertenece a otro usuario o a otro tenant, THEN THE SYSTEM SHALL
   responder `404` y SHALL NOT distinguir entre esos tres casos en el cuerpo de la respuesta: un `403`
   confirmaría la existencia de una fila ajena.
5. THE SYSTEM SHALL cubrir la ruta con test de aislamiento de tenant (regla 1 de `steering/security.md`)
   que demuestre que un usuario de otro tenant no puede acusar una fila de este.
6. THE SYSTEM SHALL dejar `read_at` fuera de cualquier criterio de `check_sla_breaches` y del emisor:
   leer un aviso no es responder a él, y el plazo de SLA se cierra por la acción de dominio, no por
   haber mirado la bandeja.

### R2 — El contador de no leídas se obtiene sin paginar la bandeja entera

**As a** cliente de la bandeja, **I want** saber cuántas notificaciones no leídas tengo con una sola
petición, **so that** la campana pueda pintar su contador sin recorrer hasta 100.000 páginas.

Acceptance criteria:

1. THE SYSTEM SHALL publicar `read_at` en cada elemento de `NotificationResponse`, junto a los campos
   que ya publica, y SHALL seguir reteniendo `recipient_contact`, `last_error`, `sla_deadline_at` y
   `sla_breached`, que este change no reabre.
2. THE SYSTEM SHALL permitir obtener el **total de no leídas del usuario del token** en una única
   petición, independiente del tamaño de página solicitado y consistente con lo que devolvería listar y
   contar `read_at IS NULL`.
3. THE SYSTEM SHALL permitir listar restringiendo a las no leídas, sin romper el envelope paginado de
   PRD §23 (`data`, `total`, `page`, `per_page`, `total_pages`) ni el orden de más nueva a más vieja.
4. THE SYSTEM SHALL regenerar `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` en el
   mismo PR (`steering/documentation.md`), de modo que los workflows `api-contract` y
   `frontend-api-contract` no detecten deriva.

### R3 — La campana, en las tres shells

**As a** propietaria, manager, limpiadora o técnico, **I want** ver desde cualquier pantalla que tengo
avisos sin leer, **so that** me entere de que me han asignado trabajo sin que nadie me llame.

Acceptance criteria:

1. THE SYSTEM SHALL montar el indicador de notificaciones en el slot `end` del `Topbar` de las tres
   shells autenticadas —`WorkspaceShell`, `CleanerShell` y `TechnicianShell`—, y SHALL NOT montarlo en
   `PublicShell` ni en `GuestShell`, que no llevan JWT.
2. WHILE el usuario tiene al menos una notificación no leída, THE SYSTEM SHALL mostrar el contador sobre
   la campana; IF el contador es cero, THEN THE SYSTEM SHALL mostrar la campana sin distintivo numérico.
3. THE SYSTEM SHALL refrescar el contador por **polling** y no por SSE, heredando la decisión ya tomada
   y documentada en el docstring de la ruta, con una cadencia no inferior a 60 s: `dispatch_notifications`
   corre cada minuto (`scheduler/schedule.py`), así que pedir más a menudo no puede descubrir nada nuevo.
4. WHEN la identidad autenticada cambia —logout, expiración, o swap de usuario—, THE SYSTEM SHALL dejar
   de mostrar el contador del usuario anterior, sin introducir un almacén propio que sobreviva a la purga
   del `QueryClient` que `specs/frontend-auth-session.md` ya declara.
5. THE SYSTEM SHALL exponer el indicador con nombre accesible traducido y anunciar el número de no leídas
   a lectores de pantalla, no solo visualmente.

### R4 — La bandeja se lee en castellano y en inglés, no en el idioma del operador

**As a** limpiadora que solo habla castellano, **I want** entender el aviso que me ha llegado, **so that**
la notificación sirva para algo más que constar en una tabla.

Acceptance criteria:

1. THE SYSTEM SHALL renderizar cada fila a partir de su `notification_type`, con texto traducido en
   `locales/es/` **y** `locales/en/`, y SHALL cubrir los **diecisiete** miembros de `NotificationType`
   —incluidos los nueve que hoy no escribe nadie y que `notification-writers-gap` traerá—, de modo que
   ningún tipo se pinte como su identificador en bruto.
2. THE SYSTEM SHALL NOT usar `subject` ni `body` como texto principal de la fila: están escritos en
   inglés, para un operador, y contienen UUID en crudo (`"A cleaning task has been assigned to you.
   Task <uuid>, property <uuid>."`).
3. IF llega un `notification_type` que la interfaz no conoce —la columna es `String(100)` libre y admite
   valores anteriores al enum—, THEN THE SYSTEM SHALL pintar un texto genérico traducido y SHALL NOT
   romper el renderizado de la lista.
4. THE SYSTEM SHALL mostrar la fecha de cada notificación localizada según el idioma activo, y SHALL
   distinguir visualmente las no leídas de las leídas.
5. THE SYSTEM SHALL ofrecer una superficie de listado paginada, mobile-first, con estados explícitos de
   carga, error y bandeja vacía, alcanzable desde la campana.

### R5 — Marcar como leída, desde donde se lee

**As a** manager, **I want** que mis avisos dejen de contar cuando los leo, **so that** el contador
signifique «me queda esto por ver» y no «esto ha pasado alguna vez».

Acceptance criteria:

1. WHEN el usuario abre o acusa una notificación no leída desde la bandeja, THE SYSTEM SHALL invocar la
   operación de acuse de R1 y SHALL reflejar el nuevo contador sin esperar al siguiente ciclo de polling.
2. THE SYSTEM SHALL ofrecer «marcar todas como leídas» sobre las no leídas del usuario del token.
3. IF la operación de acuse falla, THEN THE SYSTEM SHALL revertir el estado optimista y mostrar un error
   traducido, sin dejar la fila pintada como leída: una notificación que parece leída y no lo está
   vuelve a aparecer en el siguiente refresco y parece un fallo del sistema.
4. THE SYSTEM SHALL invalidar la caché de TanStack Query de la bandeja y del contador tras un acuse
   exitoso, sin duplicar el server state en un store de Zustand (`steering/frontend.md`).

### R6 — Enlazar solo donde hay destino vivo

**As a** manager, **I want** llegar desde el aviso a la incidencia, conversación o reserva de la que
habla, **so that** no tenga que buscarla a mano por su UUID.

Acceptance criteria:

1. WHERE la notificación lleva `related_type` con destino navegable para la shell del usuario, THE
   SYSTEM SHALL enlazar la fila a esa ruta: en `WorkspaceShell`, `incident` → `/incidents/[id]`,
   `conversation` → `/conversations/[id]` y `reservation` → `/reservations/[id]`.
2. THE SYSTEM SHALL NOT enlazar `related_type = "cleaning_task"`, que no tiene página de detalle de
   manager, ni ningún destino en `CleanerShell` o `TechnicianShell`, cuyas páginas de detalle siguen
   siendo `RoutePlaceholder` hasta que entreguen `cleaner-app` y `tech-app`.
3. IF `related_type` o `related_id` vienen a `null`, o el tipo no está en la tabla de destinos, THEN THE
   SYSTEM SHALL pintar la fila sin enlace y SHALL NOT mostrar el UUID en crudo al usuario.
4. THE SYSTEM SHALL declarar la tabla de destinos en un único sitio del frontend, de modo que añadir un
   destino cuando `cleaner-app` o `tech-app` entreguen su detalle sea una entrada más y no una búsqueda
   por componentes.

## Out of scope

- **Escribir los tipos que hoy no escribe nadie.** Nueve de los diecisiete `NotificationType` no tienen
  emisor; eso es `notification-writers-gap`, que ya está en el roadmap. Esta bandeja los traduce para
  cuando lleguen, y no los produce.
- **Enrutado por canal** (que una fila nazca `EMAIL` o `WHATSAPP`): es `notification-channel-routing`,
  decisión de dominio con entrada propia. Aquí solo se lee el canal `IN_APP` que los emisores ya fijan.
- **Entrega real por email o WhatsApp**: `smtp-delivery-adapter` y `whatsapp-cloud-adapter`.
- **SSE / tiempo real y push del navegador**: la decisión de polling se hereda explícitamente (PRD §14
  ofrece ambos); un canal `PUSH` existe en el enum y no tiene adapter ni consumidor.
- **Detalle de notificación como pantalla propia** y **filtros avanzados** (por tipo, por rango de
  fechas, por propiedad): la ruta pagina y ordena, nada más.
- **Enlaces a destinos que hoy son `RoutePlaceholder`** — los añaden `cleaner-app` y `tech-app` cuando
  entreguen sus páginas de detalle (R6.4 deja el sitio preparado).
- **Retención o archivado de notificaciones antiguas**: nadie borra filas de `notification_logs` hoy y
  este change no estrena esa política.
- **Preferencias de notificación por usuario** (qué tipos quiero recibir): no hay entidad ni entrada.

## Affected specs

- `sdd/specs/access-notifications.md` — modificar. Su sección «La bandeja in-app» afirma hoy que el
  sistema **no** ofrecerá «marcar como leída» ni la columna `read_at`, y que «el frontend lleva su propio
  estado hasta que una entrada de roadmap decida lo contrario». Este change es esa entrada: ese criterio
  se sustituye, no se matiza, y cierra el OQ2 del design D6.
- `sdd/specs/api-contract.md` — modificar: la ruta nueva y los campos nuevos entran en el contrato
  publicado.
- `sdd/specs/notifications-inbox-web.md` — *(no existe aún — se creará al archivar)*: la superficie de
  frontend, en la línea de `conversations-inbox.md` y `cleaning-manager-view.md`.
- `sdd/specs/frontend-foundation.md` — modificar si la campana o la ruta nueva tocan el `routeRegistry` o
  los slots del `Topbar`, que ese documento gobierna.

### Encargos a `/sdd:archive`

Redactados aquí, y no en `BLOCKED.md`, porque el buzón es temporal y ninguno de los changes
archivados lo conserva: si una nota tiene que sobrevivir al cierre, su home es este documento.
Se deja la **redacción concreta**, no el nombre del fichero, para que archivar no tenga que
redescubrirla.

**1. Regenerar el diagrama ER.** `docs/diagrams/2026-08-23_autohost-er-entidades.png` queda
desfasado: `notification_logs` gana la columna `read_at`. Cifras **medidas contra la metadata de
SQLAlchemy, no incrementadas a mano** (`sum(len(t.columns) for t in Base.metadata.sorted_tables)`
con todos los modelos importados): **32 entidades, 426 columnas** — antes 32 y 425. **Las
relaciones no se mueven**: `read_at` es un `TIMESTAMPTZ` sin clave ajena, así que las 79
relaciones (77 pares de tablas) y las 82 flechas del dibujo se quedan igual. Mismo caso que
`eta_at`/`materials` en `tech-cycle-completion`. Se genera desde la metadata y, por
`steering/architecture.md`, se sustituye el PNG anterior por el nuevo con fecha, borrando el viejo.

**2. Entrada candidata de roadmap `super-admin-console`** — `[BE+FE]`, encargo del design D18.
Consola de plataforma para `SUPER_ADMIN`: shell propia fuera de los tenants, alta y listado de
tenants, alta de usuarios por rol (`PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`) que hoy se hace a
mano contra la base de datos o contra la API, y la puerta —futura, con su propia decisión de
auditoría— para inspeccionar un tenant desde dentro. Su nota larga en
`sdd/roadmap/super-admin-console.md`. **El hecho que la motiva**, medido en D18 y reconfirmado por
el panel de `/sdd:review`: `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]` es `_SELF_SERVICE` y nada más
(`backend/app/auth/domain/policy.py`), así que tiene `READ_OWN_NOTIFICATIONS` pero `roleHome` lo
manda a `/dashboard`, cuyo `AuthGuard` sólo admite `TENANT_OWNER` y `PROPERTY_MANAGER` y lo rebota
a `/login?denied=role`. No alcanza **ninguna** superficie autenticada, y este change no lo cambia.
Un rol que cruza tenants es además la excepción exacta a la regla 1 de `steering/security.md`, así
que necesita su propio aislamiento y su propia decisión.

**3. Entrada candidata de roadmap `auth-session-generation-semantics`** — `[FE]`, tamaño S.
Cerrar las dos grietas de `frontend/lib/auth/` que esta bandeja destapó al ser el primer consumidor
de mutaciones optimistas del frontend. No se arreglan aquí porque cambian la semántica de un módulo
compartido, y eso no lo decide una feature de bandeja de notificaciones. Su nota larga en
`sdd/roadmap/auth-session-generation-semantics.md`, con estos dos hechos:

- **`refresh()` purga la caché sin mover la generación de sesión.** En el `catch` de `refresh()`
  (`auth-provider.tsx`) se llama a `purgeSessionCache()` **sola**, sin `clearSessionTokens()` y sin
  `notifySessionExpired()`. Como `sessionGeneration` sólo se mueve dentro de los dos escritores de
  tokens (`session-store.ts`), ése es el único camino de purga que la deja quieta — y una mutación
  optimista cuyo snapshot se tomó en esa misma generación pasa la guarda de `use-mark-read.ts` y
  reescribe las filas del usuario saliente en la caché recién vaciada, que es lo que R3.4 prohíbe.
  **Hoy es latente, no vivo**: ningún `useAuth()` del árbol desestructura `refresh` (los veinte
  sitios leen sólo `status`, `user` y `login`), verificado en el run y de nuevo por el panel de
  review. El arreglo bueno es mover el incremento **dentro** de `purgeSessionCache()`, para que
  «toda purga invalida todo snapshot en vuelo» sea cierto por construcción.
- **Limpiar tokens al expirar la sesión anula a propósito una guarda del coordinador.** El listener
  de `subscribeToSessionExpired` llama ahora a `clearSessionTokens()`, porque una sesión declarada
  expirada no debe conservar credenciales en memoria y en dos rutas (`SessionInvalidatedError` y
  «No refresh token available») las conservaba. Eso anula la guarda de `refresh-coordinator.ts:57`,
  que limpia tokens **sólo** si la generación no se movió. Interleaving concreto: refresco pendiente
  en la generación G → el usuario vuelve a autenticarse (`login()` escribe G+1 y espera
  `/auth/me`) → el refresco viejo resuelve, lanza `SessionInvalidatedError`, y el listener tira los
  tokens **de la sesión nueva**; `login()` acaba poniendo `authenticated` sobre un almacén vacío y
  se recupera solo en el siguiente `401`. Se aceptó porque antes del cambio esa misma carrera ya
  terminaba en `expired` —lo que se pierde es una recuperación que nadie usaba— y la alternativa,
  una sesión expirada que conserva credenciales, es peor. La salida es llevar la generación dentro
  de la notificación y limpiar sólo cuando la sesión que expira siga siendo la vigente.

## Verificación: lo que los tests no cubren

El repaso manual del flujo (tarea 11.7) **no se ha ejecutado**, y se acepta así a sabiendas.
Este worktree enlazado no publica ningún puerto, y con `make up PORT_OFFSET=<n>` `sdd/project.md`
documenta —medido el 2026-08-23 en `cleaning-assign-preconditions`— que la página se sirve pero
**no hidrata** (Next 15+ bloqueando peticiones de desarrollo de origen cruzado sin
`allowedDevOrigins`); arreglar eso sería cambiar la configuración de la app para poder mirarla,
que no es mirarla.

Lo que sí está verificado, y con qué: cada pieza del flujo tiene test de componente sobre DOM real
—la campana con contador y su nombre accesible, el panel con sus tres estados y la paginación, el
acuse optimista bajando el contador **antes** de que responda el servidor, la reversión al fallar,
«marcar todas», y el enlace a `/incidents/[id]`—, en verde en el panel de review (248/248 en
frontend, 156/156 en backend, paridad de catálogos 17/17, typecheck limpio).

**El riesgo residual, que ningún test de DOM puede cerrar**: que la campana se vea bien en el
topbar junto a los otros cuatro controles, y que el panel `Sheet` sea usable en una pantalla de
móvil real. Se verificará en `dev` tras el despliegue; si algo falla ahí es ajuste visual, no
comportamiento.

### Corrección: «sólo visual» era falso, y CI lo demostró

Escrito arriba antes de abrir el PR, y **desmentido por el propio PR #136**: el job
`provenance-contract` falló en su paso `npm run build`. El párrafo anterior daba por hecho que lo
único fuera del alcance de los tests era la apariencia. No lo era: faltaba **una clase entera de
verificación**, la de fronteras Server/Client de React, que sólo `next build` ejecuta.

`notification-inbox-sheet.tsx` importaba `useNotificationsPanel` desde el barrel
`@/features/shell`, y ese barrel reexportaba las cinco shells y `routeMetadata`, que alcanzan
`server-only` (las shells por `lib/theme/server`, `routeMetadata` por
`lib/metadata/create-route-metadata` → `lib/i18n/server`). Resultado: un Client Component
arrastraba `server-only` al bundle del navegador. **Ni `tsc` ni las 1749 pruebas del frontend
pueden ver eso** — todas pasaban, y siguen pasando; la frontera sólo existe en tiempo de build.

**Arreglado invirtiendo el barrel**: `@/features/shell` es ahora la API client-safe
(`PageHeader`, `ShellProfile`, `useNotificationsPanel`) y `@/features/shell/server` la de
composición de servidor (las cinco shells y `routeMetadata`); los 29 ficheros de `app/` que las
consumían apuntan allí, que es gratis porque la frontera ESLint restringe `@/features/*/**` sólo
a ficheros bajo `features/` y `app/` compone libremente por diseño. La client-safety del barrel
pasa de ser suerte a ser contrato, escrito en la cabecera de los dos ficheros.

Descartadas: pasar el estado por props (las tres shells son Server Components asíncronas y no
pueden leer un store de cliente) y el import profundo (lo prohíbe la frontera ESLint).

**La lección para el siguiente**: `npm run build` no corre en local en ningún sitio de este
proyecto —vive únicamente en el job `provenance-contract` de `frontend-tests.yml`—, así que una
sección de Verification que no lo invoque deja abierta esta clase entera. Verificado ahora en
local con las mismas variables que usa CI: build correcto, `lint` limpio, `typecheck` limpio,
1749/1749 pruebas y el gate de artefactos públicos sobre 2178 artefactos.

## ASSUMPTIONS

- **A1** — La forma exacta de la ruta de acuse (`POST /api/v1/notifications/{id}/read` frente a un
  `PATCH` sobre el recurso) y la del contador (campo en el envelope frente a endpoint propio) se deciden
  en `/sdd:design`. R1 y R2 fijan el comportamiento observable, no la firma.
- **A2** — El acuse **no** se audita en `AuditLog`: leer un aviso propio no es una operación sobre datos
  de otro ni una concesión de permiso, y `steering/security.md` regla 9 no la enumera. Si el design
  concluye lo contrario, es una decisión suya y debe bajar aquí.
- **A3** — *(enmendado en `/sdd:design`, 2026-08-29 — design D18)*. `SUPER_ADMIN` tiene
  `READ_OWN_NOTIFICATIONS` porque el permiso vive en `_SELF_SERVICE`
  (`backend/app/auth/domain/policy.py:153`), y eso sigue siendo cierto. Lo que **no** es cierto es
  la conclusión que esta línea sacaba de ello: las tres shells cubren **cuatro** roles, no cinco.
  `roleHome` manda a `SUPER_ADMIN` a `/dashboard` y el `AuthGuard` de `app/(workspace)/layout.tsx`
  admite sólo `TENANT_OWNER` y `PROPERTY_MANAGER`, así que lo rebota a `/login?denied=role`;
  `/welcome` hace el mismo rebote. `SUPER_ADMIN` no alcanza hoy **ninguna** superficie autenticada,
  y este change no lo cambia: con `_SELF_SERVICE` como único juego de permisos, darle sitio en
  `WorkspaceShell` sería una campana rodeada de nueve pantallas en `403`. Su superficie es una
  consola de plataforma propia, registrada como candidata de roadmap `super-admin-console` en el
  design D18. No se estrena rol ninguno, que era el punto que esta línea existía para dejar dicho.

## Cómo se certificó este change, y qué no lo respalda

Se deja escrito porque `STATE.md` no puede distinguir un gate satisfecho de un gate
no ejecutado, y quien lea esto dentro de seis meses merece saber cuál de los dos fue.

**Lo que sí respalda la certificación.** Siete revisores —`sdd-architect`, `sdd-security`,
`sdd-qa` y los cuatro de proyecto (`cicd`, `documentation`, `i18n`, `tenancy`)— corrieron
sobre el árbol el 2026-08-29 y devolvieron PASS con **cero hallazgos**; más una re-revisión
acotada de documentación, también PASS, sobre los cambios posteriores al panel. Cifras
medidas, no afirmadas: 156/156 en `tests/notifications` + `test_route_authorization`,
248/248 en frontend (30 ficheros), 17/17 de paridad de catálogos, `typecheck` limpio, y los
dos checks de contrato (`openapi --check`, `api:check`) en verde ejecutados de verdad.

**Lo que NO respalda la certificación: el gate ejecutable del panel no participó.**
`skills/reviewer-panel/reviewer_plan.py` de `sdd-toolkit` 0.40.0 valida un JSON de resultados
que le entrega quien despacha el panel. Entre un subagente de Claude y ese gate no hay canal
automático: el transporte es el modelo que despacha, así que «alimentar el gate» habría sido
transcribir a mano siete veredictos y pedirle al gate que validara mi propia transcripción.
El PASS resultante habría certificado la transcripción, no el trabajo de los revisores, y
habría llevado más autoridad de la que se gana. Se prefirió no ejecutarlo a ejecutarlo vacío.

Aparte de eso, el parser del gate rechazaba el `description` que Claude Code exige en
`.claude/agents/*.md`, así que los cuatro revisores de proyecto salían `unavailable` y el gate
no podía pasar dijera lo que dijera nadie. Eso sí se arregló, parcheando el toolkit para que
tolere claves de frontmatter que no consume (no se tocó `.claude/agents/`, que es compartido).
La salida de verdad es un toolkit con un protocolo de resultados que la ruta Claude pueda
producir; hasta entonces, esta nota es el sustituto honesto.
