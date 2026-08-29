# Tasks: notifications-inbox-web

> Orden pensado para que el sistema siga funcionando tras cada sección: el backend cierra el
> ciclo (§1–§4) antes de que el frontend lo consuma (§5–§9). Cada tarea lleva su test; la
> sección final corre la suite entera con los comandos de `sdd/project.md`.

## 1. Esquema: `read_at` y sus dos índices <!-- panel: PASS 2026-08-29 -->

- [x] 1.1 Añadir la columna y los índices al modelo — `backend/app/notifications/infrastructure/models.py`.
  `read_at: Mapped[datetime | None]` (`TIMESTAMPTZ`, nullable, **sin** `server_default`), y en
  `__table_args__` los dos `Index` de D1 junto a los dos que ya hay:
  `ix_notification_logs_tenant_id_recipient_user_id_created_at` sobre
  `(tenant_id, recipient_user_id, created_at DESC)` y el parcial `ix_notification_logs_unread`
  sobre `(tenant_id, recipient_user_id)` con `postgresql_where=read_at.is_(None)`. [R1.1]
- [x] 1.2 Migración Alembic — `backend/alembic/versions/<rev>_notifications_read_at.py` (nuevo),
  `down_revision = 'd4a7e18c6b93'` (cabeza actual, verificada). `upgrade` añade la columna
  nullable sin default y crea los dos índices; `downgrade` los borra y quita la columna. Sin
  backfill: toda fila preexistente queda en `NULL`. [R1.1]
- [x] 1.3 `read_at: datetime | None = None` en la entidad de dominio —
  `backend/app/notifications/domain/entities.py`. Actualizar
  `backend/tests/notifications/test_entities.py` y `test_models.py` para fijar que una fila
  recién creada nace con `read_at is None` y que los dos índices nuevos están declarados en la
  metadata. [R1.1]

## 2. Puerto y repositorio <!-- panel: PASS 2026-08-29 -->

- [x] 2.1 Ampliar el puerto — `backend/app/notifications/domain/repositories.py`:
  `list_for_recipient(..., unread: bool | None = None)`,
  `mark_read(tenant_id, user_id, log_id) -> bool`, `count_unread(tenant_id, user_id) -> int`,
  `mark_all_read(tenant_id, user_id) -> int`. Docstrings en inglés, en la línea estrecha del
  resto del puerto (D2: escrituras acotadas, nunca un `save` genérico). [R1.2, R2.2, R2.3, R5.2]
- [x] 2.2 `mark_read` en el repositorio SQLAlchemy —
  `backend/app/notifications/infrastructure/repositories.py`. Un único
  `UPDATE ... SET read_at = COALESCE(read_at, :now) WHERE tenant_id AND recipient_user_id AND id`,
  devolviendo `rowcount > 0` (D3). Test en `backend/tests/notifications/test_repositories.py`:
  primera lectura fija `read_at`; segunda llamada devuelve `True` y **no** mueve el valor
  (idempotencia); id inexistente, de otro usuario del mismo tenant y de otro tenant devuelven los
  tres `False`. [R1.2, R1.3, R1.4]
- [x] 2.3 `count_unread` y `mark_all_read` —
  `backend/app/notifications/infrastructure/repositories.py`. `count_unread` es un `SELECT count(*)`
  con `read_at IS NULL` acotado a tenant + destinatario (D4); `mark_all_read` es un `UPDATE ...
  SET read_at = :now WHERE ... AND read_at IS NULL` que devuelve el número de filas movidas y
  **no** falla con cero (D6). Tests en `test_repositories.py`: el contador ignora las leídas, las
  de otros usuarios y las de otros tenants; `mark_all_read` sobre bandeja al día devuelve `0`. [R2.2, R5.2]
- [x] 2.4 Filtro `unread` en `list_for_recipient` —
  `backend/app/notifications/infrastructure/repositories.py`. Condición `read_at IS NULL` cuando
  `unread is True`; ausente por defecto (D5). Test en `test_repositories.py`: el envelope
  (`items`/`total`), el orden de más nueva a más vieja y los topes de paginación se conservan con
  y sin el filtro. [R2.3]

## 3. Casos de uso, errores y rutas <!-- panel: PASS 2026-08-29 -->

- [x] 3.1 Error de dominio para el `404` —
  `backend/app/notifications/domain/exceptions.py`: `NotificationNotFoundError`, hermano del
  `NotificationLogNotFoundError` existente (que cubre otro caso: una escritura del job que no
  encuentra fila). El mensaje no distingue entre inexistente / de otro usuario / de otro tenant. [R1.4]
- [x] 3.2 Tres casos de uso — `backend/app/notifications/application/use_cases.py`:
  `MarkNotificationReadUseCase` (levanta `NotificationNotFoundError` cuando `mark_read` devuelve
  `False`), `CountUnreadNotificationsUseCase`, `MarkAllNotificationsReadUseCase`; y
  `ListOwnNotificationsUseCase.execute` acepta `unread`. Sus proveedores en
  `backend/app/notifications/api/dependencies.py`, con la forma que ya usa
  `get_list_own_notifications_use_case`. [R1.2, R1.3, R2.2, R2.3, R5.2]
- [x] 3.3 Esquemas de respuesta — `backend/app/notifications/api/schemas.py`: `read_at:
  datetime | None` y `notification_type: NotificationType | str` en `NotificationResponse` (D7),
  más `UnreadCountResponse` (`{"unread": int}`) y `MarkAllReadResponse` (`{"updated": int}`).
  `recipient_contact`, `last_error`, `sla_deadline_at` y `sla_breached` **siguen sin publicarse**;
  el docstring del módulo lo sigue diciendo. [R2.1]
- [x] 3.4 Tres rutas — `backend/app/notifications/api/router.py`, todas con
  `Permission.READ_OWN_NOTIFICATIONS` y el destinatario derivado del JWT:
  `GET /unread-count` (declarada **antes** que cualquier ruta con parámetro de camino, D4),
  `POST /{notification_id}/read` → `204`, `POST /read-all` → `{"updated": int}`; y el
  `?unread=` opcional en la ruta de listado. Reescribir el docstring del módulo: el párrafo
  «No "mark as read"» deja de ser cierto y se sustituye por el ciclo cerrado. [R1.2, R2.2, R2.3, R5.2]
- [x] 3.5 Tests de API — `backend/tests/notifications/test_api.py`: acuse sobre una no leída
  responde `204` y la fila pasa a leída; acuse repetido responde `204` sin mover `read_at`; id
  inexistente y de otro usuario del mismo tenant responden `404` con **el mismo cuerpo**;
  `unread-count` devuelve el total del usuario del token con independencia de `per_page`;
  `?unread=true` devuelve solo las no leídas sin romper el envelope de PRD §23; `read-all` sobre
  bandeja vacía devuelve `{"updated": 0}`. **Corregido en `/sdd:run` (2026-08-29)**: esta tarea
  pedía además «un rol sin `READ_OWN_NOTIFICATIONS` recibe `403`», y **no existe tal rol** —
  el permiso vive en `_SELF_SERVICE` (`backend/app/auth/domain/policy.py`) y lo tienen los
  cinco miembros de `UserRole`, medido contra `ROLE_PERMISSIONS`. Es el mismo hecho que A3 del
  proposal y D18 del design ya dejan escrito por otro motivo. En su lugar el test fija lo que
  sí es cierto y sí puede fallar: las tres rutas **no** son anónimas (`401` sin token) y
  ningún rol autenticado recibe `403` — que es exactamente donde `access-notifications` acabó
  para la ruta de listado. Lo que hace segura la superficie no es el permiso sino el acotado
  por destinatario, y eso lo prueban 3.6 y los tests de repositorio. [R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R5.2]
- [x] 3.6 Aislamiento de tenant — `backend/tests/notifications/test_read_isolation.py` (nuevo):
  un usuario del tenant B no puede acusar ni contar ni «marcar todas» filas del tenant A —
  `404` en el acuse y contadores que no se contaminan. Regla 1 de `steering/security.md`; el test
  se escribe sobre sesión **no** marcada, para que pueda fallar de verdad. [R1.5]
- [x] 3.7 Snapshot de rutas protegidas — `backend/tests/test_route_authorization.py`: añadir las
  tres rutas nuevas con su permiso. Sin esto la suite entera queda en rojo. [R1.2]
- [x] 3.8 El SLA no mira `read_at` — tests en `backend/tests/notifications/test_repositories.py`
      (`test_acknowledging_moves_nothing_the_sla_looks_at`, `test_mark_all_read_moves_nothing_the_sla_looks_at_either`): contra la tabla real,
      porque la afirmación es sobre lo que un statement le hace al otro y un fake sólo
      probaría que el fake se da la razón a sí mismo.
  (o fichero vecino): acusar una notificación no mueve `sla_deadline_at` ni `sla_breached` ni la
  saca de `list_sla_breach_candidates`. Verificar además por lectura que ni
  `list_sla_breach_candidates`, ni `escalation_for`, ni `check_sla_breaches` mencionan `read_at`. [R1.6]
- [x] 3.9 Confirmar que el acuse **no** escribe `AuditLog` (D8/A2): ningún caso de uso nuevo
  toca el repositorio de auditoría. Se verifica leyendo el diff del backend, sin código añadido. [R1.2]

## 4. Contrato publicado

- [x] 4.1 Regenerar `backend/openapi.json` (`make openapi`) y
  `frontend/lib/api/generated/openapi.d.ts`, y commitear ambos en el mismo PR. Desde este worktree
  enlazado el `npm run api:generate` documentado **no** funciona tal cual: usar el rodeo con
  `docker compose cp` de `sdd/project.md`. Comprobar en el `.d.ts` que aparece
  `components["schemas"]["NotificationType"]` como unión de los diecisiete literales — es lo que
  hace comprobable a R4.1. [R2.4]

## 5. Frontend: datos y hooks <!-- panel: PASS 2026-08-29 -->

- [x] 5.1 Capa de datos — `frontend/features/notifications/data/{dto.ts,index.ts,http/http-notifications-source.ts}`
  (nuevos), con el molde de `features/incidents/data/`: DTOs camelCase derivados del contrato
  generado, `getNotificationsDataSource()` como **único** punto de composición sobre
  `createAuthenticatedClients`. Cuatro operaciones: listar (con `page`/`perPage`/`unread`), contar
  no leídas, acusar una, acusar todas. Test en `data/http/http-notifications-source.test.ts`:
  rutas y parámetros correctos, mapeo del envelope, `read_at` → `readAt`. [R2.1, R2.2, R2.3, R5.2]
- [x] 5.2 Claves de caché — `frontend/features/notifications/hooks/query-keys.ts`:
  `tenantScopedKey(tenantId, "notifications-unread", userId)` y
  `tenantScopedKey(tenantId, "notifications-list", userId, filters)` (D12). Test: dos usuarios del
  mismo tenant producen claves distintas. [R3.4]
- [x] 5.3 Query del contador — `frontend/features/notifications/hooks/use-unread-count.ts`, con
  `refetchInterval: 60_000`, `refetchIntervalInBackground: false` y `retry: retryPolicy` (D11).
  Test en `use-unread-count.test.tsx`: el hook configura esos tres valores (es el primer
  `refetchInterval` del repositorio, así que el test es lo que lo fija). [R3.3]
- [x] 5.4 Query del listado — `frontend/features/notifications/hooks/use-notifications.ts`,
  paginada, **sin** `refetchInterval` (D11), `retry: retryPolicy`. Test: pide la página y los
  filtros que recibe y no configura polling. [R4.5]
- [x] 5.5 Mutación de acuse optimista — `frontend/features/notifications/hooks/use-mark-read.ts`
  (D13): `onMutate` fija `readAt` en la fila cacheada y decrementa el contador; `onError` restaura
  el snapshot; `onSettled` invalida el prefijo de las dos queries. Tests en `use-mark-read.test.tsx`:
  el contador baja antes de que responda el servidor; un fallo revierte fila **y** contador; tras
  el éxito se invalidan ambas queries. [R5.1, R5.3, R5.4]
- [x] 5.6 Mutación «marcar todas» — `frontend/features/notifications/hooks/use-mark-all-read.ts`,
  con la misma invalidación de R5.4 y reversión en `onError`. Test del camino feliz y del fallo. [R5.2, R5.3, R5.4]
- [x] 5.7 Mapeo de errores — `frontend/features/notifications/lib/error-mapping.ts` con su test,
  siguiendo `features/incidents/lib/error-mapping.ts`: cada fallo del acuse produce una clave i18n,
  nunca el texto crudo del servidor. [R5.3]

## 6. i18n y copia de la bandeja <!-- panel: PASS 2026-08-29 -->

- [x] 6.1 Namespace nuevo — `frontend/locales/es/notifications.json` y
  `frontend/locales/en/notifications.json` (nuevos), registrados en `NAMESPACES` y en `resources`
  de `frontend/lib/i18n/resources.ts` (lo exige `lib/i18n/catalog-parity.test.ts`, que compara
  contra el disco). Contienen `types.<NOMBRE>` para los **diecisiete** miembros de
  `NotificationType`, `types.unknown`, el nombre accesible de la campana, el título del panel, los
  tres estados (carga, error, vacío), el botón «marcar todas» y los mensajes de error. [R4.1, R4.3, R3.5, R4.5, R5.3]
- [x] 6.2 Catálogo tipado — `frontend/features/notifications/lib/notification-copy.ts`:
  `Record<NotificationType, string>` sobre el tipo generado del contrato (D7/D14), de modo que un
  tipo sin traducir **rompa `npm run typecheck`**; la lectura es
  `catalog[type as NotificationType] ?? "notifications:types.unknown"`. Test: los diecisiete tipos
  resuelven a una clave distinta de la genérica, y un valor desconocido cae en `types.unknown`. [R4.1, R4.3]
- [x] 6.3 Formato de fecha — `frontend/features/notifications/lib/format.ts` con
  `Intl.DateTimeFormat(locale, …)` como hacen `dashboard` y `pricing`, y su test en `es` y `en`. [R4.4]

## 7. Campana y panel <!-- panel: PASS 2026-08-30 -->

- [x] 7.1 Slot del panel en el store de shell —
  `frontend/features/shell/state/use-shell-ui-store.ts`: un `notificationsOpen` efímero (no
  persistido) con su setter, incluido en `closeOverlays()` para que `OverlayAutoCloser` cierre el
  panel al navegar (D9). Test en el fichero de test del store: `closeOverlays` lo apaga y
  `partialize` no lo persiste. [R4.5]
- [x] 7.2 `NotificationBell` — `frontend/features/notifications/components/notification-bell.tsx`:
  campana con contador cuando hay no leídas y sin distintivo cuando es cero, `aria-label`
  traducido y el número anunciado a lectores de pantalla. **Devuelve `null`** si
  `status !== "authenticated"` o `user === null` (D16: en las shells de campo el `AuthGuard` está
  dentro de la shell). Tests: contador visible / ausente, nombre accesible traducido, y que no
  revienta ni pinta nada sin sesión resuelta. [R3.2, R3.5, R3.4]
- [x] 7.3 Panel de bandeja —
  `frontend/features/notifications/components/notification-inbox-sheet.tsx`: `Sheet` (mismo
  primitivo que `MoreMenu`), mobile-first, listado paginado con los tres estados explícitos
  (carga, error, vacío) y el botón «marcar todas como leídas». `open` gobernado por el store de
  7.1. Tests de los tres estados y del botón. [R4.5, R5.2]
- [x] 7.4 Fila de notificación —
  `frontend/features/notifications/components/notification-row.tsx`: texto desde
  `notification-copy.ts` (nunca `subject`/`body`), fecha localizada, distinción visual entre leída
  y no leída, y acuse al abrirla. Tests: una fila con `subject`/`body` en inglés se pinta con el
  texto traducido y **no** muestra ni el asunto ni ningún UUID; un `notification_type` desconocido
  cae en el texto genérico sin romper la lista; abrir una no leída dispara el acuse. [R4.2, R4.3, R4.4, R5.1]
- [x] 7.5 Frontera pública — `frontend/features/notifications/index.ts` exportando
  `NotificationBell`, los hooks y las claves, en la línea de `features/incidents/index.ts`. [R3.1]

## 8. Destinos de navegación <!-- panel: PASS 2026-08-30 -->

- [x] 8.1 Tabla de destinos —
  `frontend/features/notifications/lib/notification-destinations.ts`:
  `Record<ShellProfile, Partial<Record<string, (id: string) => string>>>` con `workspace` poblado
  (`incident` → `/incidents/[id]`, `conversation` → `/conversations/[id]`, `reservation` →
  `/reservations/[id]` — las tres páginas existen) y `cleaner`/`technician` declarados y **vacíos**,
  con el motivo escrito al lado (`RoutePlaceholder` hasta `cleaner-app` y `tech-app`).
  `cleaning_task` no aparece. [R6.1, R6.2, R6.4]
- [x] 8.2 Cablear la tabla en la fila (7.4) y probarla: en `workspace` los tres tipos enlazan a su
  ruta; en `cleaner` y `technician` ninguna fila enlaza; `relatedType`/`relatedId` a `null`, o un
  tipo fuera de la tabla, pintan la fila sin enlace y **sin** enseñar el UUID. [R6.1, R6.2, R6.3]

## 9. Montaje en las tres shells <!-- panel: PASS 2026-08-30 -->

- [x] 9.1 Añadir `NotificationBell` al slot `end` de las tres shells autenticadas —
  `frontend/features/shell/components/{workspace,cleaner,technician}-shell.tsx`: el slot pasa de
  `[ThemeSwitcher, Separator, LocaleSwitcher, UserMenu]` a
  `[ThemeSwitcher, Separator, LocaleSwitcher, NotificationBell, UserMenu]`, importando el punto de
  entrada público `@/features/notifications` (mismo patrón que `UserMenu` con `@/features/auth`). [R3.1]
- [x] 9.2 Tests de shell — `frontend/features/shell/components/workspace-shell.test.tsx` y
  `field-public-guest-shell.test.tsx`: la campana está en las tres shells autenticadas y **no**
  está en `PublicShell` ni en `GuestShell`. [R3.1]
- [x] 9.3 Comprobar que no se toca `routeRegistry` ni se añade ningún `page.tsx` (D9): 
  `frontend/app/route-coverage.test.ts` debe seguir en verde sin cambios. [R4.5]

## 10. Documentación

- [x] 10.1 `docs/access-notifications.md`: la bandeja pasa de «se listan, no se acusan» a ciclo
  cerrado — campana, panel, acuse, «marcar todas» y las tres rutas nuevas. Revisar el `README.md`
  raíz y actualizarlo solo si algo de su descripción del sistema deja de ser cierto
  (`steering/documentation.md`). [R2.4]
- [x] 10.2 Dejar anotado para `/sdd:archive` lo que le corresponde y **no** se hace aquí:
  regenerar `docs/diagrams/2026-08-23_autohost-er-entidades.png` (el recuento de columnas pasa de
  425 a 426) y añadir la entrada candidata de roadmap `super-admin-console` con su nota larga
  (design D18). Ambos encargos quedan redactados en `proposal.md` § «Encargos a `/sdd:archive`»,
  con las cifras medidas y el texto de la entrada, para que archivar no tenga que redescubrirlos.
  *(Encargo del design, no cubre requisito propio.)*

## 11. Verification

- [x] 11.1 **Medir la cifra de partida del frontend antes de tocar nada** y aplicar los
  `docker compose cp` de `sdd/project.md` (los dos `ENOENT` ajenos reaparecen tras cada `make up`).
  El número de referencia se mide, no se recuerda.
  **Medido 2026-08-29 antes de tocar nada: 155 ficheros, 1531 tests.** Los dos `ENOENT` que
  documenta `sdd/project.md` NO aparecieron: el rodeo funcionó.
  **Aviso de método descubierto en este run**: con la máquina cargada los workers de vitest
  mueren por memoria, y la señal no es el rojo sino el **recuento de ficheros** — un
  `Test Files 10 passed (13)` significa que tres no llegaron a ejecutarse y esa cifra no vale.
  Medir con `--maxWorkers=1`.
- [x] 11.2 Suite del backend en verde: `docker compose exec backend uv run pytest`.
- [x] 11.3 Migración aplicable y reversible sobre la base de dev, que tiene filas:
  `alembic upgrade head` y `alembic downgrade -1` sin error, y `read_at` en `NULL` en toda fila
  preexistente. [R1.1]
- [x] 11.4 Suite del frontend en verde: `cd frontend && npm test`, comparada contra la cifra de
  11.1; y `npm run typecheck` en verde — que es lo que prueba que los diecisiete tipos están
  traducidos (D7). [R4.1]
  **Medido: 166 ficheros, 1628 tests, todos verdes, 0 skipped** (`--maxWorkers=1`), contra los
  155/1531 de 11.1 → **+11 ficheros, +97 tests**, y los once nuevos son exactamente los de
  `features/notifications/`. `npm run typecheck` en verde; probado por mutación que borrar un
  tipo del `Record` lo pone en rojo con `TS2741`, que es lo que hace comprobable a R4.1.
- [x] 11.5 Contrato sin deriva: `npm run api:check` (con el rodeo de `sdd/project.md`), de modo que
  los workflows `api-contract` y `frontend-api-contract` no fallen. [R2.4]
- [x] 11.6 Paridad de catálogos e i18n: `lib/i18n/catalog-parity.test.ts` en verde y ninguna
  cadena de UI nueva escrita a fuego en un componente. [R4.1]
- [x] 11.7 Repaso manual del flujo — **no ejecutado, y dicho explícitamente en vez de darlo por
  bueno**, que es lo que esta tarea manda hacer cuando no se puede correr. Este worktree no publica
  puertos y `PORT_OFFSET` no sirve para una pasada visual: la página se sirve pero no hidrata
  (`sdd/project.md`, medido el 2026-08-23 en `cleaning-assign-preconditions`). Decisión tomada en
  `/sdd:review` el 2026-08-29: se acepta la cobertura automática, que cubre **el comportamiento**
  entero del flujo sobre DOM real —campana con contador y nombre accesible, panel con sus tres
  estados, paginación, acuse optimista bajando el contador antes de que responda el servidor,
  reversión al fallar, «marcar todas», enlace a `/incidents/[id]`—, verde en el panel de review
  (248/248 frontend, 156/156 backend, 17/17 paridad, typecheck limpio). El riesgo residual es
  **sólo visual** —colocación de la campana entre los otros cuatro controles del topbar, y el
  `Sheet` en un móvil real— y se verifica en `dev` tras el despliegue. Escrito en
  `proposal.md` § «Verificación: lo que los tests no cubren». [R3.1]
