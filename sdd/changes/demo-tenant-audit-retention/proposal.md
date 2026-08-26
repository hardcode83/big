# Proposal: demo-tenant-audit-retention

## Why

El `audit_logs` del tenant de demostración crece sin límite. El reset diario lo preserva por
requisito (R3.6 de `demo-user`, hoy en `sdd/specs/demo-tenant.md:113-117`), así que es la
**única** tabla de un tenant nightly-reset que nunca se reduce — y su par polimórfico
`entity_type`/`entity_id`, sin clave ajena, queda colgando en cuanto pasa el primer reset. Cada
ejecución añade además una fila de convergencia por cuenta. Es el seguimiento obvio del que
`demo-user` se excluyó a conciencia: lo dejó dicho en su design D4bis punto 3
(`sdd/changes/archive/2026-08-24-demo-user/design.md:171-178`) y lo registró como roadmap
candidate al archivar.

## What changes

Una regla de retención que purga las filas de `audit_logs` del tenant demo con `created_at`
anterior a 7 días, ejecutada como una nueva fase `purge-audit` del comando
`python -m app.cli.demo_reset`, **fuera** de la transacción del reset, entre `storage-sweep` y
`clear-lock`, reusando la sesión ya marcada al tenant demo. El periodo vive como constante del
módulo (`DEMO_AUDIT_RETENTION_DAYS = 7`), no en `Settings` ni en variable de entorno, igual que
las otras constantes del comando. La fase escribe su propia fila de auditoría antes del
borrado, y la regla se documenta en `docs/demo-tenant.md`. La spec `sdd/specs/demo-tenant.md`
se enmienda para que la preservación del `audit_logs` cite la retención.

## Requirements

### R1 — Retención de 7 días sobre el `audit_logs` del tenant demo

**As a** operador del entorno `dev` público, **I want** que el `audit_logs` del tenant de
demostración no crezca sin límite, **so that** la base no acumule filas históricas de un tenant
que se resetea a diario.

Acceptance criteria:

1. WHEN el purgado corre, THE SYSTEM SHALL borrar las filas de `audit_logs` cuyo `tenant_id`
   es el del tenant demo y cuyo `created_at` es estrictamente anterior al corte de 7 días,
   donde el corte es el `started_at` capturado por la fase `prepare` de la misma ejecución
   menos `INTERVAL '7 days'`.
2. THE SYSTEM SHALL declarar `DEMO_AUDIT_RETENTION_DAYS = 7` como constante del módulo
   `app/cli/demo_reset.py`, **no** en `Settings`, **no** en variable de entorno, **no** en
   base de datos, siguiendo el mismo patrón que `DEMO_TENANT_NAME` y `PASSWORD_MIN_LENGTH`.
3. THE SYSTEM SHALL ejecutar el `DELETE` sobre la sesión ya marcada al tenant demo
   (`require_session_bound_to`), sin abrir una segunda sesión ni saltarse el marcador.
4. THE SYSTEM SHALL aplicar la retención **únicamente** al tenant de demostración, y SHALL NOT
   extenderla a otros tenants: WHERE el `tenant_id` resuelto no es el del demo, THE SYSTEM
   SHALL rechazar la fase con código 2 sin escribir nada.

### R2 — Fase `purge-audit` del reset, fuera de la transacción

**As a** operador que ejecuta `make demo-reset`, **I want** que el purgado sea una fase del
comando, **so that** corra en el mismo flujo y no quede como trabajo manual.

Acceptance criteria:

1. THE SYSTEM SHALL añadir una fase `purge-audit` al `PHASES` de `app/cli/demo_reset.py`,
   en la posición **entre** `storage-sweep` y `clear-lock`.
2. THE SYSTEM SHALL ejecutar `purge-audit` **fuera** de la transacción del reset, igual que
   `storage-sweep` y `clear-lock`, recogiendo cualquier fallo como nota en vez de abortar la
   ejecución.
3. IF la fase `purge-audit` falla, THEN THE SYSTEM SHALL emitir la fase y la clase de la
   excepción en el informe (código 2 si falló dentro de fase, 0 si la transacción fue bien),
   y SHALL NOT emitir la contraseña, su hash, ningún token de sesión ni el detalle de un
   `SQLAlchemyError` (mismo contrato que las otras fases).
4. WHEN el reset termina con éxito, THE SYSTEM SHALL emitir en su informe el número de
   filas de `audit_logs` purgadas y el `cutoff` usado.

### R3 — Purgado auditable por sí mismo

**As a** auditor, **I want** que el purgado deje huella en `audit_logs` antes de borrar,
**so that** el borrado de filas históricas quede registrado aunque la propia fase falle.

Acceptance criteria:

1. THE SYSTEM SHALL escribir una fila de auditoría al **comienzo** de la fase `purge-audit`,
   con `entity_type='DEMO_AUDIT_PURGE'`, `action='PURGE'`, `tenant_id` del demo y
   `actor_user_id=NULL` (la sesión es del runner, no de una persona), pasando por
   `AuditLogFactory.build` + `ChangeSet` para que la regla 11 de `steering/security.md`
   siga cumpliéndose por construcción.
2. THE SYSTEM SHALL escribir esa fila **antes** del `DELETE`, de modo que sobreviva a un
   fallo del propio purgado.
3. THE SYSTEM SHALL NO auditar la fila dentro de la propia fase si la fase ya falló al
   intentar escribir la fila inicial: el error se reporta en el informe sin reentrar.

### R4 — Documentación de la regla

**As a** visitante del entorno demo y como operador que diagnostica incidentes, **I want**
saber que existe una retención y cuánto cubre, **so that** la ausencia de filas antiguas
no parezca un bug.

Acceptance criteria:

1. THE SYSTEM SHALL añadir una sección en `docs/demo-tenant.md` describiendo la retención:
   periodo (7 días), cuándo corre (durante el reset diario), qué se preserva (filas del
   último reset, por construcción del corte) y la única forma de ver el histórico (descarga
   directa de la fila antes del siguiente reset, **no** soportada por el producto).
2. THE SYSTEM SHALL enmendar `sdd/specs/demo-tenant.md` para que la sección «Qué borra y qué
   preserva» cite la retención al declarar la preservación de `audit_logs`, y SHALL añadir
   el requisito R-nuevo que la nombra como sección hermana, con el mismo formato EARS.

## Out of scope

- **Cambiar el modelo de `audit_logs`** (añadir FK a las entidades, normalizar
  `entity_type`/`entity_id`, o cualquier otra mudanza de esquema). Esto cierra la
  consecuencia del reset (filas que apuntan a nada) acotando el tiempo de vida, no
  resuelve la ausencia de FK — y moverla a este change lo agranda más allá de lo que el
  registro en el roadmap promete.
- **Una política general de retención para `audit_logs` de cualquier tenant.** El único
  tenant afectado es el de demostración, por construcción; extender la regla a otros
  requiere revisar primero qué consultas, paneles y obligaciones regulatorias dependen de
  la historia completa de cada uno (`revenue-statements`, `tech-incident-context`,
  `messaging-ai`, etc.).
- **Exponer el purgado como comando independiente o endpoint.** Corre dentro del reset y
  punto; nadie lo llama a mano. El `workflow_dispatch` del workflow existente
  (`gh workflow run demo-reset.yml --ref main`) cubre el disparo manual.
- **Una tarea de limpieza masiva para filas huérfanas pre-existentes.** El primer reset
  que ejecute esta fase ya las elimina: son más viejas que 7 días. No se hace nada aparte.
- **Cualquier cambio a la regla 11 de seguridad** (`audit_logs.changes` como estructurada).
  El purgado borra filas, no escribe en `changes`; la regla sigue cumpliéndose por
  construcción en R3.1.
- **Un knob de configuración** (`DEMO_AUDIT_RETENTION_DAYS` como env o `Settings`). La
  regla es una decisión de ingeniería, no de despliegue; sigue el patrón de las otras
  constantes del comando.

## Affected specs

- `sdd/specs/demo-tenant.md` — enmendar la sección «Qué borra y qué preserva» para que la
  preservación de `audit_logs` cite la retención, y añadir el requisito de la fase
  `purge-audit` como sección hermana con su EARS.
- `docs/demo-tenant.md` — añadir la sección de retención (R4.1).
