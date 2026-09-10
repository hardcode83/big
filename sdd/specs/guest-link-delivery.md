# El enlace del portal del huésped, desde el detalle de la reserva

## Purpose

El portal del huésped (`/guest/[token]`) estaba completo desde `guest-portal-api` y
`guest-portal-messaging` — estancia, check-in, incidencia, mensajería con IA — pero nadie podía
alcanzarlo: emitir y revocar el token existían solo como rutas de operador sin pantalla, y
ninguna fila de `notification_logs` tenía nunca como destinatario a un huésped. Esta capacidad
cierra ese hueco desde `/reservations/[id]`: ver si hay un enlace vivo y desde cuándo, emitirlo
y copiarlo una sola vez, revocarlo, y disparar su entrega por email al `Guest.email` de la
reserva.

El contrato de las cuatro rutas backend (`GET`/`POST`/`DELETE`/`POST .../send`) vive en
[`guest-portal-api.md`](guest-portal-api.md); esta capacidad cubre solo la pantalla que las
consume y el escritor de notificación que la ruta `send` dispara (censado en
[`access-notifications.md`](access-notifications.md)). No amplía el token, su ventana de
vigencia ni su hashing.

## Requirements

### Ver el estado del enlace sin acuñar uno

- WHEN un operador con `MANAGE_GUEST_ACCESS_TOKENS` abre `/reservations/[id]`, THE SYSTEM SHALL
  mostrar si la reserva tiene actualmente un enlace de portal vivo y, si lo tiene, desde cuándo
  se emitió — sin exponer el valor del token en ningún momento.
- THE SYSTEM SHALL consultar el estado mediante `GET
  /api/v1/reservations/{reservation_id}/guest-access-token` y NEVER SHALL derivar la presencia
  de un enlace vivo de emitir uno nuevo.
- IF el usuario autenticado no tiene `MANAGE_GUEST_ACCESS_TOKENS`, THEN THE SYSTEM SHALL no
  renderizar ningún control de emitir, copiar, revocar ni enviar, y NEVER SHALL emitir la
  consulta de estado. El backend decide el permiso; el frontend solo lo oculta
  (`steering/frontend.md`).

### Emitir y copiar, una sola vez

- WHEN el operador acuña el enlace, THE SYSTEM SHALL mostrar el valor devuelto en un control de
  copiar-al-portapapeles marcado como mostrado una sola vez, y NEVER SHALL volver a mostrarlo
  tras desmontar el componente o abandonar y volver a la pantalla — mismo patrón que
  `features/platform/components/temporary-password-reveal.tsx` usa para la contraseña temporal.
  El valor vive solo en el estado transitorio de la mutación (`gcTime: 0`); ningún
  `localStorage`, cadena de consulta ni historial de navegación lo retiene.
- WHEN el operador revoca el enlace, THE SYSTEM SHALL actualizar el estado visible a "sin enlace
  vivo" sin recargar la página.
- WHILE una mutación de emitir, revocar o enviar está en curso, THE SYSTEM SHALL deshabilitar el
  control que la disparó, para impedir un envío duplicado.

### Enviar el enlace por email

- WHEN el operador dispara "enviar", THE SYSTEM SHALL invocar `POST
  /api/v1/reservations/{reservation_id}/guest-access-token/send`, que acuña un enlace nuevo
  (revocando el vivo, igual que el `POST` simple) y lo entrega por email al huésped en la misma
  petición — ver [`guest-portal-api.md`](guest-portal-api.md) para el contrato completo de esa
  ruta y [`access-notifications.md`](access-notifications.md) para la fila de
  `notification_logs` que escribe.
- THE SYSTEM SHALL mostrar `delivered: true`/`false` como retroalimentación en línea, distinta
  de un rechazo: `delivered: false` (`200`) significa "se acuñó el enlace, no llegó el correo"
  y no revierte la emisión; un `422` (sin `Guest` enlazado o sin email) sí es un rechazo y no
  acuña nada.
- THE SYSTEM NEVER SHALL mostrar el valor en claro del token tras un envío: esa acción entrega
  el enlace al huésped, no al operador, que no tiene por qué ver una segunda copia en su propio
  navegador — ese es el papel de "emitir y copiar", una acción distinta.
- WHEN el envío resuelve (con o sin éxito de entrega), THE SYSTEM SHALL invalidar la consulta de
  estado: un envío acuña un enlace nuevo, así que "desde cuándo" cambia también.

## Out of scope

- Instrucciones de acceso, código de puerta y recordatorios 24h/2h — `guest-scheduled-comms`.
- Emisión automática al confirmar la reserva o desde un barrido — decisión de
  `guest-scheduled-comms`; el MVP es manual desde esta pantalla.
- Envío por WhatsApp — el MVP entrega por email y muestra el enlace copiable para pegarlo a
  mano en otro canal.
- Cualquier cambio al ciclo de vida, hash o límites del token — se consume el contrato existente
  de `guest-portal-api.md` tal cual.

## Key files

- `frontend/features/reservations/components/detail/guest-portal-link-card.tsx` — el
  componente, gateado por `useHasPermission(Permission.MANAGE_GUEST_ACCESS_TOKENS)`.
- `frontend/features/reservations/hooks/use-guest-access-token.ts` — `useGuestAccessTokenStatus`,
  `useIssueGuestAccessToken`, `useRevokeGuestAccessToken`, `useSendGuestAccessTokenEmail`.
- `frontend/features/reservations/data/{dto.ts,http/http-reservations-source.ts}` — las cuatro
  operaciones tipadas contra el contrato generado.
- `frontend/features/reservations/components/detail/reservation-detail-sections.tsx`,
  `reservation-detail-view.tsx` — la sección `guestPortalLink`, renderizada tras la de huésped.
- `frontend/lib/auth/permissions.ts` — `MANAGE_GUEST_ACCESS_TOKENS`, espejo de
  `_GUEST_ACCESS_TOKEN_MANAGE` del backend (`TENANT_OWNER`, `PROPERTY_MANAGER`).
- `frontend/locales/{es,en}/reservations.json` — las claves `guestPortalLink.*`.
- `backend/app/guests/application/portal.py` — `GetGuestAccessTokenStatusUseCase`,
  `SendGuestAccessTokenUseCase` (documentados en detalle en `guest-portal-api.md`).
