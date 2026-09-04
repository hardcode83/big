# guest-link-delivery

[BE+FE] **el portal del huésped está entero y nadie le da el enlace**.

> Hito «MVP operable» 2 — *el huésped real* (auditoría del 2026-09-04).

**El hecho medido (2026-09-04)**: `/guest/[token]` está completo —información de la estancia,
check-in con documentos, reportar incidencia, hilo de mensajes con respuesta de IA y escalación
(`guests/api/portal_router.py:203`, :267, :314, :366, :423)—. Emitir y revocar el token existen
(`backend/app/guests/api/router.py:151`, :184), están en manos de owner y manager
(`_GUEST_ACCESS_TOKEN_MANAGE`, `policy.py`), y **sólo `frontend/lib/api/generated/openapi.d.ts:884-894`
los conoce**: ninguna feature los llama. La única emisión en claro de todo el árbol es el
`stdout` de `backend/app/cli/demo_reset.py:1322-1323`, documentada en `docs/demo-tenant.md:79-86`.
`make seed-demo` no emite ninguno a propósito, porque emitir revoca el vivo
(`docs/seed-demo.md:74-79`). Y **ninguna fila de `notification_logs` tiene hoy como destinatario
a un huésped** (medido por `guest-scheduled-comms` el 2026-08-28 y vigente).

**Por qué no es cosmético**: es la superficie con más trabajo entregado por rol y la única que un
usuario real no puede alcanzar. Sin enlace no hay check-in online, no hay incidencia del huésped
y no hay conversación por portal —que es el único canal de mensajería que funciona hoy de
extremo a extremo sin credenciales externas—.

**Alcance**:

- **[FE]** en `/reservations/[id]`: emitir el enlace, mostrarlo copiable **una sola vez** (mismo
  patrón que la contraseña temporal de `features/platform/components/temporary-password-reveal.tsx`,
  con `Cache-Control: no-store` del lado del servidor si el contrato lo permite), revocar, y ver
  si hay uno vivo y desde cuándo. Gateado por permiso.
- **[BE]** un escritor de notificación con destinatario **huésped** —el primero— que envíe el
  enlace al `Guest.email` por el SMTP de `smtp-delivery-adapter`, disparado desde la emisión (o
  como acción separada «enviar»); idioma resuelto como `messaging/domain/language.py` ya hace,
  porque un `Guest` no tiene `preferred_language` de usuario.

**Lo que decide y no es cosmético**:

1. **Frontera con `guest-scheduled-comms`**, y es lo que hace posible que esta entrada sea S:
   aquí viaja **sólo el enlace del portal**. Las instrucciones de acceso, el código de la
   cerradura y los recordatorios 24 h/2 h son de aquella entrada, que es la que tiene que
   resolver la forma enmascarada de la regla 11 para un código de acceso en `subject`/`body`. El
   enlace del portal no es un valor de la regla 3: es una URL con un token opaco que `guest-portal-api`
   ya define como credencial de la estancia (token, hash en BD, revocable, acotado por
   estancia/tenant). El design cita ese spec y **no** amplía el censo.
2. **El token en el `body` de `notification_logs`.** La regla 11 dice que los cuerpos llevan ids
   y un tipo. Un email con el enlace necesita el enlace. Opciones: (a) el `body` guarda una
   referencia y el adapter compone la URL al enviar, sin persistirla; (b) se persiste y se
   declara fila en el censo con la mitigación que corresponda. Recomendación: (a), que es la
   misma forma que ADR 0006 exige para el código de puerta («se persiste una referencia, nunca
   el valor renderizado»).
3. **Quién decide el canal.** `notification-channel-routing` resuelve por conmutadores del tenant
   para usuarios; para un huésped el canal es el que tenga contacto —email hoy; WhatsApp sólo
   dentro de las 24 h o con plantilla, que no hay—. El MVP envía por email y muestra el enlace
   copiable para pegarlo a mano en WhatsApp/Airbnb: eso es lo que hará el operador real.
4. **Cuándo se emite**: al confirmar la reserva, a mano, o en `provision_access_records`
   (cada 5 min, `scheduler/schedule.py:57`), que ya toca cada reserva confirmada sin `AccessRecord`.
   Recomendación MVP: a mano desde el detalle; automático es `guest-scheduled-comms`.

**Fuera de alcance**: recordatorios, instrucciones de acceso, código de puerta; SES.Hospedajes
(`guests/api/router.py:216`, sin pantalla — candidata aparte); mostrar en el detalle lo que el
huésped hizo en el portal (check-in completado, documentos) si no está ya.

**Verificación**: emitir desde `/reservations/[id]`, recibir el email (SMTP de dev o
`ConsoleEmailAdapter` en local), abrir el enlace en un móvil, enviar un mensaje, leer la
respuesta de la IA, y que el manager la vea en `/conversations`.
