# Portal del huésped — API y seguridad

## Purpose

Da al huésped una vía web para consultar su estancia, completar el check-in legal de PRD §17 y
abrir una incidencia **sin ser un `User` del sistema y sin JWT** (PRD §§6, 7.6, 7.7, 17, 22, 23).
La identidad la aporta un **token opaco por estancia** que viaja en la ruta: él resuelve la
reserva, la propiedad y el tenant, y nada de la petición puede ampliar ese alcance.

Son cuatro rutas anónimas bajo `/api/v1/guest/`, dos rutas de operador para acuñar y revocar el
token, una tabla `guest_access_tokens`, la columna `audit_logs.actor_guest_token_hash` y el
`application/` que [`domain-foundation-ops.md`](domain-foundation-ops.md) dejaba pendiente para
`Incident`. Se apoya en lo que ya existía: el escritor único del documento cifrado y el servicio
de estado legal de [`access-notifications.md`](access-notifications.md), y la forma de superficie
anónima que [`reservations-webhooks.md`](reservations-webhooks.md) fijó — token en la ruta, hash
indexable, respuesta de fallo única, redacción en el log de acceso.

**Sin frontend.** La ruta `frontend/app/(guest)/guest/[token]/` existe reservada pero ninguna
página la ejerce; la interfaz es `guest-portal-web`. Hoy el portal se opera con `curl`.

El *cómo se opera y se diagnostica* —invocaciones, tabla de configuración, consultas SQL de
diagnóstico— está en [`docs/guest-portal.md`](../../docs/guest-portal.md); esta spec cubre qué
garantiza el sistema.

## Requirements

### Reparto de rutas y montaje

- THE SYSTEM SHALL servir las cuatro rutas anónimas desde un router propio,
  `app/guests/api/portal_router.py`, montado por separado del router autenticado del módulo, que
  declara `AUTHENTICATED_RESPONSES` y cuelga sus rutas de `require(...)`. Una ruta sin autenticar
  dentro de una forma que promete lo contrario es lo que esa separación existe para impedir.
- THE SYSTEM SHALL exponer exactamente estas cuatro rutas, con el token como último segmento:

  | Método y ruta | Respuesta | Éxito |
  |---|---|---|
  | `GET /api/v1/guest/info/{token}` | `StayInfoResponse` | `200` |
  | `GET /api/v1/guest/checkin/{token}` | `CheckinStatusResponse` | `200` |
  | `POST /api/v1/guest/checkin/{token}` | `CheckinSubmittedResponse` | `200` |
  | `POST /api/v1/guest/incident/{token}` | `IncidentReportedResponse` | `201` |

- THE SYSTEM SHALL declarar en las cuatro un contrato de error propio de `404`, `429` y `413`
  contra `ErrorEnvelope`, y NEVER SHALL declarar el `401` de las rutas autenticadas: no pueden
  prometer un código que nunca devuelven.
- THE SYSTEM SHALL mantener las cuatro entradas en el censo `ANONYMOUS_ENDPOINTS` de
  `tests/test_route_authorization.py`, de modo que añadir una quinta ruta anónima sea un diff
  visible y no un descuido.
- THE SYSTEM SHALL no introducir ningún código de error nuevo: `NOT_FOUND`, `RATE_LIMITED`,
  `PAYLOAD_TOO_LARGE` y `VALIDATION_ERROR` ya existen en el registro.

### El token: ciclo de vida

- THE SYSTEM SHALL emitir un token **por estancia** con 32 bytes de CSPRNG (256 bits) en forma
  URL-safe, porque es un segmento de ruta.
- THE SYSTEM SHALL persistir **solo** su SHA-256 en hexadecimal (64 caracteres), sin sal ni
  pimienta, y NEVER SHALL ofrecer ninguna ruta que lo lea de vuelta. La ausencia de sal es
  deliberada y estructural: la consulta de verificación llega **sin tenant en la mano**, así que
  el hash tiene que ser indexable — un digest salado sería imposible de buscar, que es la
  propiedad de la que depende toda la ruta. No hay diccionario que atacar contra 256 bits.
- THE SYSTEM SHALL hacer `token_hash` único **globalmente**, no por tenant, de modo que
  «exactamente una fila» sea garantía del esquema y no suposición del llamante.
- THE SYSTEM SHALL garantizar por índice único parcial —`(reservation_id) WHERE revoked_at IS
  NULL`— que nunca haya dos tokens vigentes autorizando la misma estancia.
- THE SYSTEM SHALL acoplar el token a su tenant con una clave ajena **compuesta** sobre
  `(tenant_id, reservation_id) → reservations(tenant_id, id)`, `ON DELETE RESTRICT`. Dos claves
  ajenas independientes permitirían una fila que empareja el tenant A con una reserva del tenant
  B, y la autorización corre sobre una sesión deliberadamente **sin marcar** —es la fila del
  token la que resuelve el tenant—, así que el filtro global está apagado justo donde esa fila
  incoherente se leería.
- THE SYSTEM SHALL derivar la vigencia en cada verificación y NEVER SHALL almacenarla: no existe
  columna `expires_at`. Un `expires_at` calculado en la emisión quedaría obsoleto en cuanto la
  estancia se mueve, y las cancelaciones exigirían un barrido.
- WHEN se verifica un token, THE SYSTEM SHALL exigir las tres condiciones a la vez —`revoked_at`
  nulo, reserva no `CANCELLED`, y el instante actual dentro de la ventana— y SHALL fundirlas en
  un único booleano, de modo que las causas sean indistinguibles desde fuera.
- THE SYSTEM SHALL cerrar la ventana en la **medianoche UTC** de
  `check_out_date + GUEST_PORTAL_TOKEN_GRACE_DAYS`. La medianoche de una fecha es su *primer*
  instante: con salida el día 3 y 2 días de gracia el token muere a las 00:00 del día 5, así que
  el huésped conserva el 3 y el 4 enteros. Leerlo como «hasta el final del 5» concede un día de
  más, y la primera implementación lo concedía.
- ASSUMPTION: la ventana cierra en UTC y no en `properties.timezone`. Con la gracia por defecto
  el desfase máximo son 2 horas sobre 48, y meter la zona de la propiedad en el cálculo obligaría
  a leerla en el camino de autenticación, antes de tener tenant.
- WHEN la reserva pasa a `CANCELLED`, THE SYSTEM SHALL dejar de autorizar el token en ese
  instante, sin ninguna acción manual ni ningún job.
- El «token de un solo uso» de PRD §23 es una **divergencia declarada**: un solo uso no puede
  servir las cuatro rutas que ese mismo comentario encabeza a lo largo de una estancia. Lo que el
  paréntesis pide —que no sea una credencial permanente— lo da la ventana, y «consumido» lo cubre
  `revoked_at`.

### Emisión y revocación: ruta de operador, valor devuelto una sola vez

- THE SYSTEM SHALL exponer `POST` y `DELETE /api/v1/reservations/{reservation_id}/guest-access-token`
  en el router autenticado, bajo el permiso `MANAGE_GUEST_ACCESS_TOKENS`, concedido a
  `TENANT_OWNER` y `PROPERTY_MANAGER`.
- WHEN un operador acuña el token, THE SYSTEM SHALL devolver el valor en claro **exactamente una
  vez**, en el `201`, y después SHALL conservar solo su hash. Es la excepción única y nombrada de
  la regla 3(a) de `steering/security.md` —un secreto que nosotros generamos para que un tercero
  nos autentique— y no se ensancha.
- WHEN se acuña un token para una estancia que ya tenía uno vigente, THE SYSTEM SHALL revocar el
  anterior y crear el nuevo **en la misma transacción**: sustitución explícita, no acumulación.
  Devolver el anterior es imposible, porque solo se guarda su hash.
- THE SYSTEM SHALL hacer la revocación idempotente mediante una escritura condicional
  `WHERE revoked_at IS NULL`, SHALL responder `204` sin cuerpo las dos veces, y NEVER SHALL
  revelar si había token que revocar.
- IF dos emisiones concurrentes chocan contra el índice único parcial, THEN THE SYSTEM SHALL
  traducir el `IntegrityError` a `409 CONFLICT` con un mensaje accionable, y SHALL re-lanzar
  cualquier otra violación de restricción en lugar de absorberla. El perdedor no deja estado, así
  que su reintento acuña limpio.
- THE SYSTEM SHALL auditar la emisión y la revocación, y NEVER SHALL escribir fila de auditoría
  cuando la revocación no revocó nada.
- La **entrega** del enlace al huésped es manual hoy: `ConsoleEmailAdapter` y `MockWhatsAppAdapter`
  son los únicos adapters y sus plantillas no llevan enlace de portal, así que emitirlo desde el
  barrido de accesos acuñaría credenciales que nadie recibe. La costura está hecha —el caso de uso
  y su puerto existen—, y la emisión automática es después un llamante más.

### Autorización: el token es la única identidad

- WHEN llega una petición a cualquiera de las cuatro rutas, THE SYSTEM SHALL derivar la reserva,
  la propiedad y el `tenant_id` **de la fila del token, dentro del caso de uso**, y NEVER SHALL
  leerlos de la ruta, del cuerpo, de la query ni de una cabecera. El router recibe el token y
  nada más.
- THE SYSTEM SHALL ordenar la autorización así, y el orden es la propiedad de seguridad: hash del
  token → consulta por `token_hash` sobre la sesión **sin marcar** → proyección de la reserva →
  la regla de vigencia → `bind_session_to_tenant` → `GuestSession` congelada.
- THE SYSTEM SHALL ejecutar la proyección de la reserva **siempre**, incluso cuando el hash no
  encontró fila, sustituyendo los identificadores por marcadores. Sin eso, «token desconocido»
  cuesta una consulta y «token conocido pero muerto» cuesta dos, y esa asimetría es medible desde
  fuera.
- THE SYSTEM SHALL seleccionar **columnas y no modelos** en los dos pasos previos al marcado, de
  modo que ninguna instancia ORM entre en el mapa de identidad antes de que la sesión tenga
  tenant. Que el límite 4 de `app/core/db.py` no muerda aquí es entonces estructural y no una
  consecuencia del refcounting de CPython.
- THE SYSTEM SHALL rechazar cualquier JWT **por ausencia**: ninguna de las cuatro rutas declara
  esquema bearer ni dependencia de autenticación, así que no hay código que lea `Authorization`.
  Una petición con un JWT válido y sin token de ruta válido recibe el mismo `404` que cualquier
  otra. Un rechazo explícito sería peor: obligaría a leer la cabecera para poder rechazarla.
- R2.5 (aislamiento sin excepción para `SUPER_ADMIN`) se cumple por construcción: no hay rol en
  esta superficie, no hay JWT y ninguna consulta consulta un rol.
- THE SYSTEM SHALL derivar `tenant`, reserva y propiedad del token también en la ruta de
  operador, verificando que la reserva pertenece al tenant del llamante antes de acuñar.

### Una sola respuesta de fallo

- THE SYSTEM SHALL responder `404` con un cuerpo **idéntico** a todo fallo de autorización —token
  inexistente, mal formado, revocado, fuera de ventana o de una reserva cancelada—, construido
  una sola vez como constante del módulo para que varios sitios no puedan divergir.
- THE SYSTEM SHALL levantar una única excepción sin causa para todos esos casos, de modo que la
  razón no viaje hasta el borde ni pueda filtrarse por descuido.
- THE SYSTEM SHALL usar `404` y no `401`: un `401` invita a una cabecera `Authorization` que aquí
  no significa nada, y `NOT_FOUND` es el código que el proyecto ya usa para «existe pero no es
  tuyo».
- THE SYSTEM SHALL emitir ese `404` desde un único punto que **antes** contabiliza el intento
  fallido contra el presupuesto por IP. La entrada equivalente en la tabla de manejadores de
  excepción produce un cuerpo idéntico pero no cobra: es la red, no el mecanismo.
- El `404` es por tanto inútil para diagnosticar, a propósito. Diagnosticar se hace sobre la fila
  de `guest_access_tokens`, y [`docs/guest-portal.md`](../../docs/guest-portal.md) da las consultas.

### Límites de abuso

- THE SYSTEM SHALL aplicar dos límites asimétricos sobre Redis, en ventana fija de 60 segundos:
  - **por IP**, `GUEST_PORTAL_PROBE_LIMIT_PER_MINUTE` (20), alimentado **solo por autorizaciones
    fallidas** y consultado como portón **antes de cualquier consulta**;
  - **por token**, `GUEST_PORTAL_RATE_LIMIT_PER_MINUTE` (60), cobrado **después** de autorizar y
    con el digest ya resuelto, nunca re-hasheando el segmento de ruta.
- El segundo importa aquí más que en los webhooks: es lo único que acota cuántas filas de
  `incidents` puede producir una estancia, porque la incidencia no está deduplicada.
- THE SYSTEM SHALL aplicar el tope de cuerpo general de `/api/v1/` (1 MiB) **antes del routing**,
  sin rama ni ajuste propio, y SHALL devolver `413` sin haber escrito nada — un cuerpo truncado
  llega como desconexión del cliente, y un rechazo que además escribe es peor que cualquiera de
  los dos resultados por separado.
- ASSUMPTION: la ventana es fija y no deslizante, y la comprobación del presupuesto no es atómica
  respecto a su cobro, así que dos peticiones simultáneas en el borde pueden pasar ambas.

### Consulta de la estancia

- WHEN el huésped consulta la información con un token autorizado, THE SYSTEM SHALL devolver una
  **proyección congelada** de exactamente dieciséis campos: fechas y horas de entrada y salida,
  nombre y dirección de la vivienda, ciudad, provincia, código postal, país, zona horaria, nombre
  de la WiFi, instrucciones de llegada, código de acceso enmascarado y vía de soporte.
- THE SYSTEM SHALL cumplir la exclusión **estructuralmente**, por el juego de campos del tipo y
  no por disciplina del serializador: `reservations.internal_notes`, `gross_amount`,
  `ota_commission`, `net_amount`, los identificadores externos de PMS y canal, los datos de otros
  huéspedes, `properties.wifi_password_encrypted` y el propio token no están declarados, así que
  ningún serializador futuro puede filtrarlos por descuido.
- THE SYSTEM NEVER SHALL devolver el número de documento por esta vía, ni siquiera al huésped que
  lo aportó: el único endpoint que lo devuelve sigue siendo `GET /api/v1/guests/{id}/document`,
  con su rol y su auditoría ([`access-notifications.md`](access-notifications.md)).
- THE SYSTEM SHALL tomar las horas de entrada y salida de la reserva y, cuando sean nulas, de
  `properties.default_check_in_time`/`default_check_out_time`.
- THE SYSTEM SHALL exponer `properties.access_notes` como instrucciones de llegada, y el código
  de acceso **ya enmascarado** desde la base de datos —el sistema no almacena el código en claro
  en ninguna parte—, tomando el registro vivo más reciente de la estancia.
- THE SYSTEM SHALL tomar la vía de soporte de la configuración y no de ningún dato de otro
  huésped.
- THE SYSTEM SHALL filtrar `properties.tenant_id` **explícitamente** en esa consulta, además de
  `reservations.tenant_id`. La clave ajena `reservations.property_id` es plana y no acopla el
  tenant, así que una reserva del tenant A apuntando a una propiedad del tenant B es una fila
  representable; sin ese segundo predicado se leen la dirección, el nombre de la WiFi y las
  instrucciones de llegada de otro operador.

### Check-in y captura de los datos legales

- WHEN el huésped consulta el estado de check-in, THE SYSTEM SHALL devolver **qué falta** de los
  ocho mínimos de PRD §17 más `document_status` y `legal_registration_status`, y NEVER SHALL
  devolver los datos ya aportados.
- WHEN la estancia todavía no tiene huésped asociado, THE SYSTEM SHALL evaluar la misma regla
  pura sobre un sujeto vacío que solo lleva las dos fechas de la reserva, y responder
  `NOT_PROVIDED` / `PENDING_GUEST_DATA` en lugar de fallar.
- THE SYSTEM SHALL aceptar en el envío exactamente seis campos —`full_name`, `nationality`,
  `date_of_birth`, `document_type`, `document_number`, `document_expiry_date`—, todos requeridos,
  y SHALL rechazar cualquier campo no declarado, incluidos los de identidad como `tenant_id` o
  `reservation_id`. Las dos fechas de la estancia no se piden ni se aceptan: son de la reserva.
- THE SYSTEM SHALL rechazar el texto que la base de datos no puede almacenar —lo que no sobrevive
  a UTF-8 y los caracteres de control de categoría `Cc` fuera de una lista corta de espacios en
  blanco— y NEVER SHALL devolver el valor rechazado en el mensaje de error.
- WHEN el envío es válido, THE SYSTEM SHALL delegar la escritura en el **escritor único** del
  documento en lugar de duplicarlo, cifrando `document_number` en la misma llamada y moviendo
  `document_status` a `PROVIDED`. Un segundo escritor de la columna más sensible del sistema
  convertiría en lista-que-alguien-recuerda-actualizar la enumeración exhaustiva de dónde existe
  el número en claro.
- IF `reservations.guest_id` es `NULL`, THEN THE SYSTEM SHALL crear el `Guest` desde el nombre
  enviado y reclamar la estancia con una escritura **condicional** `WHERE guest_id IS NULL`, que
  devuelve quién la sostiene. Dos envíos simultáneos leerían ambos `NULL`, crearían dos huéspedes
  y el segundo sobrescribiría el enlace, dejando huérfana una fila **con el documento cifrado
  dentro**, inalcanzable y no borrable; con la reclamación condicional el perdedor continúa con
  el huésped del ganador y a lo sumo deja atrás una fila con solo un nombre.
- THE SYSTEM SHALL reevaluar `legal_registration_status` **solo** para la reserva nombrada, solo
  entre `PENDING_GUEST_DATA` y `READY_TO_SUBMIT`, en ambos sentidos, y SHALL devolver sin tocar
  cualquier otro estado —`SUBMITTED`, `FAILED`, `MANUAL_REVIEW`, `NOT_REQUIRED`— ni propagar a las
  demás estancias del huésped. Es el comportamiento que
  [`access-notifications.md`](access-notifications.md) ya tenía; lo único que cambia es quién lo
  dispara.
- THE SYSTEM SHALL completar la operación en **una sola transacción con un solo `commit()`**. El
  escritor reutilizado comitea incondicionalmente al final, así que componerlo dentro de otro caso
  de uso le daría dos transacciones: se le pasa una unidad de trabajo cuyo `commit()` no hace
  nada, y la frontera se queda entera en el caso de uso del portal. Los dos cableados dejan las
  mismas filas cuando nada falla —lo que los distingue es la **secuencia**, y por eso está fijada
  con un test.
- IF falta un campo o un dato no cumple su formato, THEN THE SYSTEM SHALL rechazar antes de tocar
  la base de datos y NEVER SHALL persistir una actualización parcial.
- THE SYSTEM SHALL tratar el reenvío del formulario de forma idempotente en el **efecto de
  negocio**: es una sobrescritura completa del mismo conjunto de campos y el estado legal converge
  al mismo valor. El rastro no se suprime — ver Auditoría.
- THE SYSTEM NEVER SHALL devolver eco del número de documento en la respuesta del envío.

### Incidencia comunicada por el huésped

- WHEN el huésped envía título y descripción válidos, THE SYSTEM SHALL crear un `Incident` con
  `source = GUEST`, `status = OPEN`, la propiedad y la reserva **derivadas del token**, y
  `reported_by_guest_token` con el digest hexadecimal, nunca el valor del token.
- THE SYSTEM SHALL dejar `category`, `severity`, `ai_summary`, `ai_classification`,
  `assigned_technician_id`, `owner_approval_required`, los costes y `resolved_at` en sus valores
  por defecto, de modo que una incidencia creada aquí sea **indistinguible** para el flujo de
  clasificación de cualquier otra en `OPEN`. **Ese flujo existe desde `maintenance`**
  (2026-08-15) y consume exactamente ese par —`OPEN` y sin `ai_classification`—, así que la
  indistinguibilidad dejó de ser una promesa de diseño y es la condición literal del job
  `classify_incidents` ([`maintenance.md`](maintenance.md)). La clasificación **no** ocurre
  dentro de esta petición: colgar la llamada al clasificador de una ruta anónima de internet es
  lo que prohíbe la regla 12(d) de `steering/security.md`.
- THE SYSTEM SHALL exigir `title` además de `description`, porque la columna es `NOT NULL`.
  Derivarlo de los primeros caracteres de la descripción sería inventar un dato del huésped.
- IF el cuerpo excede los límites o no contiene texto válido, THEN THE SYSTEM SHALL rechazarlo
  **antes** de crear nada, y el `422` NEVER SHALL devolver el valor rechazado.
- THE SYSTEM NEVER SHALL permitir al portador del token listar, leer, modificar, asignar,
  clasificar ni resolver incidencias. Se cumple **estructuralmente**: no existe ninguna ruta `GET`
  de incidencias en el portal, así que no hay nada que restringir. La respuesta del `POST` lleva
  `id`, `status` y `created_at` de la que acaba de crear, y nada más.
- THE SYSTEM SHALL dar a `maintenance` el `application/` que no tenía —un puerto de repositorio
  con **un solo método** (`add`) y el caso de uso de creación— sin darle `api/`: la ruta de
  creación es del portal. Es la convención de
  [`domain-foundation-ops.md`](domain-foundation-ops.md), que asigna el `application/` de cada
  entidad al change que primero la persiste. Un puerto de un método es más fácil de ensanchar que
  uno especulativo de diez — y **eso es exactamente lo que pasó**: el change `maintenance`
  (2026-08-15) ensanchó ese puerto y le dio a `maintenance` su propia capa `api/`
  ([`maintenance.md`](maintenance.md)). Esta ruta del portal sigue siendo la única superficie
  **anónima** que crea incidencias, y ninguna de las rutas nuevas es alcanzable con un token de
  huésped.
- THE SYSTEM SHALL rechazar en el adaptador cualquier escritura cuyo tenant no coincida con el de
  la entidad, en lugar de confiar en el filtro global, que no cubre los `INSERT`.

### Auditoría

- WHEN se escribe o modifica PII del huésped por esta vía, THE SYSTEM SHALL registrar la fila de
  `AuditLog` con el portador identificado por `actor_guest_token_hash` —el digest, nunca el
  token—, la IP, los **campos** afectados y el instante.
- THE SYSTEM SHALL auditar el check-in del huésped como `GUEST_DOCUMENT_UPDATED` sobre la entidad
  `GUEST`, y NEVER SHALL inventar una acción propia: la operación *es* la modificación del
  documento, y quién la hizo lo dice el actor, no el verbo. Una acción distinta partiría en dos la
  consulta «quién tocó el documento de este huésped».
- THE SYSTEM SHALL registrar `GUEST_ACCESS_TOKEN_ISSUED` y `GUEST_ACCESS_TOKEN_REVOKED` sobre la
  entidad `GUEST_ACCESS_TOKEN`, e `INCIDENT_CREATED` sobre `INCIDENT`.
- THE SYSTEM SHALL escribir la fila de auditoría **antes** del `commit()` y antes de producir la
  respuesta, de modo que una auditoría que falla revierte la operación entera. En la emisión, el
  valor en claro se devuelve **después** del commit.
- THE SYSTEM SHALL exigir que un `AuditLog` lleve **exactamente uno** de los dos actores —usuario
  o portador de token— y que el hash sea un digest hexadecimal en minúsculas de 64 caracteres,
  comprobado en tres capas que coinciden en un solo predicado: la factoría de dominio, el
  repositorio y una restricción `CHECK` de la tabla.
- THE SYSTEM SHALL restringir los campos auditables de una incidencia a `source`, `status` y
  `reservation_id`, y los de un token de acceso a `token_hash` y `revoked_at`. `title` y
  `description` quedan fuera a propósito: son texto libre escrito desde fuera y `audit_logs.changes`
  es un sumidero de la regla 11. `token_hash` ya está denegado, así que la única forma alcanzable
  de registrarlo es «cambió», sin su valor.
- THE SYSTEM SHALL registrar una fila de auditoría en **cada** envío del formulario, incluidos los
  reenvíos. Suprimir la segunda escondería un segundo envío del documento, posiblemente desde otra
  IP, que es justo lo que una revisión de incidente busca: la idempotencia de R4.5 es sobre el
  efecto de negocio, no sobre el rastro.
- THE SYSTEM NEVER SHALL escribir fila de auditoría en las dos rutas de solo lectura.
- THE SYSTEM SHALL mantener `full_name` y `nationality` en la lista de campos redactados. Los
  incorporó esta capacidad: hasta ahora los escribía un operador, y abrir el `POST` anónimo de
  check-in convirtió en texto que teclea un anónimo lo que se habría registrado en claro en una
  tabla *append-only*. Ambos siguen en el *allowlist* de la entidad `GUEST`, así que la auditoría
  sigue registrando **que** cambiaron.
- La columna `actor_guest_token_hash` es una **divergencia declarada** de PRD §7.25, que enumera
  las columnas de `audit_logs` y no la incluye. Las dos alternativas estaban cerradas, no
  descartadas por gusto: meterlo en `changes` lo impide la regla 11 por construcción, y dejar el
  actor a `NULL` contradice el requisito de identificar al portador.

### Timeline

- THE SYSTEM SHALL registrar `GUEST_CHECKIN_COMPLETED` —valor de enum nuevo— **solo cuando el
  estado legal transiciona de verdad**, de modo que un reenvío no escriba un segundo evento en una
  tabla inmutable. Ninguno de los tipos existentes lo decía: el de la ventana de entrada es el
  reloj, y reutilizar el de la presentación legal afirmaría permanentemente una presentación ante
  la policía que no hubo.
- THE SYSTEM SHALL registrar `INCIDENT_CREATED`, que ya existía.
- THE SYSTEM SHALL marcar ambos con `actor_type = GUEST` y `actor_user_id` nulo, que es lo único
  que la factoría permite para un actor que no es un usuario.
- THE SYSTEM SHALL llevar en el evento un título **constante** y solo identificadores en su
  metadato, y NEVER SHALL llevar campos ni valores del documento ni el texto que escribió el
  huésped: la timeline es inmutable y nada que aterrice ahí se puede redactar después.

### El token no persiste en claro en ningún sumidero

- THE SYSTEM SHALL redactar el último segmento de `/api/v1/guest/{acción}/{token}` en el log de
  acceso, conservando la acción, que no es secreta. Es obligatorio y no cosmético: el token viaja
  en la ruta, así que sin esto cualquiera con lectura del log recupera todas las estancias vivas.
- THE SYSTEM SHALL hacerlo **generalizando el filtro que ya existía** para los webhooks —un único
  filtro con dos patrones, no un segundo filtro sobre el mismo logger—, porque dos filtros
  haciendo lo mismo es cómo uno de los dos deja de instalarse.
- THE SYSTEM SHALL anclar el patrón en el prefijo más un segmento, de modo que cubra cualquier
  acción futura bajo `/api/v1/guest/`.
- THE SYSTEM NEVER SHALL registrar el token en `AuditLog`, en la timeline, en
  `incidents.reported_by_guest_token` ni en mensajes de error: en todos ellos circula solo el
  digest.

### Aislamiento por tenant

- THE SYSTEM SHALL filtrar `tenant_id` explícitamente en toda consulta y toda escritura de esta
  superficie, **excepto** la búsqueda por `token_hash`, que es la que resuelve el tenant y por
  tanto no tiene por qué filtrar.
- Esa búsqueda es una de las consultas sin scope de tenant del sistema. Su enumeración —el
  control de auditoría de la regla 1 de `steering/security.md`— vive en **un solo sitio**, el
  docstring de `SqlAlchemyUserRepository.find_by_email_globally`, y esta spec lo cita en vez de
  repetir el recuento. La convención de nombrado `*_globally` dejó de enumerarlas: esta no lleva
  el sufijo ni vive en ese módulo.
- THE SYSTEM SHALL marcar la sesión con el tenant en cuanto lo resuelve, y NEVER SHALL desmarcarla:
  el marcado es de un solo sentido, que es correcto porque la sesión de una ruta anónima nace sin
  marcar.

### Configuración

| Variable | Defecto | Qué hace |
|---|---|---|
| `GUEST_PORTAL_TOKEN_GRACE_DAYS` | `2` | Días tras `check_out_date` en que el enlace sigue autorizando |
| `GUEST_PORTAL_RATE_LIMIT_PER_MINUTE` | `60` | Peticiones por minuto y token, tras autorizar |
| `GUEST_PORTAL_PROBE_LIMIT_PER_MINUTE` | `20` | Autorizaciones **fallidas** por minuto e IP |
| `GUEST_PORTAL_SUPPORT_CHANNEL` | — | Vía de soporte que se le enseña al huésped |

Ninguna es secreta, así que las tres primeras llevan defecto funcional.

## Deuda declarada

- **El portón por IP frena también a un huésped legítimo.** El presupuesto solo lo *alimentan* las
  autorizaciones fallidas, pero se *consulta* en toda petición, así que agotado por 20 fallos una
  dirección compartida —CGNAT, WiFi de hotel— devuelve `429` a un token bueno hasta que acabe la
  ventana. Se mantiene a propósito: el portón tiene que morder antes de las consultas que un
  adivinador intenta provocar, y es el orden que ya lleva en producción la superficie de webhooks.
  La forma de la solución está identificada —un portón por token, o una lista de excepción para
  las direcciones de salida conocidas de un operador— y anotada junto al valor que la gobierna.
- **La incidencia no es idempotente.** Un reintento crea una segunda incidencia en `OPEN`. Lo
  único que la acota es el límite por token.
- **Los caracteres de formato (`Cf`) permiten spoofing visual.** El guard refusa lo que la base de
  datos no puede almacenar, no `U+202E` y sus vecinos, que son texto válido: una incidencia puede
  llevar un título que se **renderice** invertido o truncado en la lista del operador. El sitio
  correcto para la defensa es el renderizado, no el esquema, y la misma decisión vale para
  `properties.access_notes` y para cualquier texto de tercero, así que pertenece al change que
  traiga esa superficie.
- **El registro del intermediario guarda el token en claro.** La redacción se instala sobre el
  logger de acceso de la aplicación y sobre nada más, y aquí la URL **es** toda la credencial. En
  el despliegue de dev el público termina en un túnel de Cloudflare cuyo registro no configura ni
  desactiva nada de este repositorio. Ningún componente de este repositorio escribe el token en un
  log; confirmar la retención del URI completo en esa cuenta es **requisito previo de
  `guest-portal-web`**, que es quien hace la superficie realmente navegable. Hoy nada la ejerce.
- **Los `description` de los esquemas de respuesta publican referentes internos.** Un docstring de
  modelo Pydantic es el `description` del esquema en `/openapi.json`, que es anónimo. Varios
  esquemas de respuesta nombran ficheros de test e identificadores de proceso. No hay presupuesto,
  ni enumeración de causas de rechazo, ni oráculo, así que lo que se filtra es estructura del
  repositorio: arreglarlo es una pasada de convención sobre todos los esquemas publicados del
  backend.
- **`reservations.property_id` no acopla el tenant.** El invariante que falta, para quien lo
  recoja: *la propiedad de una reserva pertenece al tenant de la reserva*. La clave ajena es plana
  —sin la clave compuesta que sí tienen `guest_access_tokens.reservation_id` y
  `reservations.guest_id`—, así que la fila incoherente es representable. Sus escritores son el
  CRUD de reservas y el sync del PMS, no esta capacidad; lo que sí era problema de aquí es el
  lector, y está cerrado con el filtro explícito. **La clave ajena no sostiene el invariante, así
  que el filtro va en la query.**
- **El cliente de Redis cacheado en un global cruza bucles de eventos.** Un test que llegue a una
  ruta con la dependencia real deja un cliente atado a *su* bucle y el siguiente muere. La
  reparación —una fixture `autouse` que lo cierre, o el equivalente de `NullPool` para Redis— es
  infraestructura de test compartida por todas las suites. Ningún test de ruta de esta capacidad
  pide el Redis real.

## Key files

- `backend/app/guests/domain/portal_token.py` — generación y hash del token.
- `backend/app/guests/domain/portal_authorisation.py` — la regla de vigencia, pura.
- `backend/app/guests/domain/portal_ports.py` — `GuestAccessToken`, `StayInfo`, `GuestSession` y
  los puertos.
- `backend/app/guests/application/portal.py` — `GuestPortalAuthenticator` y los casos de uso de
  consulta, check-in, emisión y revocación.
- `backend/app/guests/api/portal_router.py`, `portal_schemas.py`, `portal_dependencies.py` — las
  cuatro rutas anónimas y su cableado.
- `backend/app/guests/api/router.py`, `errors.py` — las dos rutas de operador y la traducción del
  conflicto de emisión.
- `backend/app/guests/infrastructure/portal_repositories.py` — los adaptadores, incluida la
  consulta sin scope y la proyección de la estancia.
- `backend/app/guests/infrastructure/portal_throttle.py` — los dos límites.
- `backend/app/guests/application/use_cases.py` — `GuestActor` y el escritor único del documento.
- `backend/app/maintenance/{domain/repositories.py,application/use_cases.py,infrastructure/repositories.py}`
  — el `application/` nuevo de `Incident`.
- `backend/app/audit/domain/{actions.py,value_objects.py,services.py}` — vocabulario, campos
  redactados y la invariante del actor.
- `backend/app/core/log_redaction.py` — el filtro de redacción de rutas.
- `backend/alembic/versions/e7a3c419d82b_guest_portal_api.py` — la tabla, la columna de auditoría
  y el valor de enum.
- `docs/guest-portal.md` — operación y diagnóstico.
