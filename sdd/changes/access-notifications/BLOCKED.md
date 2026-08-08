# BLOCKED — access-notifications

Preguntas abiertas del diseño y lo que quedó sin correr en `/sdd:run`. **Nada bloquea la
implementación**: las cuatro OQ llevan un default tomado, y aquí queda registrado cuál para que
revertirlo sea barato. Se resuelven con Jose antes de `/sdd:ship`.

## OQ1 — ¿La API de lectura in-app entra en este change?

- **phase**: design
- **type**: decision
- **qué y por qué**: `design.md` D5 marca `SENT` las notificaciones `IN_APP` porque «la fila es la
  entrega». Eso solo es cierto si algo puede leerla, y no existía endpoint. D6 mete
  `GET /api/v1/notifications` en el alcance; el proposal no lo enumeraba.
- **default tomado**: implementado. Revertir = borrar `backend/app/notifications/api/`,
  `ListOwnNotificationsUseCase`, `list_for_recipient` y el permiso `READ_OWN_NOTIFICATIONS`.
- **resume**: `/sdd:review access-notifications`

## OQ2 — «Marcar como leída» exige una columna que el PRD no declara

- **phase**: design
- **type**: decision
- **qué y por qué**: `notification_logs` no tiene `read_at` y PRD §7.24 no la declara. Sin ella el
  ciclo in-app queda a medias (se listan, no se acusan). Añadirla es una migración pequeña pero
  inventa esquema fuera del PRD.
- **default tomado**: no se añade; no hay `POST /notifications/{id}/read`.
- **resume**: `/sdd:review access-notifications`

## OQ3 — Avalancha de escalados en el primer tick tras desplegar — **MEDIDO**

- **phase**: run
- **type**: decision
- **qué y por qué**: al marcar `SENT` por primera vez, las filas `CLEANING_TASK_ASSIGNED` cuyo
  plazo ya venció pasan a ser candidatas y `check_sla_breaches` las escala todas de golpe.
- **medición (tarea 9.6, 2026-08-08)**: reproducido en el stack del worktree con 7 filas de plazo
  vencido. Antes del emisor: **0 candidatas**. Tras un `dispatch_notifications`: **7 entregadas y
  7 candidatas**, y `check_sla_breaches` reportó `breached=7`. Es decir, **la relación es 1:1**:
  se escalará exactamente una vez cada asignación pendiente con plazo vencido que exista en la
  base de datos al desplegar.
  - El número real de dev/producción **no se puede medir desde aquí**: el worktree arranca con
    base vacía (`sdd/project.md`, «Worktree bootstrap»). Lo que se sabe es la fórmula, no el
    total. Consultarlo antes de desplegar es un `SELECT count(*) FROM notification_logs WHERE
    notification_type = 'CLEANING_TASK_ASSIGNED' AND status = 'PENDING' AND sla_deadline_at <
    now()`.
- **default tomado**: se acepta. Son incumplimientos reales y ocultarlos con un filtro sería
  mentir sobre el pasado.
- **resume**: `/sdd:review access-notifications`

## OQ4 — `EXPIRED` sin nadie que rellene `valid_to`

- **phase**: design
- **type**: decision
- **qué y por qué**: la transición a `EXPIRED` depende de `valid_to`, que hoy no rellena nadie (lo
  haría un proveedor real de accesos). Implementarla deja código sin ejercitar en producción; no
  implementarla deja un valor del enum sin camino.
- **default tomado**: implementada, con test propio y con
  `test_expirable_finds_nothing_because_nothing_writes_valid_to` fijando la ausencia — ese test
  empezará a fallar, útilmente, el día que un proveedor empiece a rellenar la columna.
- **resume**: `/sdd:review access-notifications`

## OQ5 — ¿`access_records.notes` entra en la tabla de sumideros de la regla 11?

- **phase**: review
- **type**: decision (requiere tocar `sdd/steering/security.md`, así que es de Jose)
- **qué y por qué**: el panel de seguridad a escala de feature encontró que `notes` es texto
  libre que viaja **en el mismo formulario** que el código de acceso, se persistía verbatim y se
  devolvía en cada listado a todo el que tenga `READ_ACCESS_RECORDS`. La capa de auditoría ya lo
  trataba como peligroso (`redacted()`), pero la columna y la respuesta no.
- **arreglado en este change, y hasta dónde llega**: `AccessRecord.register_manual_code` ahora
  rechaza la petición si `notes` contiene el código que se está registrando — es el único punto
  del sistema donde ambas cadenas coexisten, así que es el único donde la comprobación es
  decidible. Cierra el escenario concreto («puerta 481523, timbre 2»). **No cierra el caso
  general**: nada impide escribir *otro* código en `notes` más tarde.
- **la decisión que queda**: la tabla de la regla 11 enumera seis columnas y `access_records.notes`
  no es una de ellas. Meterla es ampliar el contrato de un sumidero, y la propia regla dice cómo:
  «con una entrada nueva y nombrada aquí, aprobada en el design del change que la pida». Este
  change no la pide porque no la necesita para cumplir R2.6; el siguiente que amplíe la superficie
  de `notes` —`field-apps`, cuando la limpiadora vea accesos— sí debería.
- **resume**: decidir con Jose; si es que sí, sale como entrada propia de roadmap.
