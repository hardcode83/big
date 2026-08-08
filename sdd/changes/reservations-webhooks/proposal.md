# Proposal: reservations-webhooks

## Why

`reservations` entregó tres de los cuatro ítems de PRD §16 —CRUD, `MockPMSAdapter` e import CSV— y dejó
fuera el cuarto, la **recepción de webhooks del PMS**, porque sus dos dependencias duras no existían:
la entidad `WebhookEvent` (PRD §7.26), que pertenece a `domain-foundation-financial`, y el job Celery
`process_webhook_events`, que pertenece a `celery-jobs`. Implementar una recepción que no persistiera lo
que el PRD exige persistir habría sido peor que no tenerla. Las dos dependencias están cerradas
(`changes/archive/2026-08-05-celery-jobs/`, `webhook_events` ya en el esquema), así que la entrada está
en la frontera del roadmap.

Sin esta capacidad, la única vía de entrada de reservas desde el PMS es el sondeo (`pms_sync <tenant>`),
que llega tarde y consume cuota: el techo medido en `specs/pms-beds24-spike.md` es un sync cada 30 s por
cuenta contra 100 créditos / 5 min. El webhook es el aviso que permite re-leer *cuando pasa algo*.

Fuentes que gobiernan este change, y que lo desvían del enunciado literal del PRD:

- Entrada de roadmap y su nota: `sdd/roadmap/reservations-webhooks.md`.
- [ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md) — **ninguno de los once proveedores
  evaluados firma sus webhooks**. PRD §16 dice "valida firma HMAC si el provider lo soporta"; la condición
  es falsa para todos, así que la rama condicional nunca se ejecuta y lo que aplica es el caso sin firma.
  El ADR registra además la **cuarta desviación del PRD**: la ruta de PRD §23 lleva un segmento token.
- `sdd/steering/security.md` **regla 12** (webhooks entrantes sin firma) y **regla 13** (datos de titular
  de tarjeta), que esta entrada hereda por nombre propio. La 13 se declara de aplicación **en diseño**.

## What changes

Después de este change, un PMS puede avisarnos y ese aviso se convierte en reservas actualizadas sin que
nadie sondee: existirá un endpoint de recepción en una **ruta no adivinable por tenant**
(`POST /api/v1/webhooks/{provider}/{webhook_token}`, no la forma global de PRD §23), autenticado por una
**cabecera estática cuyo valor es distinto por tenant** y comparado en tiempo constante, con límite de
tasa y tope de cuerpo. Lo que acepta se persiste como `WebhookEvent` con `processed=FALSE` —después de
**descartar los datos de tarjeta en la frontera**— y lo procesa el job Celery `process_webhook_events`
con 3 reintentos y backoff exponencial, alimentando el `ReservationIngestor` que `reservations` ya dejó
como única ruta de upsert e idempotente por `(tenant_id, external_pms_id)`. La re-lectura por API que el
aviso dispara va **encolada y coalescida**, nunca una llamada saliente por webhook recibido.

Se aprovisiona además el material que la autenticación necesita: token de ruta y secreto de cabecera por
tenant, generados en el alta, rotables y auditados.

## Requirements

### R1 — Recepción autenticada en una ruta no adivinable

**Como** integrador del PMS, **quiero** que el aviso del proveedor entre por un endpoint que solo mi
tenant conoce y que rechace a cualquier otro, **para que** una escritura anónima desde internet no pueda
insertar eventos ni amplificar consumo de cuota.

Criterios de aceptación:

1. WHEN se solicita `POST /api/v1/webhooks/{provider}/{webhook_token}` con un `webhook_token` que
   corresponde a un tenant y la cabecera estática del proveedor con el valor de ese tenant, THE SYSTEM
   SHALL persistir un `WebhookEvent` con `processed=FALSE`, `provider`, `event_type`, `received_at` y el
   `tenant_id` resuelto, y responder `202` sin cuerpo de negocio.
2. IF el `webhook_token` no corresponde a ningún tenant, THEN THE SYSTEM SHALL responder `404` sin
   escribir nada y sin revelar si el `{provider}` existe.
3. IF la cabecera estática falta o su valor no coincide con el del tenant resuelto, THEN THE SYSTEM SHALL
   responder `404` —la misma respuesta que un token desconocido— sin escribir nada.
4. THE SYSTEM SHALL comparar el valor de la cabecera en **tiempo constante**, y no SHALL usar comparación
   de cortocircuito.
5. THE SYSTEM SHALL usar un `webhook_token` opaco, generado con un CSPRNG y con al menos 128 bits de
   entropía, y no SHALL derivarlo del identificador del tenant, de su nombre ni de ningún dato
   enumerable.
6. IF el `{provider}` de la ruta no es un proveedor soportado, THEN THE SYSTEM SHALL responder `404` sin
   escribir nada.
7. THE SYSTEM SHALL rechazar la petición ANTES de leer el cuerpo completo cuando la autenticación falla,
   de forma que un cuerpo grande de un llamante no autenticado no se materialice en memoria.
8. THE SYSTEM SHALL registrar el evento con el `tenant_id` resuelto por el token; y IF un evento aceptado
   no es atribuible a un tenant, THEN THE SYSTEM SHALL escribirlo con `tenant_id` NULL en vez de
   descartarlo (PRD §7.26), leyéndolo después desde una sesión **nunca marcada**.

### R2 — Aprovisionamiento, rotación y custodia de las credenciales de webhook

**Como** operadora del tenant, **quiero** obtener el token de ruta y el secreto de cabecera para pegarlos
en el panel del proveedor, y poder rotarlos, **para que** la autenticación de R1 tenga material que
administrar sin que ese material quede legible en el sistema.

Criterios de aceptación:

1. WHEN se da de alta la configuración de webhooks de un tenant, THE SYSTEM SHALL generar un
   `webhook_token` y un secreto de cabecera **distintos por tenant**, y no SHALL usar ninguna constante
   global para ninguno de los dos.
2. THE SYSTEM SHALL almacenar el secreto de cabecera cifrado con Fernet (`steering/security.md` regla 3),
   por ser una credencial de proveedor que no vive en el entorno.
3. THE SYSTEM SHALL devolver el secreto de cabecera en claro **una sola vez**: en el momento de generarlo
   y en cada rotación (excepción acotada de la regla 3(a)); y no SHALL devolverlo en ninguna lectura
   posterior, ni siquiera enmascarado.
4. WHEN se rota el token o el secreto, THE SYSTEM SHALL escribir una entrada de `AuditLog` (regla 9), y
   la rotación SHALL invalidar el valor anterior.
5. THE SYSTEM SHALL exigir RBAC para el alta y la rotación, y no SHALL exponer ninguna de las dos
   operaciones sin autenticación de usuario.
6. THE SYSTEM SHALL cubrir la tabla que guarde estas credenciales con su **test de aislamiento propio**
   (regla 1 y regla 3(c)), porque un fallo de scoping aquí no filtra datos: concede control.

### R3 — Límite de tasa y tope de tamaño de cuerpo

**Como** responsable de la disponibilidad, **quiero** que el endpoint tenga techo de peticiones y de
cuerpo, **para que** quien obtenga el token no pueda convertirlo en un amplificador ni llenar la tabla.

Criterios de aceptación:

1. IF un origen supera el límite de tasa configurado del endpoint, THEN THE SYSTEM SHALL responder `429`
   sin escribir ningún `WebhookEvent`.
2. IF el cuerpo de la petición supera el tope de tamaño configurado, THEN THE SYSTEM SHALL responder
   `413` sin escribir ningún `WebhookEvent`.
3. THE SYSTEM SHALL declarar ambos límites como configuración con valor por defecto, y no SHALL
   codificarlos como literales dispersos.
4. THE SYSTEM SHALL aplicar el límite de tasa también a las peticiones que fallan la autenticación de R1,
   de forma que sondear tokens tenga coste.

### R4 — Los datos de titular de tarjeta se descartan en la frontera

**Como** responsable de cumplimiento PCI, **quiero** que ningún dato de tarjeta llegue a persistirse,
loguearse ni reenviarse, **para que** `webhook_events.payload` no se convierta en el sumidero que la
regla 13 describe.

Criterios de aceptación:

1. WHEN se recibe un cuerpo de webhook, THE SYSTEM SHALL eliminar los datos de titular de tarjeta
   (`guarantee` y equivalentes: `card_number`, `card_type`, `cvv`, `cardholder_name`, `expiration_date`)
   **antes** de escribir `webhook_events.payload`, y no SHALL cifrarlos ni enmascararlos: PCI DSS prohíbe
   retener el CVV, así que la obligación es descartarlos (regla 13(a)).
2. THE SYSTEM SHALL aplicar el descarte de forma recursiva sobre toda la estructura del cuerpo, incluidos
   los objetos anidados dentro de listas, con política **fail-closed** ante una clave desconocida que
   coincida con el patrón.
3. THE SYSTEM SHALL escribir `webhook_events.payload` y `webhook_events.error` en **forma estructurada**
   (regla 11): el valor sensible no sobrevive en absoluto, ni enmascarado. Este change es el primer
   escritor de ambas columnas y por tanto quien hereda su contrato.
4. THE SYSTEM SHALL garantizar que ningún fixture versionado de este change contiene datos de tarjeta, y
   SHALL cubrirlo con un guard automático que **lea los ficheros en disco**, no solo la función que los
   produce (regla 13(c)).
5. THE SYSTEM SHALL mantener los datos de tarjeta fuera de los logs de acceso y de error del endpoint.

### R5 — Procesamiento asíncrono con `process_webhook_events`

**Como** manager, **quiero** que el aviso se convierta en reservas actualizadas sin intervención,
**para que** el estado de la propiedad refleje lo que pasó en el PMS.

Criterios de aceptación:

1. WHEN el job Celery `process_webhook_events` se ejecuta, THE SYSTEM SHALL procesar los `WebhookEvent`
   con `processed=FALSE` y, al completarlos, fijar `processed=TRUE` y `processed_at`.
2. THE SYSTEM SHALL alimentar el `ReservationIngestor` como **única** ruta de upsert, apoyándose en su
   idempotencia por `(tenant_id, external_pms_id)`; y no SHALL escribir reservas por ninguna otra vía.
3. IF el procesamiento de un evento falla, THEN THE SYSTEM SHALL reintentarlo hasta **3 veces con backoff
   exponencial** (PRD §16) y, agotados los reintentos, SHALL dejar el evento con `processed=FALSE` y su
   causa en `error` en forma estructurada.
4. THE SYSTEM SHALL aislar el fallo de un evento del resto: un evento que falla no SHALL impedir el
   procesamiento de los demás de la misma ejecución.
5. THE SYSTEM SHALL abrir **una sesión marcada por tenant**, nunca re-marcada, para el trabajo por tenant,
   y SHALL leer la cola de `webhook_events` desde una sesión **nunca marcada** — la columna `tenant_id` es
   nullable y una sesión marcada esconde las filas `NULL` sin error (ADR 0006, decisión 7, punto 5).
6. WHEN un evento produce una transición de estado operacional, THE SYSTEM SHALL registrarla con actor
   `WEBHOOK`, que **no está exento** de escribir su fila de `AuditLog` (regla 9).
7. THE SYSTEM SHALL tratar los eventos como potencialmente **desordenados** (ADR 0006: Channex documenta
   que llegan así) y no SHALL asumir que el orden de llegada es el orden de los hechos.

### R6 — La re-lectura por API va desacoplada del volumen de peticiones

**Como** responsable de la integración, **quiero** que el número de llamadas salientes al PMS no dependa
del número de webhooks recibidos, **para que** nadie pueda agotar la cuota del proveedor desde fuera.

Criterios de aceptación:

1. THE SYSTEM SHALL tratar el webhook como **aviso no fiable** y obtener el dato re-leyendo por API
   (ADR 0006), y no SHALL confiar en el cuerpo recibido como fuente de verdad.
2. THE SYSTEM SHALL **encolar y coalescer** la re-lectura, de forma que N avisos para el mismo objetivo
   dentro de una ventana produzcan **una** llamada saliente (regla 12(d)).
3. THE SYSTEM SHALL garantizar que ninguna ruta del endpoint de recepción realiza una llamada saliente al
   proveedor de forma síncrona.
4. WHEN se resuelven credenciales de proveedor durante el procesamiento, THE SYSTEM SHALL registrar una
   fila de `AuditLog` por cada credencial **distinta** descifrada en esa ejecución, no una por descifrado
   (segunda excepción nombrada de la regla 9).

## Out of scope

- **Suscripción automática de webhooks en el proveedor.** ADR 0006 constata que Beds24 los configura por
  propiedad desde su UI y no expone API de suscripción; por eso R2 entrega el material para pegarlo a
  mano. Automatizarlo requiere un proveedor que lo permita.
- **Validación de firma HMAC.** No se implementa la rama condicional de PRD §16: ADR 0006 demuestra que
  ninguno de los once proveedores firma. Si algún día uno lo soporta, es un change propio.
- **Webhooks de registro policial** (Chekin, `PoliceRegistration.*`). Heredan la misma regla 12 pero
  pertenecen a `access-notifications`.
- **Webhooks de mensajería** del PMS: son de `beds24-messaging-adapter`.
- **Frontend** para administrar token y secreto: la entrega es por API; la pantalla es de `dashboard-web`.
- **Redacción de códigos de acceso (PIN) en recepción.** ADR 0006 la señala como obligatoria *si* se
  elige la vía "Arrivals API de Beds24 + GrinPass", decisión que sigue abierta (PRD §5.5). No se
  construye aquí; queda anotada como riesgo a recoger cuando esa vía se elija.
- **Reproceso manual** de eventos ya marcados `processed=TRUE`, y panel de cola de errores.

## Affected specs

- `sdd/specs/reservations-webhooks.md` — *(no existe aún — se creará al archivar)*: la capacidad completa
  de recepción y procesamiento.
- `sdd/specs/reservations.md` — corregir la forma de la ruta, que hoy documenta la de PRD §23
  (`POST /api/v1/webhooks/{provider}`) y pasa a llevar el segmento token; y retirar la nota de
  "Sin recepción de webhooks" de su sección de exclusiones.
- `sdd/specs/celery-jobs.md` — registrar `process_webhook_events` entre los jobs del scheduler.
- `sdd/specs/domain-foundation-financial.md` — declarar a este change como escritor vivo de
  `webhook_events.payload` y `webhook_events.error` en la tabla de sumideros de la regla 11.
- `sdd/specs/api-contract.md` — el endpoint de recepción y los de aprovisionamiento/rotación.
- `sdd/specs/pms-beds24-adapter.md` — enlazar la recepción que su sección "Fuera de alcance" difiere aquí.
