# notifications-inbox-web

[FE] **la bandeja in-app, que es la única entrega real que el producto tiene hoy y no la lee nadie**.

**El hecho medido (2026-08-28)**: `GET /api/v1/notifications` existe desde `access-notifications`
(`backend/app/notifications/api/router.py`, una sola ruta) y **cero ficheros del frontend la llaman** —
un barrido de `frontend/**/*.{ts,tsx}` por `notification` devuelve tres coincidencias y ninguna es una
llamada: `features/dashboard/lib/timeline-event-types.ts`, `features/cleaning/components/assign-cleaner-control.tsx`
y el `openapi.d.ts` generado.

**Por qué eso no es cosmético, y es el argumento entero de la entrada**: `InAppNotificationAdapter`
declara por escrito que «the row **is** the delivery», y deja escrita también su condición de verdad
(`backend/app/notifications/infrastructure/adapters.py`): *"it is only true because that endpoint
exists (design D6). If the endpoint ever goes away, this adapter is a lie and must go with it."*
La ruta existe, pero **ningún humano puede llegar a ella**, así que la afirmación es verdadera en el
contrato y falsa en el producto. Ocho de los diez escritores de notificaciones del backend fijan
`channel=NotificationChannel.IN_APP` a pelo, de modo que **toda** la comunicación interna del sistema
—limpieza asignada, técnico asignado, incidencia rechazada, aprobación del propietario, escalación de
huésped, registro policial fallido, incumplimiento de SLA— termina hoy en filas que solo se leen con SQL.

**Alcance**: la campana con contador de no leídos y una superficie de listado, en las **tres** shells,
porque los tres roles tienen `READ_OWN_NOTIFICATIONS` en `ROLE_PERMISSIONS` y ninguno tiene dónde mirar:
el workspace del manager/owner, `CleanerShell` y `TechnicianShell`. La ruta está paginada
(`page`/`per_page`, tope 100) y acotada por token — no hay parámetro que ensanche el destinatario —,
así que no hace falta backend nuevo.

**Lo que decide y no es cosmético**: (1) **no hay «marcar como leído»** y no es un olvido — necesita una
columna `read_at` que PRD §7.24 no declara, y el design D6 de `access-notifications` decidió no inventarla,
dejándolo como OQ2 de su `BLOCKED.md`; esta entrada es la que tiene el consumidor delante, así que le toca
resolverlo o declarar explícitamente que el contador es «totales» y no «no leídos». (2) **Polling y no SSE**:
la decisión ya está tomada en el docstring de la ruta y conviene heredarla, pero la cadencia del cliente es
nueva — y `dispatch_notifications` corre cada minuto (`scheduler/schedule.py`), así que pedir más a menudo
no compra nada. (3) `subject`/`body` de esas filas llevan ids y un tipo, nunca contenido de otra fila
(regla 11 de `steering/security.md`), así que la pantalla tiene que **renderizar** el `notification_type`
a texto i18n ES/EN y no limitarse a pintar el `body`, que está escrito en inglés y para un operador.

**Por qué va primera de todo el bloque de comunicación**: es la única de las nueve que no necesita ni un
proveedor externo, ni una decisión de dominio, ni una migración — y sin ella no hay forma de **observar**
que ninguna de las otras ocho funciona.
