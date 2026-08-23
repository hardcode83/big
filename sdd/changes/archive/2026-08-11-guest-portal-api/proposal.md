# Proposal: guest-portal-api

## Why

El PRD define un recorrido web para que el huésped consulte las instrucciones de
su estancia, complete el check-in legal y comunique una incidencia **sin ser un
`User` del sistema ni usar JWT** (PRD §§6, 7.6, 7.7, 17, 22, 23). `auth-tenancy`
excluyó esa identidad a propósito y `access-notifications` la dejó nombrada como
trabajo de esta entrada: *«La captura de los datos del huésped por el propio
huésped —token web, formulario de check-in— es `guest-portal-api`, que declara
`needs: access-notifications` precisamente por esto»*
(`sdd/specs/access-notifications.md:499-500`).

Hoy falta **toda la mitad de servidor**: no existe ningún token de huésped, ni
ningún endpoint público. Lo que sí existe es el suelo sobre el que se apoya —
`GuestModel` con `document_number_encrypted`, `ReservationModel` con
`legal_registration_status`, `IncidentModel` con `source = GUEST` y una columna
`reported_by_guest_token` ya prevista — de modo que este change es la costura que
los une, no un dominio nuevo.

Semilla: la capability original `guest-portal`, CANCELLED al partirse en dos.
Sus R1-R4 son de servidor y se reformulan aquí; su R5 es de interfaz y pertenece a
`guest-portal-web`. Su directorio de change se eliminó el 2026-08-23, una vez
entregadas las dos subtareas; el texto original sigue en el historial de git.

> **Corrección de una premisa heredada.** La proposal de `guest-portal` afirmaba
> que *«La API ya reserva los endpoints `/api/v1/guest/{checkin,incident,info}/{token}`»*.
> Es falso: `sdd/specs/api-contract.md` no cataloga endpoints — describe la
> generación y verificación del artefacto OpenAPI y el registro de códigos de
> error — y no contiene ninguna ruta `/api/v1/guest`. Lo que sí está reservado es
> la ruta **de frontend** `frontend/app/(guest)/guest/[token]/`. Los tres
> endpoints se diseñan aquí desde cero, no se rellena un hueco existente.

## What changes

Existirá una vía pública, acotada por un **token opaco por estancia**, que permite
a un huésped sin cuenta: consultar la información operativa de su reserva,
completar los datos legales de check-in de PRD §17 y abrir una incidencia. El
change define el **ciclo de vida completo del token** —emisión, hash en reposo,
vigencia, capacidades, revocación e idempotencia—, la autorización que deriva
estancia y tenant del propio token sin leer nada de la petición, la escritura de
PII bajo las mismas garantías de cifrado y auditoría que ya rigen para el manager,
y los límites de abuso propios de una superficie anónima. No se toca el modelo
`User`, ni RBAC, ni el flujo JWT.

## Requirements

### R1 — Ciclo de vida del token de acceso

**Como** operador del sistema, **quiero** que el acceso del huésped esté
respaldado por un token con un ciclo de vida explícito, **para que** una
superficie anónima no se convierta en una puerta permanente.

Acceptance criteria:

1. THE SYSTEM SHALL emitir un token de acceso **por estancia**, generado con un
   CSPRNG y con entropía suficiente para que su adivinación no sea viable, y
   SHALL asociarlo a exactamente una reserva y su tenant.
2. THE SYSTEM SHALL persistir **solo** una representación no reversible del token
   (hash), de modo que la columna no sea buscable por valor, y NEVER SHALL
   registrar el token en claro en logs, trazas, `AuditLog`, mensajes de error ni
   en `incidents.reported_by_guest_token`.
3. THE SYSTEM SHALL dar al token una **vigencia acotada y derivada de la
   estancia**, y IF la fecha actual queda fuera de esa ventana, THEN SHALL
   tratarlo como no autorizado.
4. THE SYSTEM SHALL permitir **revocar** un token, y WHEN la reserva pasa a
   `CANCELLED`, THE SYSTEM SHALL dejar de autorizarlo sin necesidad de una acción
   manual.
5. WHEN se emite un token para una reserva que ya tiene uno vigente, THE SYSTEM
   SHALL comportarse de forma idempotente o sustituirlo de manera explícita, y
   NEVER SHALL dejar dos tokens vigentes que autoricen la misma estancia.
6. ASSUMPTION: la **entrega** del token al huésped (el enlace dentro de la
   notificación de acceso) no está definida en `access-notifications` —su spec no
   declara plantilla ni enlace de portal—. Este change expone la emisión y deja
   la integración con el envío como decisión de `design`; si resulta que exige
   tocar la plantilla de notificación, se declarará allí.

### R2 — Autorización por estancia y tenant, y nada más

**Como** responsable de la seguridad, **quiero** que el token sea la única fuente
de identidad de la petición, **para que** no exista forma de ampliar su alcance
desde fuera.

Acceptance criteria:

1. WHEN una petición llega a un endpoint de huésped con un token válido y
   vigente, THE SYSTEM SHALL derivar la reserva, la propiedad y el `tenant_id`
   **del token dentro del caso de uso**, y NEVER SHALL leerlos de la ruta, del
   cuerpo, de la query ni de una cabecera.
2. IF el token es inexistente, inválido, expirado, revocado o consumido, THEN THE
   SYSTEM SHALL responder con el envoltorio de error público único
   (`app/core/errors.py::error_envelope`) y un código que **no distinga entre esas
   condiciones**, sin revelar si la reserva existe.
3. THE SYSTEM SHALL rechazar cualquier JWT presentado a estos endpoints: no son
   una vía alternativa de autenticación para usuarios internos.
4. THE SYSTEM SHALL aplicar a esta superficie los topes de tamaño de cuerpo ya
   existentes (`app/core/http_limits.py`) y un **límite de tasa por IP contado
   sobre autenticaciones fallidas**, siguiendo el precedente de
   `RedisWebhookThrottle`, de modo que adivinar un token cueste.
5. THE SYSTEM SHALL mantener el aislamiento de tenant en toda consulta y
   escritura, sin excepción para `SUPER_ADMIN`.

### R3 — Consulta de la información de la estancia

**Como** huésped autorizado, **quiero** consultar los datos operativos de mi
llegada, **para** encontrar la vivienda y saber cómo pedir ayuda.

Acceptance criteria:

1. WHEN el huésped consulta el endpoint de información con un token autorizado,
   THE SYSTEM SHALL devolver únicamente datos de **esa** estancia: fechas y horas
   de entrada/salida, datos públicos de la propiedad, instrucciones de llegada
   disponibles y la vía de soporte.
2. THE SYSTEM NEVER SHALL incluir en esa respuesta `reservations.internal_notes`,
   importes (`gross_amount`, `ota_commission`, `net_amount`), identificadores
   externos de PMS/canal, datos de otros huéspedes, credenciales, secretos de
   almacenamiento ni el propio token.
3. THE SYSTEM NEVER SHALL devolver el número de documento del huésped por esta
   vía, ni siquiera al huésped que lo aportó: el único endpoint que lo devuelve
   sigue siendo `GET /api/v1/guests/{id}/document`, con su rol y su auditoría
   (`sdd/specs/access-notifications.md:371-374`).

### R4 — Check-in y captura de los datos legales

**Como** huésped, **quiero** completar el formulario de check-in, **para que** la
gestora disponga de los datos del registro legal.

Acceptance criteria:

1. WHEN el huésped consulta el estado de check-in, THE SYSTEM SHALL devolver qué
   datos faltan de los ocho mínimos de PRD §17 —`full_name`, `nationality`,
   `date_of_birth`, `document_type`, `document_number`, `document_expiry_date`,
   `check_in_date`, `check_out_date`— **sin devolver los ya aportados que sean
   sensibles**.
2. WHEN el huésped envía datos de check-in válidos, THE SYSTEM SHALL actualizar
   el `Guest` asociado a la estancia, cifrar el número de documento en
   `guests.document_number_encrypted` en la misma llamada, y mover
   `guests.document_status` de `NOT_PROVIDED` a `PROVIDED`.
3. WHEN la escritura nombra explícitamente esa reserva, THE SYSTEM SHALL
   reevaluar `reservations.legal_registration_status` **solo** entre
   `PENDING_GUEST_DATA` y `READY_TO_SUBMIT`, en ambos sentidos, y SHALL devolver
   sin tocar cualquier otro estado, ni propagar a las demás estancias del huésped
   (`sdd/specs/access-notifications.md:325-332`).
4. IF falta un campo obligatorio o un dato no cumple su formato, THEN THE SYSTEM
   SHALL rechazar la operación con errores de validación objetivos y NEVER SHALL
   persistir una actualización parcial.
5. THE SYSTEM SHALL tratar el reenvío del formulario de forma idempotente, de modo
   que un reintento por pérdida de red no produzca un segundo efecto.

### R5 — Incidencia comunicada por el huésped

**Como** huésped, **quiero** comunicar una incidencia durante mi estancia, **para
que** el equipo la atienda sin darme acceso al backoffice.

Acceptance criteria:

1. WHEN el huésped envía una descripción válida, THE SYSTEM SHALL crear un
   `Incident` con `source = GUEST`, `status = OPEN`, la `property_id` y la
   `reservation_id` derivadas del token, y `reported_by_guest_token` con la
   **referencia no reversible** del token, nunca su valor.
2. IF el cuerpo excede los límites configurados o no contiene una descripción
   válida, THEN THE SYSTEM SHALL rechazarlo **antes** de crear la incidencia.
3. THE SYSTEM NEVER SHALL permitir al portador del token listar, leer, modificar,
   asignar, clasificar ni resolver incidencias; la única lectura permitida es el
   acuse de la que acaba de crear.
4. THE SYSTEM SHALL dejar `category`, `severity`, `ai_summary` y
   `ai_classification` en sus valores por defecto: clasificar es de `maintenance`,
   y una incidencia creada aquí SHALL ser indistinguible para ese flujo de
   cualquier otra en `OPEN`.
5. THE SYSTEM SHALL añadir a `maintenance` el `application/` que hoy no tiene
   —puerto de repositorio y caso de uso de creación—, y SHALL limitarlo a lo que
   esta vía necesita. Esto **es la convención, no una invasión de alcance**:
   `sdd/specs/domain-foundation-ops.md:12` establece que el `application/` y el
   `api/` de cada entidad los añade *«el change que primero persiste/expone la
   entidad»*, y para `Incident` ese change es este.

### R6 — Auditoría de una superficie anónima

**Como** responsable de cumplimiento, **quiero** que todo acceso del huésped deje
rastro, **para** poder responder quién tocó qué datos y cuándo.

Acceptance criteria:

1. WHEN se escribe o modifica PII del huésped por esta vía, THE SYSTEM SHALL
   registrar un `AuditLog` con el actor identificado como el portador del token
   —por su referencia no reversible—, la IP, los **campos** afectados y el
   instante, siguiendo el precedente `GUEST_DOCUMENT_UPDATED`.
2. THE SYSTEM SHALL escribir el `AuditLog` **antes** de producir la respuesta que
   expone o modifica el dato, no después.
3. THE SYSTEM SHALL registrar un `TimelineEvent` para los hitos con significado
   operativo —check-in completado, incidencia abierta— de modo que aparezcan en la
   timeline de la propiedad como cualquier otra transición.
4. THE SYSTEM NEVER SHALL incluir el token en claro ni el número de documento en
   ninguno de esos registros.

## Out of scope

- **La página `/guest/[token]` y toda la interfaz**: estados de carga, validación,
  error, éxito, accesibilidad e i18n ES/EN. Es `guest-portal-web`
  (`needs: guest-portal-api`), y la ruta ya existe en
  `frontend/app/(guest)/guest/[token]/`.
- **Clasificación IA, `OwnerApproval`, asignación técnica y flujo de resolución de
  incidencias**: es `maintenance`. Aquí solo se crea la incidencia en `OPEN`.
- **Submission real a SES.Hospedajes** y el movimiento de estado más allá de
  `READY_TO_SUBMIT`: es de `access-notifications`, que ya lo implementó con su
  adapter mock.
- **Emisión de instrucciones de acceso, adapters de cerradura y notificaciones**:
  `access-notifications`. Este change las **consume**, no las produce.
- **Subida de fotos o documentos desde el portal**: requiere una decisión propia de
  proveedor y límites, que es `object-storage-provisioning`.
- **Alta, login, RBAC y recuperación de contraseña de usuarios internos**:
  `auth-tenancy`, `user-management`, `auth-account-recovery`.
- **Postura general de cabeceras y topes de cuerpo para todo el backend**: es
  `backend-response-hardening`. Aquí solo se aplican los mecanismos existentes a
  esta superficie.
- **Acoplamiento de tenant en `reservations.property_id`** — candidato a entrada
  propia de roadmap, destapado por el panel de §3 y acotado deliberadamente aquí.

  El invariante que falta, enunciado como tal para quien lo recoja: **la propiedad
  de una reserva pertenece al tenant de la reserva.** Hoy no lo sostiene el
  esquema — `reservations.property_id` es una FK plana, sin la clave compuesta que
  este change sí dio a `guest_access_tokens.reservation_id` (§1) y a
  `reservations.guest_id` (§3) —, así que la fila incoherente es representable.

  Por qué no se cierra aquí: este change **no escribe** `property_id`; sus
  escritores son el CRUD de reservas y el sync del PMS, y endurecerlo obligaría a
  tocar sus caminos de escritura y sus tests. Lo que sí era problema de este change
  era el lector que lo hacía alcanzable, y está cerrado: `stay_info` filtra
  `properties.tenant_id` explícitamente, con test sobre sesión **sin marcar**.
  Verificado además por el panel que esa era la única unión reserva→propiedad del
  backend fuera de `properties/infrastructure/repositories.py`, que ya filtraba.

  Lección para quien escriba la siguiente unión reserva→propiedad: la FK **no**
  sostiene el invariante, así que el filtro va en la query.
- **Los caracteres de control de formato (`Cf`) permiten spoofing visual del texto que el
  huésped escribe** — candidato a entrada propia de roadmap, medido en §7 y acotado
  deliberadamente aquí.

  El guard de `portal_schemas.py` refusa lo que la base de datos no puede almacenar —NUL y el
  resto de la categoría `Cc`, y lo que no sobrevive a UTF-8— porque eso era un `500` anónimo.
  No refusa `U+202E` ni sus vecinos de categoría `Cf`: son texto válido que Postgres almacena
  sin queja, así que una incidencia puede llevar un título que se **renderice** invertido o
  truncado en la lista del operador. Medido por el panel de QA de §7: se acepta con `201` y se
  guarda tal cual.

  Por qué no se cierra aquí: ningún criterio de aceptación en alcance (R5.1-R5.4, R6.1-R6.4)
  pide defensa frente a spoofing visual, y el sitio correcto para ponerla no es el esquema sino
  el renderizado —la misma decisión vale para `properties.access_notes`, para los nombres de
  huésped y para cualquier texto de tercero que la UI muestre—, así que pertenece al change que
  traiga esa superficie (`guest-portal-web` para el lado del huésped, y el backoffice para el
  del operador). Lo que sí era problema de este change está cerrado: nada de lo que el huésped
  escriba puede tumbar la petición ni salir de sus dos columnas.

- **Los `description` de las respuestas del portal publican referentes internos** — candidato
  a entrada propia de roadmap, medido en `review` y acotado deliberadamente aquí.

  Un docstring de modelo Pydantic **es** el `description` del esquema en `/openapi.json`, que es
  anónimo. El hallazgo bloqueante de `review` —el presupuesto por token publicado en el contrato—
  se cerró moviendo el razonamiento de los dos esquemas de **petición** a comentarios `#`, que no
  se publican. Lo que queda, medido y no arreglado: varios esquemas de **respuesta** siguen
  publicando referentes internos —`StayInfoResponse` nombra `tests/guests/test_portal_ports.py`, y
  `CheckinStatusResponse`, `CheckinSubmittedResponse` e `IncidentReportedResponse` llevan ids R#/D#
  y una cita de requisito en castellano.

  Por qué no se cierra aquí: ninguno cae en las categorías que sí importan —no hay presupuesto, ni
  enumeración de causas de rechazo, ni oráculo—, así que lo que se filtra es estructura del
  repositorio y vocabulario de proceso, de valor nulo para quien ataca. Y arreglar uno obliga a
  arreglar los cuatro por consistencia, que es una pasada de convención sobre todos los esquemas
  publicados del backend y no una tarea de esta capacidad. La regla que lo gobierna ya está escrita
  donde toca (`backend/app/guests/api/portal_router.py`, y ahora también sobre los dos esquemas de
  petición): quien haga la pasada la tiene enunciada.

- **El registro de peticiones del intermediario guarda el token en claro** — requisito
  previo de `guest-portal-web`, localizado en `review` y acotado deliberadamente aquí.

  La restricción 9 de la tarea 6.1 exigía «confirmar el log de acceso del ingress antes de
  exponerla» y se cerró sobre una premisa que resultó falsa: *«el panel no localizó esa
  configuración en `infra/`»*. Sí hay ingress, y está fuera de `infra/` —
  `docker-compose.deploy.yml` corre `cloudflare/cloudflared … tunnel run`.

  Lo que la revisión sí estableció, contra la lectura más alarmista: cloudflared enruta
  **solo** a `http://frontend:3000` (`infra/environments/dev/main.tf`) y `backend` está fuera
  de la red `ingress` a propósito, así que **ningún componente de este repositorio** escribe
  el token en un log. La redacción de D8 cubre el único que podría. Pero el token viaja en el
  URI que termina en el edge de Cloudflare, y nada del repositorio configura ni desactiva ese
  registro (`grep -rn "logpush|logging" infra/` → vacío).

  Por qué no se cierra aquí: la comprobación es contra la cuenta de Cloudflare, que está
  fuera de la IaC de este repositorio, y **hoy no hay nada que ejerza la superficie** —
  `frontend/app/(guest)/guest/[token]/` son tres ficheros de relleno y cero llamantes de
  `guest/info|checkin|incident`. La puerta está abierta y aún no se ha cruzado; se cruza con
  `guest-portal-web`, que es donde este requisito previo tiene que morder. Lo que sí era
  problema de este change está cerrado: `docs/guest-portal.md` ya no afirma un absoluto que
  D8 solo garantiza para uvicorn, y nombra el residual del intermediario para que un operador
  que vea el token en el panel de Cloudflare no lo lea como una brecha.

- **El cliente de Redis cacheado en un global cruza bucles de eventos** — candidato
  a entrada propia de roadmap, medido en §6 y acotado deliberadamente aquí.

  `app/core/redis.py::get_redis` guarda un único cliente en un global de módulo, y
  los tests crean un bucle por test (`tests/conftest.py` lo documenta para el motor
  de SQLAlchemy, que sí tiene `NullPool` por eso mismo). Así que el primer test que
  llega a una ruta usando la dependencia real deja ahí un cliente atado a **su**
  bucle, y el siguiente que lo reutilice muere con `RuntimeError: Event loop is
  closed`. Medido: al añadir los tests de §6 sin fingir el throttle, el que se caía
  era `tests/integrations/test_webhook_receiver_api.py::test_the_router_drives_the_real_throttle`
  — un fichero que este change no toca, y en verde al ejecutarlo aislado.

  Por qué no se cierra aquí: la reparación es una fixture `autouse` en el
  `conftest.py` raíz que llame a `close_redis()`, o un `NullPool` equivalente para
  Redis; en ambos casos es infraestructura de test compartida por las nueve suites
  y su alcance es todo el backend, no esta superficie. Lo que sí era problema de
  este change está cerrado: ninguno de sus tests de ruta pide el Redis real, y el
  fichero del tope de cuerpo explica por qué finge el throttle que ni siquiera
  consulta.

## Affected specs

- `sdd/specs/guest-portal-api.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/access-notifications.md` — su nota sobre `guests.document_status` y
  `legal_registration_status` anticipa explícitamente esta revisión
  (líneas 306-310); se actualizará solo si el diseño cambia ese contrato.

  **La condición se cumplió: hay que actualizarla al archivar, y no antes.** El
  panel de §2 obligó a meter `full_name` y `nationality` en `REDACTED_FIELDS`
  (design D10, corregido en run), así que estas dos frases de esa spec quedarán
  falsas en cuanto este change entre:

  - línea 394-395: *«Y `nationality` no está denegada: la frase de steering nombra
    el documento y la fecha de nacimiento y ahí se detiene, así que su redacción es
    disciplina del caso de uso.»* → pasa a estar denegada, y la redacción deja de
    ser disciplina para ser construcción. La premisa que la justificaba —que solo
    la escribía un operador— es justo la que rompe este change al abrir
    `POST /api/v1/guest/checkin/{token}`. Al reescribirla, **citar**
    `REDACTED_FIELDS` en vez de reenunciar el contrato: la regla 11 dice que su
    único hogar es `steering/security.md` y que todo lo demás la cita, y esta
    frase es precisamente una reenunciación.
  - el párrafo «Dónde acaba la garantía estructural» que la contiene: revisar que
    el resto siga siendo cierto una vez la auditoría del huésped es estructural en
    los cinco campos y no en tres.

  No se toca ahora **a propósito**: `sdd/specs/` describe el sistema desplegado, y
  hasta que este change se mergee la frase sigue siendo verdad de `main`.
  Encontrada por el panel de seguridad de §2, que la localizó después de que un
  grep mío la dejara pasar por acotar los términos de búsqueda.
- `sdd/specs/auth-tenancy.md` — referencia de la exclusión del huésped. La premisa
  original («no debería modificarse salvo que el diseño revele una contradicción») **se
  cumplió al revés de lo esperado**: no hay contradicción de diseño, pero sí dos frases
  que este change vuelve falsas, y hay que actualizarlas al archivar.

  Las dos afirman el **recuento de consultas sin scope de tenant**, que es el control de
  auditoría de la regla 1 de `steering/security.md`:

  - línea 35: *«`find_by_email_globally` —la **primera** de las dos consultas sin scope de
    tenant del sistema»*
  - línea 398: *«sigue siendo una de las **dos** del sistema»*

  Son **tres** desde este change: entra
  `SqlAlchemyGuestAccessTokenRepository.find_live_by_token_hash`, y —esto es lo que rompe
  más que el número— **no se llama `*_globally`**, así que la auditoría por grep del sufijo
  que esas frases describen deja de ser exhaustiva. Al reescribirlas, **citar** la
  enumeración de `SqlAlchemyUserRepository.find_by_email_globally` en vez de repetir el
  recuento: el panel de arquitectura del merge encontró **seis** copias de este dato en el
  árbol y solo una corregida, que es el mismo fallo que la regla 11 documenta de sí misma.

  No se tocan ahora a propósito: `sdd/specs/` describe el sistema desplegado, y hasta que
  este change se mergee las dos frases siguen siendo verdad de `main`.
- `sdd/specs/domain-foundation-ops.md` — dueña de `Incident` y de la regla de
  reparto de la línea 12 (*el `application/` lo añade quien primero persiste la
  entidad*); se actualizará para dejar de decir que `maintenance` «sigue sin»
  `application/` una vez este change se lo dé.
