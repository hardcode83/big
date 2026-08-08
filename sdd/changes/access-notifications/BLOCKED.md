# BLOCKED — access-notifications

Preguntas abiertas del diseño. **Ninguna bloquea la implementación**: cada una lleva un default
tomado para que `/sdd:run` pueda avanzar, y aquí queda registrado cuál, para que revertirlo sea
barato. Se resuelven con Jose antes de `/sdd:ship`.

## OQ1 — ¿La API de lectura in-app entra en este change?

- **phase**: design
- **type**: decision
- **qué y por qué**: `design.md` D5 marca `SENT` las notificaciones `IN_APP` porque «la fila es la
  entrega». Eso solo es cierto si algo puede leerla, y hoy no existe endpoint. D6 mete
  `GET /api/v1/notifications` en el alcance; el proposal no lo enumeraba.
- **default tomado**: se implementa. Revertir = borrar `notifications/api/` y
  `ListOwnNotificationsUseCase`.
- **resume**: `/sdd:review access-notifications`

## OQ2 — «Marcar como leída» exige una columna que el PRD no declara

- **phase**: design
- **type**: decision
- **qué y por qué**: `notification_logs` no tiene `read_at` y PRD §7.24 no la declara. Sin ella el
  ciclo in-app queda a medias (se listan, no se acusan). Añadirla es una migración pequeña pero
  inventa esquema fuera del PRD.
- **default tomado**: no se añade; no hay `POST /notifications/{id}/read`.
- **resume**: `/sdd:review access-notifications`

## OQ3 — Avalancha de escalados en el primer tick tras desplegar

- **phase**: design
- **type**: decision
- **qué y por qué**: al marcar `SENT` por primera vez, las filas `CLEANING_TASK_ASSIGNED` cuyo
  plazo ya venció pasan a ser candidatas y `check_sla_breaches` las escala todas de golpe. Son
  incumplimientos reales, pero el volumen puede molestar.
- **default tomado**: se acepta. Se mide en `/sdd:run` contra los datos de dev y se anota el número.
- **resume**: `/sdd:review access-notifications`

## OQ4 — `EXPIRED` sin nadie que rellene `valid_to`

- **phase**: design
- **type**: decision
- **qué y por qué**: la transición a `EXPIRED` de `AccessRecord` depende de `valid_to`, que hoy no
  rellena nadie (lo haría un proveedor real de accesos). Implementarla deja código sin ejercitar en
  producción; no implementarla deja un valor del enum sin camino.
- **default tomado**: se implementa con test propio.
- **resume**: `/sdd:review access-notifications`
