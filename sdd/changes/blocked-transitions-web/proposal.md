# Proposal: blocked-transitions-web

## Why

`GET /api/v1/blocked-transitions` existe desde `cleaning-stall-blocks-next-stay` (archivado el
2026-08-24), entrega el desajuste con permiso `READ_PROPERTIES` —lo tienen `PROPERTY_MANAGER` y
`TENANT_OWNER`— y **nadie lo consume**. La R2 de aquel change decía «que no me enteré por un
huésped», y se cumple sólo en el dato: una propietaria —PRD §1, dos viviendas en el móvil— y un
manager —PRD §2, opera reservas/limpiezas/incidencias— ven los mismos datos en la card de la
vivienda del dashboard, pero no este. Mientras siga así, el atasco medido en `dev` (REDES11 del
2026-08-16 al 2026-08-22) **se repite en silencio**: el reloj lo registra, el log lo dice, y
ninguna persona se entera hasta que el huésped escribe.

El encargo explícito vive en el design D11 de `cleaning-stall-blocks-next-stay` y la nota de
roadmap [`sdd/roadmap/blocked-transitions-web.md`](../../roadmap/blocked-transitions-web.md):
pintar los desajustes donde el manager ya mira, en `locales/es` **y** `locales/en`, y con salida
—sin acción al lado, el aviso es el mismo silencio con otra forma.

## What changes

Después de este change, la card de cada vivienda en `/dashboard` muestra los desajustes de su
propiedad ordenados por `due_since` ascendente —lo primero que el operador necesita es lo que
lleva más tiempo parado—, con el `trigger` y `blocking_state` como literales canónicos (mismo
trato que `operational_state` en `dashboard-api`), el `due_since` formateado en el locale del
usuario, y un botón de acción cuando el rol del llamante pueda ejecutarla. La propietaria ve el
aviso porque `READ_PROPERTIES` le basta; el `PROPERTY_MANAGER` ve además los botones de cancelar
limpieza y resolver incidencia porque tiene `MANAGE_CLEANING_TASKS` y `EXECUTE_INCIDENTS`.

El aviso desaparece solo: `cleaning-stall-blocks-next-stay` R2.4 ya garantiza que la próxima
consulta no devuelve un desajuste resuelto, así que pintar sin sondear es el comportamiento por
defecto.

## Requirements

### R1 — Cada desajuste de su vivienda aparece en su card del dashboard

**As a** propietaria o `PROPERTY_MANAGER`, **I want** ver en la card de cada vivienda, en
`/dashboard`, los desajustes que le atañen, **so that** una vivienda parada no dependa de que
alguien la mire por casualidad.

Acceptance criteria:

1. WHEN una vivienda del tenant tiene uno o más desajustes vigentes, THE SYSTEM SHALL
   mostrarlos dentro de la card de esa vivienda en `/dashboard`, ordenados por `due_since`
   ascendente y con desempate estable por `reservation_id` y `trigger`.
2. THE SYSTEM SHALL mostrar para cada desajuste su `property_code` (la vivienda ya viene
   implícita por la card), el `trigger` y el `blocking_state` como **literales canónicos**,
   sin prosa traducida y sin color inventado —el color, si lo hay, sale de la misma tabla que
   `dashboard-api` usa para `operational_state`—, y el `due_since` formateado en el locale del
   usuario con fecha y hora.
3. WHEN la vivienda no tiene desajustes vigentes, THE SYSTEM SHALL no pintar sección, badge ni
   estado vacío: la card queda como está hoy.
4. THE SYSTEM SHALL respetar el aislamiento por tenant: una card nunca muestra desajustes de
   otro tenant.
5. THE SYSTEM SHALL no inventar contenido —ni estado, ni acción, ni fechas— a partir del
   `trigger` o `blocking_state`: el mapeo a una posible acción se declara en la spec del
   componente y se cubre con tests, no con `if (state === …)` distribuidos.

### R2 — El aviso se ve con `READ_PROPERTIES` y se opera con permisos de escritura

**As a** usuaria autenticada, **I want** que la pantalla refleje mis permisos sin esconderme
información ni prometerme acciones que devolverán `403`, **so that** vea siempre lo mismo que
mi rol le permite ver, y opere sólo lo que mi rol le permite operar.

Acceptance criteria:

1. WHEN el rol del llamante tiene `READ_PROPERTIES`, THE SYSTEM SHALL mostrar el aviso y SHALL
   no ocultarlo por motivos de rol.
2. WHEN el rol del llamante tiene `MANAGE_CLEANING_TASKS` y el `blocking_state` mapea a una
   limpieza activa, THE SYSTEM SHALL ofrecer la acción de cancelar limpieza
   (`POST /api/v1/cleaning-tasks/{task_id}/cancel`, con motivo obligatorio).
3. WHEN el rol del llamante tiene `EXECUTE_INCIDENTS` y el `blocking_state` mapea a una
   incidencia activa, THE SYSTEM SHALL ofrecer la acción de resolver incidencia
   (`POST /api/v1/incidents/{id}/resolve`).
4. WHEN el rol del llamante no tiene el permiso de la acción disponible, THE SYSTEM SHALL no
   mostrar el botón —nunca SHALL pintar un botón que responderá `403`—.
5. THE SYSTEM SHALL consultar el rol del llamante desde el estado de sesión ya disponible en
   el frontend (`frontend-auth-session`), sin un endpoint nuevo.

### R3 — Una acción confirmada refresca el aviso sin recarga

**As a** `PROPERTY_MANAGER`, **I want** que cancelar la limpieza o resolver la incidencia
desaparezca el aviso al instante, **so that** vea de inmediato que el desajuste quedó
resuelto y no tenga que recargar la pestaña.

Acceptance criteria:

1. WHEN el usuario confirma una acción de R2.2 o R2.3, THE SYSTEM SHALL invocar el endpoint
   correspondiente del backend con el cuerpo que su contrato exige —incluido el motivo
   obligatorio de la cancelación— y SHALL no sintetizar campos que la API ya conoce por URL o
   por la sesión.
2. WHEN la acción termina en éxito, THE SYSTEM SHALL invalidar la query de
   `GET /api/v1/blocked-transitions` del dashboard para que la próxima lectura no incluya el
   desajuste resuelto.
3. WHEN la acción termina en error (`4xx`/`5xx`), THE SYSTEM SHALL mostrar el mensaje
   localizado que devuelva el backend —o el genérico del contrato común si el detalle no es
   seguro— y SHALL dejar el aviso en pantalla.
4. IF el backend rechaza la cancelación con `409` por el motivo que `cleaning-stall-blocks-next-stay`
   documenta (estado terminal, huésped activo), THEN THE SYSTEM SHALL mostrar el motivo al
   usuario y SHALL no reintentar.

### R4 — El aviso es localizable y los literales no se traducen

**As a** usuario de la app, **I want** leer el aviso en mi idioma, **so that** el catálogo de
traducciones no me obligue a aprender los códigos de la matriz.

Acceptance criteria:

1. THE SYSTEM SHALL añadir las cadenas de la pantalla —etiquetas, verbos de los botones, mensajes
   de error, formato de fecha— en `frontend/locales/es/<namespace>.json` y en
   `frontend/locales/en/<namespace>.json`, sin hardcodear ni una sola en componentes.
2. THE SYSTEM SHALL mostrar `trigger` y `blocking_state` como los literales canónicos que
   devuelve el backend —`CHECKIN_TIME_REACHED`, `CLEANING_IN_PROGRESS`, etc.—, sin traducirlos
   ni colorearlos por su valor. El color, si se usa, sale del mismo mapping que
   `property-state-badge.tsx` aplica a `operational_state`; la traducción de la prosa vive en
   `locales/`.
3. THE SYSTEM SHALL no introducir un catálogo paralelo de traducciones de los literales: el
   backend los emite sin prosa a propósito (ver `cleaning-stall-blocks-next-stay` R2.2 y el
   docstring de `BlockedTransitionResponse`) y este change los respeta.

### R5 — Los límites del backend se declaran en la pantalla

**As a** operadora del sistema, **I want** saber que el aviso no es exhaustivo, **so that** un
atasco de más de 30 días no me haga pensar que el sistema se ha olvidado cuando en realidad
dejó de mirarlo por la ventana operativa.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en `docs/properties.md` que un atasco de más de 30 días deja de
   aparecer —el mismo límite de `candidate_window` que
   `sdd/specs/celery-jobs.md` declara para el job—, y SHALL enlazarlo desde la pantalla con un
   texto breve que no ocupe más de una línea.
2. THE SYSTEM SHALL no prometer exhaustividad en la copia de la pantalla: ni «todas las
   viviendas», ni «en tiempo real», ni «completo».
3. WHERE la query falle con `5xx`, THEN THE SYSTEM SHALL mostrar el estado de error localizado
   del contrato común y SHALL no ocultar la card de la vivienda detrás de un error global.

## Out of scope

- **Pintar también en `/cleaning` o en una página dedicada `/blocked-transitions`.** La nota de
  roadmap lo dejaba abierto; este change pinta solo en la card del dashboard por ser donde la
  propietaria mira primero (PRD §1) y donde el manager ya entra cada mañana.
- **Refactor de `PropertyRepository.list_all` para paginar en origen.** Aparece como deuda
  declarada en `sdd/specs/celery-jobs.md` §"Dos deudas declaradas"; con dos viviendas es
  irrelevante y no se paga aquí.
- **Sondeo automático (polling / WebSocket) del aviso.** El refresh por invalidación tras la
  acción cubre R3; un sondeo continuo entra en su propia decisión de coste y de plataforma.
- **Notificación push al móvil del manager.** El alcance es pull en el dashboard, no canal
  saliente.
- **Editar el catálogo de literales canónicos de `trigger` o `blocking_state`.** Son del
  backend; este change los consume tal cual.
- **El `409` específico de cancelación con huésped activo**: ya lo rechaza el backend y R3.4 lo
  muestra, pero la decisión de qué hacer con la limpieza bloqueada (esperar checkout vs.
  forzar por incidente) es de operación y se queda en `docs/properties.md`.

## Affected specs

- `sdd/specs/celery-jobs.md` — el endpoint ya está descrito; se anota el consumidor nuevo.
- `sdd/specs/dashboard-api.md` — el dashboard ya carga las cards desde aquí; este change no
  añade endpoint.
- `sdd/specs/cleaning.md` — la acción de cancelar ya está; este change la consume desde una
  pantalla nueva.
- `sdd/specs/maintenance.md` — la acción de resolver ya está; este change la consume desde una
  pantalla nueva.
- `sdd/specs/frontend-foundation.md` — si la card crece con una sección propia, se documenta la
  decisión de layout.
- `docs/properties.md` — cómo se opera el aviso desde el lado de la propietaria/manager.
