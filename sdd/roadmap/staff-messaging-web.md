# staff-messaging-web

[FE] **el hilo del personal en las tres pantallas donde ya se trabaja**: `/cleaner/tasks/[id]`,
`/tech/incidents/[id]` y la vista del manager sobre la tarea o la incidencia.

Es la mitad de frontend de `staff-messaging` y va separada por el mismo criterio que partió `field-apps` en
cuatro el 2026-08-18 y `cleaner-app` en tres: la superficie móvil de dos roles nuevos no cabe en el mismo
change que estrena entidad, rutas y permisos en el backend.

**Depende de que existan las pantallas, no solo la API**: `cleaner-app` y `tech-app` son las que estrenan
`/cleaner/tasks/[id]` y `/tech/incidents/[id]` como páginas reales — hoy el andamio de `tech` está puesto
(`frontend/app/(field)/tech/` con `TechnicianShell` y `AuthGuard`) y las dos páginas son `RoutePlaceholder`.
Colgar el hilo de un placeholder no es implementable, así que esta entrada va detrás de las dos.

**Lo que decide**: si el hilo es una pestaña o una sección de la página de detalle (mobile-first, y en un
móvil una pestaña más es un salto de contexto en mitad de una limpieza); cómo se distingue visualmente el
mensaje del manager del propio; y qué se hace mientras no hay mensajes, que es el estado normal y no un
vacío de error. i18n ES/EN en `locales/es` y `locales/en`, sin cadenas incrustadas, por
`steering/frontend.md`.
