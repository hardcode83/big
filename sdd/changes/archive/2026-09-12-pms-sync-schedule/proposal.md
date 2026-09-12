# Proposal: pms-sync-schedule

## Why

`sdd/roadmap.md` entry `pms-sync-schedule` (hito "MVP operable" 3), con su nota en
`sdd/roadmap/pms-sync-schedule.md`. `steering/product.md` afirma que **el PMS es la fuente de
verdad de reservas**, pero eso es hoy cierto solo mientras alguien ejecuta
`python -m app.integrations.cli.pms_sync <tenant>` a mano — no hay ninguna entrada de beat que
lo dispare. `backend/app/scheduler/schedule.py` (`CADENCES`/`DAILY_JOBS`/`MONTHLY_JOBS`) no
contiene ningún sync de PMS; el único vecino es `process_webhook_events` cada 60 s, que
**re-lee lo que un aviso nombra**, no barre el portfolio. El propio router de webhooks nombra
el poll como camino de recuperación de avisos perdidos durante una rotación
(`integrations/api/router.py:153-156`) sin que nada lo programe, y Beds24 —cuyos webhooks no
van firmados y se configuran por propiedad desde su UI (ADR 0006)— "desaconseja el tiempo real
y recomienda sincronización completa cada ~6 horas". Sin barrido, un webhook perdido es una
reserva que no existe hasta el siguiente `pms_sync` a mano.

`celery-jobs` design D16 (2026-08-04) decidió explícitamente NO programar este sync — pero no
porque el coste no estuviera medido: su propio texto dice "la cadencia sí está medida —8
créditos por ciclo, techo de un sync cada 24 s, recomendación del proveedor ~6 h— pero está
medida **contra Beds24, cuyo adapter no existe**." El único bloqueo real era el adapter: sin él,
el único selector de proveedor era un flag de operador con `mock` por defecto, y programar un
sync periódico contra el mock no habría verificado nada mientras metía en la aplicación una
configuración de proveedor que `pms_sync.py:54-66` evita a propósito para no resucitar el
`PMS_PROVIDER` global que ADR 0006 retiró. D16 dejó el job explícitamente para cuando llegara
`pms-beds24-adapter`, dueño de la `PMSAdapterFactory` — y esa change ya cerró: la factory
resuelve un adapter real por propiedad. `sdd/specs/celery-jobs.md`'s "Estado y deuda conocida"
sigue diciendo "su adapter no existe", lo que ya es falso y se corrige al archivar. (El consumo
de crédito *real*, a diferencia de la cadencia teórica que D16 ya midió, sigue sin
instrumentar — eso es un asunto aparte, hacia delante, de `beds24-webhook-cutover-measurement`,
no la razón por la que D16 aplazó el job.) El argumento de D16 nunca aplicó a `MockPMSAdapter`
ni a `ChannexAdapter` (staging), que son los proveedores con los que el MVP opera hasta la
ventana de corte.

## What changes

Un job periódico `sync_pms_reservations` se une al calendario de `celery-jobs` (`CADENCES`,
cada 6 h — la cadencia que Beds24 mismo recomienda), recorre los tenants `ACTIVE` con la
misma forma que los seis jobs de reloj ya existentes (`run_for_every_tenant`, candado de
`scheduler/locks.py`, sesión marcada por tenant y nunca re-marcada), y para cada uno llama a
`SyncReservationsFromPmsUseCase.execute(...)` — el mismo caso de uso que ya usan el CLI y el
recorte de webhooks, sin una segunda implementación. La ventana de barrido (`since`) es un
`Settings` nuevo, `pms_sync_window_days` (default 2 días: suficiente margen sobre la cadencia
de 6 h para tolerar una ejecución perdida sin re-barrer el mes entero). Se añade `make pms-sync`
como disparo manual equivalente al CLI ya existente, y un tercer `source` (`"pms_scheduled"`)
para que el `TimelineEvent` de una reserva distinga "llegó por el barrido periódico" de "llegó
por un webhook" o "por un `pms_sync` manual" — la misma distinción que ya separa `PMS_SOURCE`
de `WEBHOOK_SOURCE`.

## Requirements

### R1 — El sync periódico entra en el calendario de beat

**As a** propietario del sistema, **I want** que el barrido de reservas del PMS ocurra solo
por el reloj, **so that** una reserva o cancelación que el proveedor no notificó por webhook
no dependa de que alguien recuerde ejecutar el CLI.

Acceptance criteria:

1. WHEN el worker de beat arranca, THE SYSTEM SHALL incluir `sync_pms_reservations` en
   `beat_schedule()` con cadencia de 6 horas, registrada en `CADENCES`
   (`backend/app/scheduler/schedule.py`) exactamente como los demás jobs periódicos — un
   `timedelta` literal, no derivado de `Settings`, porque `test_schedule.py` transcribe el
   calendario contra el PRD y sus divergencias declaradas y ningún otro job del calendario lee
   su cadencia de configuración.
2. WHEN `sync_pms_reservations` dispara, THE SYSTEM SHALL ejecutarlo para cada tenant
   `ACTIVE` (incluidos los que solo tienen propiedades `MOCK`) con la misma sesión marcada por
   tenant, nunca re-marcada, que ya usan `check_checkin_windows` y el resto (`run_for_every_tenant`
   / `run_in_marked_session`).
3. WHEN dos procesos de beat están vivos a la vez (redeploy), THE SYSTEM SHALL tomar el mismo
   candado mutex de `scheduler/locks.py` que los demás jobs periódicos, con TTL derivado de la
   cadencia (`lock_ttl_for`, 3× = 18 h), e informar `skipped_locked` en vez de fallar cuando no
   lo consigue.
4. WHEN un tenant falla (proveedor caído, credencial rota), THE SYSTEM SHALL continuar con el
   resto de tenants y con el resto de proveedores de ESE tenant — el mismo aislamiento de fallos
   que `_sync_one_provider` ya garantiza por proveedor y `run_for_every_tenant` por tenant — sin
   que el fallo de un tenant marque a los demás como `skipped_locked` ni interrumpa el resto del
   ciclo.

### R2 — La ventana de barrido es configurable, no fija a 30 días

**As a** operador, **I want** que el barrido periódico use una ventana corta y ajustable, **so
that** cada ciclo de 6 horas no re-pida un mes de reservas por propiedad y gaste crédito de
Beds24 sin necesidad.

Acceptance criteria:

1. WHEN se ejecuta `sync_pms_reservations`, THE SYSTEM SHALL calcular `since` como
   `now - timedelta(days=settings.pms_sync_window_days)`, con `pms_sync_window_days: int = 2`
   por defecto — distinto de `DEFAULT_WINDOW_DAYS = 30` del CLI manual, que sigue existiendo
   sin cambios para el barrido bajo demanda.
2. IF se cambia `pms_sync_window_days` en `Settings`, THEN THE SYSTEM SHALL usar el nuevo valor
   en el siguiente ciclo sin requerir cambios de código.

### R3 — Atribución distinguible del origen del sync

**As a** alguien que lee el timeline de una reserva, **I want** distinguir si llegó por el
barrido periódico, por un webhook o por un `pms_sync` manual, **so that** la pregunta "¿por qué
cambió esto ahora?" tenga una respuesta distinta de "el proveedor avisó algo".

Acceptance criteria:

1. WHEN `sync_pms_reservations` importa o actualiza una reserva, THE SYSTEM SHALL registrar su
   `TimelineEvent` con un tercer valor de `source` (`"pms_scheduled"`), distinto de
   `PMS_SOURCE` (`"pms"`, CLI manual) y `WEBHOOK_SOURCE` — nunca reutilizando `PMS_SOURCE`, por
   la misma razón por la que `WEBHOOK_SOURCE` no lo reutiliza.
2. WHEN se ejecuta con este origen, THE SYSTEM SHALL mantener `actor_type=SYSTEM` (el valor por
   defecto de `SyncReservationsFromPmsUseCase.execute`), consistente con lo que su propio
   docstring ya declara (design D15: "a command or, later, Celery beat runs this, and there is
   no person to attribute it to") — nunca `TimelineActorType.SCHEDULER`, que otros casos de uso
   sí usan pero que este no adoptó cuando se escribió.

### R4 — Disparo manual equivalente al CLI

**As a** operador, **I want** un `make pms-sync` que ejecute el mismo barrido sin abrir una
shell dentro del contenedor, **so that** verificar o forzar un ciclo sea tan simple como
`make sim-advance`.

Acceptance criteria:

1. WHEN se ejecuta `make pms-sync TENANT=<uuid>`, THE SYSTEM SHALL invocar
   `python -m app.integrations.cli.pms_sync <uuid>` dentro del contenedor `backend`, con los
   mismos argumentos opcionales `WINDOW` y `PROVIDER` que ya acepta el CLI — sin duplicar su
   lógica, exactamente como `make sim-advance` invoca `app.cli.sim_advance`.

### R5 — Aislamiento entre tenants durante el barrido

**As a** tenant, **I want** que el barrido periódico de otro tenant nunca toque mis reservas,
**so that** la regla 1 de `steering/security.md` se cumpla también en el único camino que no
pasa por una petición HTTP.

Acceptance criteria:

1. WHEN el barrido procesa dos tenants con propiedades `MOCK` en el mismo ciclo, THE SYSTEM
   SHALL dejar en cada uno únicamente las filas resueltas para ese `tenant_id` — la garantía que
   ya prueban los tests de `test_locks.py`/`test_runner.py` para los demás jobs, extendida a
   este.

## Out of scope

- **ARI** (`update_price`, `block_dates`, `get_availability`): no están en el puerto
  `PMSAdapter`; sin cambios.
- **Mensajería OTA**: pertenece a `beds24-messaging-adapter`.
- **Ruta HTTP de sync manual**: PRD §23 no la define; el disparo bajo demanda sigue siendo el
  CLI (R4), nunca un endpoint.
- **Reactivar la cuenta de Beds24**: fuera de este change por completo.
- **Credenciales por propiedad**: `_sync_one_provider` ya se niega a servirlas en un sync
  agrupado (ver `BLOCKED.md` de `pms-provider-resolution`) — el job hereda esa negativa sin
  intentar resolverla; hoy no muerde porque Beds24 es `ACCOUNT`-scoped.
- **Un `TimelineEvent` por reserva modificada/cancelada vía PMS que hoy no existe**: gap
  conocido que pasa de teórico a diario con este change; lo cierra la siguiente entrada del
  roadmap, `pms-ingest-change-events` (`needs: pms-sync-schedule`).
- **Bajar la cadencia según el crédito real de Beds24**: el gancho queda para cuando
  `beds24-webhook-cutover-measurement` mida `X-RequestCost`; hasta entonces, 6 h fijas.

## Affected specs

- `sdd/specs/celery-jobs.md` — nuevo `THE SYSTEM SHALL` para `sync_pms_reservations` en la
  sección "El calendario y su despliegue", y corrección de "Estado y deuda extraída" (la línea
  "No hay sync periódico del PMS... su adapter no existe" queda falsa dos veces: el adapter
  existe desde `pms-beds24-adapter` y este change añade justamente el sync que anunciaba).
- `sdd/specs/reservations.md` — sección "Sincronización con el PMS": añadir que el mismo caso
  de uso tiene ahora tres disparadores (CLI manual, webhook, beat) en vez de solo el CLI y el
  webhook.
