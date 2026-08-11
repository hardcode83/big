# Proposal: auth-account-recovery

## Why

Hoy la única vía de recuperación del producto es que un administrador llame a
`POST /api/v1/users/{id}/reset-password`, un endpoint que `user-management` añadió fuera de
PRD §23 **precisamente porque este change no existía** (`specs/user-management.md`, «Reset de
contraseña asistido»). Eso deja dos agujeros concretos, no hipotéticos:

1. **El único `TENANT_OWNER` activo de un tenant no tiene recuperación posible.** Solo
   `TENANT_OWNER` tiene `MANAGE_USERS`: el `PROPERTY_MANAGER` recibe `403` en toda mutación,
   y `CLEANER`/`TECHNICIAN`/`SUPER_ADMIN` en los ocho endpoints. Quien pierda esa contraseña
   necesita autenticarse para resetearse a sí mismo, que es justo lo que no puede hacer. El
   bootstrap tampoco sirve: es idempotente y **no modifica** un usuario que ya existe. La
   salida real es SQL a mano contra la base de datos — con el tenant de MVP (dos usuarios:
   `TENANT_OWNER` y `PROPERTY_MANAGER`), ese es el estado de partida.
2. **La contraseña temporal es permanente.** `user-management` la genera en el alta y en el
   reset y la devuelve una vez, pero nada obliga a cambiarla: sobrevive hasta que un
   administrador la rote. Su propia spec registra la deuda y le asigna aquí su casa —
   «Exige una columna `must_change_password` y un endpoint de autoservicio, que pertenecen a
   `auth-account-recovery`».

PRD §24 lista `/forgot-password` como **opcional MVP**, y la entrada del roadmap acota la
prioridad de forma explícita: estar registrada no desplaza las prioridades operacionales de
PRD §30. Esto no es una capability nueva del producto, es cerrar el autoservicio de una
capacidad ya viva.

### Premisa verificada antes de escribir: la última milla no existe todavía

La entrada del roadmap dice que este change «depende del `NotificationAdapter`, que llega en
`access-notifications`». Ese puerto **ya está vivo** (`specs/access-notifications.md`), pero
verificado contra el código, lo que hay detrás no entrega nada a una persona:

- **No hay adapter real de envío.** `EMAIL` y `CONSOLE` resuelven a `ConsoleEmailAdapter`;
  SMTP real está asignado a `hardening-release`.
- **Y el adapter de consola no imprime el mensaje**: la spec le prohíbe registrar contenido y
  destinatario — solo canal y **longitudes** de `subject`/`body`, porque ese campo lleva el
  contacto del huésped. Así que ni siquiera en dev se puede leer el enlace desde el log.

Consecuencia, declarada aquí y no descubierta en `run`: **el correo de recuperación no llega a
ningún sitio recuperable hasta que exista un adapter SMTP real**. No invalida el change —
R1 y R5 son autoservicio puro y no tocan el emisor, y R2/R3 dejan el flujo completo, probado y
listo para el día que el adapter aterrice— pero sí obliga a que el change entregue una vía de
operación honesta en lugar de fingir una entrega (R6), y a que la promesa «el propietario
bloqueado se recupera solo» **no se dé por cerrada** al archivar. El resto del producto está en
la misma situación (asignaciones de limpieza y escalados de SLA también van a consola), con una
diferencia que sí importa: aquellas tienen la bandeja in-app como red, y un usuario que no puede
autenticarse no tiene bandeja.

## What changes

Después de este change existirán tres endpoints nuevos bajo `/api/v1/auth/` —cambio de
contraseña por el propio usuario (autenticado), solicitud de recuperación (anónima) y consumo
del token de recuperación (anónimo)—, una tabla nueva de tokens de recuperación con su
migración de Alembic, una columna `users.must_change_password` que convierte la contraseña
temporal de `user-management` en algo que hay que cambiar antes de operar, una política de
contraseña que hoy no existe en ninguna parte, y un decimoséptimo `NotificationType` para el
aviso. Todo dentro del módulo `app/auth/`, sobre los mecanismos que `auth-tenancy` ya montó:
el hasher bcrypt en hilos, el throttle de Redis, la revocación de familias de refresh y la
razón `PASSWORD_RESET` que `user-management` ya añadió al enum. Sin frontend.

## Requirements

### R1 — Cambio de contraseña por el propio usuario

**As a** usuario autenticado de cualquier rol, **I want** cambiar mi contraseña presentando la
actual, **so that** no dependa de un administrador para rotar mi credencial.

Acceptance criteria:

1. WHEN se envía a `POST /api/v1/auth/change-password` un token de acceso válido, la
   contraseña actual correcta y una contraseña nueva que cumple la política, THE SYSTEM SHALL
   reemplazar el hash almacenado y responder `204`.
2. IF la contraseña actual presentada no coincide, THEN THE SYSTEM SHALL responder `401` con
   `{"error": {"code": "INVALID_CREDENTIALS", ...}}` y SHALL NOT modificar el hash.
3. WHEN el cambio tiene éxito, THE SYSTEM SHALL revocar **todas** las familias de refresh del
   usuario con razón `PASSWORD_RESET`, incluida la de la sesión que hizo la llamada: un cambio
   de contraseña que deja vivas las sesiones anteriores no rota la credencial, solo añade una.
4. THE SYSTEM SHALL exigir el permiso `MANAGE_OWN_SESSION` —autoservicio que PRD §6 concede a
   todo rol que puede autenticarse— y SHALL NOT permitir que la petición nombre a otro usuario:
   el sujeto se deriva del token y el esquema es `extra="forbid"`.
5. IF la contraseña nueva no cumple la política de R1.6, THEN THE SYSTEM SHALL responder `422`
   nombrando qué regla incumple, sin devolver ni registrar la contraseña presentada.
6. THE SYSTEM SHALL fijar una política de contraseña —longitud mínima y tope de **72 bytes en
   UTF-8**— y SHALL aceptar sin excepción toda contraseña que genera
   `app/auth/domain/passwords.py`: su alfabeto sin caracteres ambiguos y su garantía de una de
   cada clase existen, según `specs/user-management.md`, exactamente para que este change no
   acabe rechazando lo que aquel sistema emite. El tope no es cosmético: `auth-tenancy` rechaza
   al crear el hash toda contraseña de más de 72 bytes en vez de truncarla, así que sin
   validación en el borde eso sale como error no mapeado en lugar de como `422`.
7. IF la contraseña nueva es idéntica a la actual, THEN THE SYSTEM SHALL responder `422`: un
   cambio que no cambia nada revoca todas las sesiones del usuario sin rotar credencial alguna.
8. WHILE la cuenta está bloqueada por acumulación de fallos, THE SYSTEM SHALL rechazar la
   petición **sin verificar** la contraseña presentada; y IF la contraseña actual presentada no
   coincide, THEN THE SYSTEM SHALL contabilizar el fallo en el **mismo** contador por cuenta que
   `login` (`login:fail:<uid>`), de modo que el bloqueo de 10 fallos de `auth-tenancy` cubra
   también esta vía.

   **Criterio añadido en `run` (2026-08-10), no en `new`**: lo levantó el panel de seguridad de
   la sección 4 y lo aprobó Jose. La propuesta original no decía nada de throttling aquí, con el
   razonamiento de que el llamante ya está autenticado y por tanto el presupuesto por IP de
   `login`/`refresh` no aplica. Eso era cierto sobre la **clave** del contador y falso sobre la
   conclusión: el presupuesto tiene que existir, pero por `user_id`. Sin él, este endpoint
   verifica una credencial igual que `login` pero **más barato para el atacante** —sin bloqueo,
   sin contador y sin rastro—, y eso abre dos agujeros concretos: (a) quien robe un token de
   acceso de 15 minutos puede convertirlo en la contraseña real probándola bcrypt a bcrypt, y
   cualquier rol autenticado sirve porque `MANAGE_OWN_SESSION` lo tienen todos; (b) un bucle de
   contraseñas deliberadamente erróneas retiene todas las plazas del `CapacityLimiter` de bcrypt
   —que es **compartido con `login`**— sin revocar las sesiones del atacante, así que degrada el
   login de todo el mundo sin necesidar credencial robada alguna. Es la regla 7 de
   `steering/security.md` («bloqueo tras 10 fallos») aplicada a todo camino que verifica una
   contraseña, no sólo al anónimo.

   **Lo que este criterio NO cierra, dicho aquí para que no se lea como más de lo que es**: el
   contador sólo avanza cuando la verificación falla, así que quien conoce una contraseña válida
   —la suya— sigue pudiendo quemar un bcrypt por petición indefinidamente mandando una
   contraseña nueva que incumple la política. No obtiene credencial alguna, pero degrada el
   `CapacityLimiter` compartido con `login` igual que el escenario (b). El residuo está medido y
   registrado en D14, junto con lo único que lo cerraría —un presupuesto por usuario y por
   minuto, ofrecido y descartado— y con el motivo por el que no se mitiga con un reordenamiento.

### R2 — Solicitud de recuperación, anónima e indistinguible

**As a** usuario que ha perdido su contraseña, **I want** pedir un enlace de recuperación con
solo mi email, **so that** no dependa de que otra persona del tenant pueda resetearme.

Acceptance criteria:

1. WHEN se envía a `POST /api/v1/auth/forgot-password` un email cualquiera, THE SYSTEM SHALL
   responder `202` con un cuerpo fijo que no describe el resultado.
2. IF el email normalizado no corresponde a ninguna cuenta, o el usuario no está `ACTIVE`, o su
   tenant no está `ACTIVE`, THEN THE SYSTEM SHALL responder **exactamente la misma** respuesta
   —código, cuerpo y cabeceras— que en el caso con cuenta, y SHALL NOT emitir token ni escribir
   fila alguna en `notification_logs`. Es el mismo criterio con el que `auth-tenancy` hace
   indistinguibles los cinco motivos de fallo del login, y por el mismo motivo: la alternativa
   es un enumerador de usuarios anónimo y expuesto a internet.
3. THE SYSTEM SHALL resolver la cuenta por `find_by_email_globally`, que sigue siendo la única
   consulta sin scope de tenant del sistema (ADR 0005), y SHALL derivar el `tenant_id` de la
   fila encontrada — nunca del cuerpo de la petición, que no lo admite.
4. THE SYSTEM SHALL contabilizar cada llamada en el **mismo** contador por IP que `login` y
   `refresh` (`login:ip:<ip>`, 10/min) y SHALL NOT darle presupuesto propio, respondiendo `429`
   con `RATE_LIMITED` antes de resolver el email. Partir el presupuesto permitiría gastar dos
   desde una misma dirección, que es literalmente el razonamiento con el que `auth-tenancy`
   metió `refresh` en el contador de `login`.
5. THE SYSTEM SHALL acotar además cuántos enlaces vivos puede acumular **una misma cuenta**,
   de modo que la dirección de una víctima no pueda inundarse desde IPs distintas, y SHALL
   aplicar esa cota sin que el resultado sea observable en la respuesta (R2.2 sigue mandando).
   WHEN la cuenta ya está en la cota, THE SYSTEM SHALL **revocar el enlace vivo más antiguo y
   emitir el nuevo**, en lugar de descartar la solicitud; y SHALL NOT revocar un enlace vivo
   **más joven que un margen de gracia corto**, descartando la solicitud en silencio cuando
   todos los vivos estén dentro de ese margen.

   **Segunda mitad añadida en `run` (2026-08-10)**: lo levantó el panel de seguridad de la
   sección 6 y lo aprobó Jose. La redacción original —descartar la solicitud al alcanzar la
   cota— convertía la cota en un arma de doble filo: cualquiera que conozca una dirección gasta
   tres peticiones, dentro del presupuesto de 10/min por IP, y durante los 30 minutos de vida
   del token **toda recuperación real del titular devuelve el mismo `202` y no envía nada**.
   R2.2 garantiza que la víctima no recibe señal alguna, y recargando a medida que expiran la
   supresión es indefinida; la única salida era que un administrador emitiera una temporal. Es
   decir: la cota anulaba justo la capacidad que este change existe para dar. Revocando el más
   antiguo, una solicitud legítima **siempre gana**, el número de enlaces válidos que coexisten
   sigue acotado —que es una propiedad de seguridad por derecho propio— y el volumen de correo
   lo sigue acotando el presupuesto por IP.

   **Tercera parte, el margen de gracia, añadida en `run` (2026-08-10)** y aprobada por Jose: el
   mismo panel midió que revocar-el-más-antiguo, tal cual, quitaba dos propiedades que descartar
   sí daba. (a) Antes, al llegar a la cota no se enviaba nada, así que una cuenta recibía **como
   máximo `cota` avisos por ventana de vida del token, sin importar cuántas IPs preguntaran**;
   enviando siempre, el correo por cuenta pasa a ser 10/min × número de IPs — exactamente la
   inundación entre IPs que la cláusula de propósito de esta regla nombra, así que la frase de
   arriba sobre el presupuesto por IP era falsa: un presupuesto **por IP** no puede acotar un
   total **por cuenta**. (b) Un atacante sostenido a ~3 peticiones/minuto retiraba el enlace
   recién enviado al titular en unos 20 segundos, con lo que el titular pasaba de no recibir
   correo a recibir correo cuyo enlace ya no sirve. El margen cierra las dos con un solo
   mecanismo: el enlace del titular es irrevocable durante la ventana en que lo va a pulsar, y el
   correo por cuenta vuelve a estar acotado a `cota` por ventana de gracia.
6. THE SYSTEM SHALL registrar el intento en el log de la aplicación en inglés, con el resultado
   y sin el email, sin el token y sin ninguna forma reversible de ninguno de los dos.

### R3 — Consumo del token de recuperación

**As a** usuario que recibió el enlace, **I want** fijar una contraseña nueva presentando el
token una sola vez, **so that** recupere el acceso sin que el enlace quede utilizable después.

Acceptance criteria:

1. WHEN se presenta a `POST /api/v1/auth/reset-password` un token válido, no usado, no expirado
   y no revocado junto a una contraseña que cumple la política de R1.6, THE SYSTEM SHALL
   reemplazar el hash del usuario y responder `204`.
2. THE SYSTEM SHALL decidir quién consume un token con **una única sentencia condicional**
   (`UPDATE … WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > now`) comprobando
   `rowcount`, exactamente como `auth-tenancy` resuelve la rotación de refresh: separar la
   comprobación de la escritura dejaría que dos presentaciones simultáneas resetearan las dos.
3. IF el token no existe, ya se usó, expiró, fue revocado, o su usuario o su tenant dejaron de
   estar `ACTIVE`, THEN THE SYSTEM SHALL responder un error único e indistinguible entre esos
   casos y SHALL NOT modificar el hash.
4. THE SYSTEM SHALL fijar una vida corta y configurable para el token (por defecto, del orden de
   los minutos, no de los días) y SHALL emitirlo con entropía criptográfica generada por
   `secrets`, nunca derivada de datos de la cuenta.
5. WHEN un reset se completa, THE SYSTEM SHALL (a) revocar todas las familias de refresh del
   usuario con razón `PASSWORD_RESET`, (b) invalidar **los demás tokens de recuperación vivos**
   de esa cuenta, y (c) poner a cero el contador de fallos de login y levantar el bloqueo por
   cuenta si lo hubiera. Sin (c) la recuperación no recupera nada: 10 intentos fallidos son
   justo lo que precede a un «he perdido la contraseña», y el bloqueo de 15 minutos seguiría
   rechazando el login inmediatamente posterior con el mismo `401` genérico.
6. THE SYSTEM SHALL NOT emitir tokens de sesión en la respuesta del reset: el usuario se
   autentica después por `POST /api/v1/auth/login`. Un reset que además inicia sesión convierte
   la posesión del enlace en una sesión sin volver a presentar credencial.
7. THE SYSTEM SHALL aplicar a este endpoint el mismo contador por IP de R2.4, comprobado
   **antes** de resolver el token presentado.

### R4 — El token no persiste en claro en ningún sumidero

**As a** responsable de la seguridad del producto, **I want** que un volcado de la base de
datos, del log o del rastro de auditoría no contenga ningún enlace de recuperación utilizable,
**so that** el token sea una credencial de un solo uso y no un secreto almacenado.

Acceptance criteria:

1. THE SYSTEM SHALL almacenar el token de recuperación de forma que la fila **no permita
   reconstruirlo**, y SHALL NOT persistirlo en claro en ninguna columna.
2. THE SYSTEM SHALL NOT escribir el token, ni el enlace que lo contiene, en
   `notification_logs.subject` ni en `notification_logs.body`. La regla 11 de
   `steering/security.md` es explícita: esas dos columnas tienen **una excepción y solo una**,
   la forma enmascarada `****XX` de un código de acceso, y un token de recuperación no es eso.
   **Esta es la restricción más dura del change y la que el diseño tiene que resolver**, porque
   el emisor de `access-notifications` entrega leyendo esas mismas columnas: cómo llega el
   enlace a la persona sin quedar escrito ahí es una decisión de `/sdd:design`, no de esta
   propuesta.
3. THE SYSTEM SHALL NOT escribir el token ni la contraseña —nueva o presentada— en el log de la
   aplicación, en `audit_logs.changes`, en ningún `TimelineEvent` ni en ninguna respuesta de la
   API, en ninguna forma reversible ni enmascarada.
4. THE SYSTEM SHALL registrar en `AuditLog` que hubo una recuperación —quién y cuándo— con el
   vocabulario cerrado de acciones y a través de `ChangeSet`/`AuditLogFactory`, de modo que la
   entrada no pueda transportar el secreto por construcción (regla 9 y regla 11).
5. THE SYSTEM SHALL traer un test propio que demuestre R4.1-R4.3 en rojo antes de darlos por
   buenos: el contrato de sumideros de la regla 11 lo hereda «el change que primero escribe en
   cada una, con su propio test», y aquí el escritor nuevo es este.

### R5 — La contraseña temporal deja de ser permanente

**As a** administrador que da de alta a una limpiadora, **I want** que la temporal que le
entrego solo sirva para entrar y cambiarla, **so that** una credencial que viajó por WhatsApp no
se quede siendo la contraseña de esa cuenta para siempre.

Acceptance criteria:

1. THE SYSTEM SHALL añadir `users.must_change_password` (booleano, por defecto falso) con su
   migración de Alembic, y SHALL mutarlo únicamente a través de un método de la entidad `User`
   — el test que deriva de `User.__dataclass_fields__` el conjunto de campos mutables exige uno
   por campo, y ese test **nombra literalmente `must_change_password`** como el caso que vendría
   después (`backend/tests/auth/test_entities.py:313`).
2. WHEN `user-management` crea un usuario o completa un reset asistido, THE SYSTEM SHALL dejar
   `must_change_password` en verdadero: son sus dos caminos de contraseña temporal.
3. WHEN el propio usuario completa R1 o R3, THE SYSTEM SHALL dejarlo en falso.
4. WHILE `must_change_password` es verdadero, THE SYSTEM SHALL responder `403` con un código
   propio y accionable (`PASSWORD_CHANGE_REQUIRED`) a toda petición autenticada salvo
   `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` y `POST /api/v1/auth/change-password`.
5. THE SYSTEM SHALL seguir emitiendo el par de tokens en un login con la temporal: sin sesión no
   hay forma de llamar al endpoint de cambio, y bloquear el login dejaría la cuenta muerta en
   vez de acotada.
6. THE SYSTEM SHALL exponer el flag en `GET /api/v1/auth/me`, de modo que el frontend pueda
   redirigir sin adivinar.

### R6 — La entrega, y lo que hoy no puede prometer

**As a** operador del producto, **I want** que el aviso de recuperación use el emisor que ya
existe y que su límite real esté declarado, **so that** nadie dé por funcionando un correo que
no llega a nadie.

Acceptance criteria:

1. THE SYSTEM SHALL añadir un decimoséptimo `NotificationType` para este aviso, declarándolo
   como divergencia de los dieciséis de PRD §14 igual que `access-notifications` declaró sus dos
   jobs frente a los cuatro de PRD §8.3.
2. THE SYSTEM SHALL emitir la fila sin `sla_deadline_at`, de modo que `escalation_for` devuelva
   `None` y el job de SLA no la escale: no hay plazo que incumplir en una recuperación.
3. THE SYSTEM SHALL escribir la fila con el `tenant_id` de la cuenta resuelta y su
   `recipient_user_id`, y SHALL apoyarse en el `NotificationLogRepository.add` existente sin
   ensanchar el puerto.
4. THE SYSTEM SHALL marcar `EXTERNAL_DEPENDENCY` la ausencia de adapter SMTP real y SHALL
   declarar en `specs/` y en `docs/` que, hasta que llegue con `hardening-release`, el aviso
   **no alcanza a la persona**: el `ConsoleEmailAdapter` no registra ni el contenido ni el
   destinatario, por prohibición expresa de `specs/access-notifications.md`.
5. THE SYSTEM SHALL documentar, mientras esa dependencia siga abierta, el procedimiento de
   operación que sí recupera un `TENANT_OWNER` bloqueado, para que la salida no siga siendo SQL
   improvisado. Cuál es —y si toca o no al `ConsoleEmailAdapter` para dev— lo decide
   `/sdd:design`; lo que esta propuesta fija es que el change **no se archiva sin una**.
6. THE SYSTEM SHALL reservar por nombre y sin valor en `.env.example` lo que un SMTP real
   necesitará (regla 8 de `steering/security.md`), sin introducir ningún secreto en el
   repositorio.

## Out of scope

- **La página `/forgot-password` y la pantalla de cambio de contraseña** (PRD §24): este change
  es `[BE]`. El frontend va con `dashboard-web` / `hardening-release`, que es donde
  `specs/user-management.md` ya sitúa el resto de sus pantallas.
- **El adapter SMTP real** y las credenciales de un proveedor de correo: asignado a
  `hardening-release` por `specs/access-notifications.md`. Aquí solo se reservan los nombres.
- **Endpoint de desbloqueo de cuenta para administradores**: el bloqueo de `auth-tenancy` es
  temporal y configurable (15 min por defecto) y su propia spec declara que por eso no hace
  falta. R3.5 levanta el bloqueo como efecto de una recuperación completada, que es distinto.
- **Segundo factor, magic links y política de expiración periódica de contraseñas**: nada en el
  PRD los pide y ninguno es necesario para cerrar el autoservicio.
- **Cambio del propio email**: es identidad de login (ADR 0005) y hoy vive en
  `PATCH /api/v1/users/{id}`, administrado. Moverlo a autoservicio es otra decisión.
- **Recuperación para huéspedes**: el portal de huésped usa token opaco por estancia y es
  `guest-portal-api`.
- **`AuditLog` retroactivo** de otras capacidades: sigue siendo la deuda que
  `specs/user-management.md` dejó accionable.

## Affected specs

- `sdd/specs/auth-account-recovery.md` — *(no existe aún — se creará al archivar)*
- `sdd/specs/auth-tenancy.md` — deja de ser cierto que la capacidad excluye «recuperación de
  contraseña por el propio usuario»; se amplían el contrato de endpoints anónimos, el catálogo
  de lo que cuenta contra el contador por IP y la política de contraseña.
- `sdd/specs/user-management.md` — cierra dos entradas de su «Estado y deuda conocida»: la
  temporal que no se fuerza a cambiar, y el reset asistido como única vía de recuperación.
- `sdd/specs/access-notifications.md` — nuevo escritor de `notification_logs` y decimoséptimo
  `NotificationType`.
- `sdd/steering/security.md` — la tabla de sumideros de la regla 11 gana un escritor nuevo si
  el diseño acaba tocando `notification_logs.subject`/`body`; si no lo toca, la tabla se queda
  como está y eso también se registra.
