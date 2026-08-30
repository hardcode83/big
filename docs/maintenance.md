# Mantenimiento — cómo se opera

Capability del change `maintenance` (PRD §12, §26.11). Esta página cuenta **cómo se usa y se
opera**; el *qué hace* está en `sdd/specs/maintenance.md` con sus criterios EARS, y el
contrato HTTP en `backend/openapi.json`.

## El ciclo, de principio a fin

```
alguien reporta una avería            (el portal del huésped, la limpiadora,
                                       una conversación, o `make seed-demo`)
        │
        ▼
incidencia OPEN, sin categoría ni severidad
        │  classify_incidents (cada 5 min)  ── o ──  POST /incidents/{id}/classify
        ▼
   ¿confianza ≥ ai_confidence_threshold?
        │
        ├── sí ──► CLASSIFIED, con categoría y severidad
        │            │  si severidad HIGH/CRITICAL:
        │            ├─► propiedad → MAINTENANCE_REQUIRED | CRITICAL_INCIDENT
        │            └─► notificación a los managers (INCIDENT_CREATED_CRITICAL | _HIGH)
        │
        └── no ──► sigue OPEN, con `ai_classification` escrita
                     (queda para triaje humano, y el job ya no vuelve a preguntar)
        ▼
el manager tría          PATCH /incidents/{id}     categoría, severidad, coste estimado
        │                                        si la deja HIGH/CRITICAL y aún no se avisó:
        │                                        + notificación a los managers
        │
        ├── coste ≤ umbral del tenant ──────────► sigue el flujo
        └── coste > umbral ─────────────────────► AWAITING_OWNER_APPROVAL
                                                   + OwnerApproval PENDING (related_type=INCIDENT)
                                                   + notificación a la propietaria
        ▼
la propietaria responde  POST /owner-approvals/{id}/respond
        ├── APPROVED ──► vuelve a CLASSIFIED, con `approved_cost` fijado
        └── REJECTED ──► CANCELLED, y la propiedad se recompone
        ▼
el manager asigna        POST /incidents/{id}/assign   → ASSIGNED
                                                        + notificación al técnico
                                                        + plazo de SLA según la severidad
        ▼
                                                        (si vence: TECHNICIAN_NO_RESPONSE
                                                         a los managers)
el técnico acepta        POST /incidents/{id}/accept   → ACCEPTED  (cancela el plazo)
                                                       { "eta_at": … } opcional
el técnico rechaza       POST /incidents/{id}/reject   → CLASSIFIED (cancela el plazo)
                                                       + notificación al manager
                                                       borra asignatario, ETA y nota
va de camino             POST /incidents/{id}/en-route → IN_PROGRESS
                                                       { "eta_at": … } opcional
espera piezas            POST /incidents/{id}/wait-parts → WAITING_EXTERNAL_PARTS
reanuda                  POST /incidents/{id}/resume   → IN_PROGRESS
        ▼
cierra                   POST /incidents/{id}/resolve  { "final_cost": …,
                                                         "materials": … opcional }
        │
        ├── coste cubierto o bajo umbral ──────► RESOLVED, con `resolved_at`
        │                                        propiedad recompuesta
        └── coste > umbral y sin cubrir ───────► AWAITING_OWNER_APPROVAL, **sin** resolver
                                                 + OwnerApproval (related_type=MAINTENANCE_COST)
                                                 aprobada → vuelve a IN_PROGRESS y reintenta
```

Ninguna de esas flechas de estado de propiedad la escribe este módulo por su cuenta: todas
pasan por `PropertyStateMachine`, que es el único sitio donde ocurre una transición
(`sdd/steering/architecture.md`).

## Las dos puertas de la propietaria, y por qué son dos

PRD §12 pone el umbral sobre el **coste estimado**. Si sólo existiera esa puerta, estimar
90 € y gastar 500 se saltaría la regla de aprobación entera, así que hay una segunda sobre el
**coste real** al cerrar. Se distinguen por el `related_type` de la aprobación, que es también
lo que decide a dónde vuelve la incidencia cuando la propietaria dice que sí:

| `related_type` | Quién la abrió | Vuelve a |
|---|---|---|
| `INCIDENT` | el triaje, con un `estimated_cost` por encima del umbral | `CLASSIFIED` |
| `MAINTENANCE_COST` | el cierre, con un `final_cost` por encima del umbral y sin cubrir | `IN_PROGRESS` |

«Cubierto» significa que la incidencia ya lleva un `approved_cost` **mayor o igual** que el
coste final. Una aprobación de 450 € no estira para una factura de 500 €.

Al aprobar el coste real el sistema **no cierra la incidencia**: la devuelve a `IN_PROGRESS`
y el técnico repite el cierre. Cerrarla por él haría que `resolved_at` dejara de significar
«lo dio por terminado».

## Quién puede hacer qué

| | propietaria | manager | técnico | limpiadora |
|---|---|---|---|---|
| Ver incidencias | ✔ | ✔ | ✔ sólo las suyas | — |
| Ver el contexto de una incidencia (a qué piso y cómo entrar) | ✔ | ✔ | ✔ sólo las suyas | — |
| Clasificar, triar, asignar, cancelar | — | ✔ | — | — |
| Aceptar, empezar, esperar piezas, reanudar, resolver | — | ✔ | ✔ sólo las suyas | — |
| Ver las fotos de una incidencia | ✔ | ✔ | ✔ sólo las suyas | — |
| Subir fotos a una incidencia (antes / después) | — | ✔ | ✔ sólo las suyas | — |
| Responder una aprobación | ✔ | — | — | — |
| Abrir una incidencia desde su propia limpieza | — | — | — | ✔ |

Tres cosas que no se ven en la tabla y conviene saber:

- **El técnico sólo ve y opera las suyas**, y eso no es un filtro que la petición pida: sale
  del rol del token. Una incidencia asignada a otro técnico devuelve el **mismo `404`** que
  una que no existe — con el mismo cuerpo —, para que el endpoint no sirva de sonda.
- **El manager también puede conducir el ciclo del técnico**, para desatascar. Es la única
  diferencia con limpieza, donde ejecutar es sólo de la limpiadora.
- **La limpiadora abre incidencias y no lee ninguna**, y esa fila de la tabla es toda su
  relación con este módulo. Las quince rutas de `/api/v1/incidents` le siguen respondiendo `403`;
  lo que puede hacer vive en otro sitio y se describe abajo. **Con una señal indirecta que
  conviene no negar**: al cerrar su limpieza puede recibir un `409` que le dice que en esa
  vivienda hay una incidencia `CRITICAL` sin resolver. Es un bit —existe o no—, sin id, sin
  título y sin descripción, y está descrito en [`cleaning.md`](cleaning.md).

## Reportar una incidencia desde una limpieza

`POST /api/v1/cleaning-tasks/{task_id}/incidents` — PRD §11 la pide entre los nueve elementos de
la app de la limpiadora y PRD §12 la lista como una de las cinco fuentes de creación.

**Cuelga de la tarea de limpieza, no de la incidencia**, y por eso la ruta no está bajo
`/api/v1/incidents`: el sujeto es la limpieza que está haciendo. Este módulo sigue sin exponer
ninguna ruta de creación propia.

Cómo se opera, y qué decide el sistema en lugar de quien llama:

- El cuerpo son **exactamente dos campos**, `title` y `description`. Cualquier otro —
  `property_id`, `source`, `severity`, un coste— se rechaza con `422` en vez de ignorarse.
- La vivienda **sale de la tarea**, nunca de la petición. La incidencia queda sellada
  `source = CLEANER`, atribuida a su usuario y vinculada a esa limpieza.
- Nace `OPEN` y **sin clasificar**: el job de arriba le pone categoría y severidad en su
  siguiente vuelta, y desde ahí es del manager.
- Solo alcanza **sus propias tareas**, por el rol persistido del token y sin que ningún campo
  pueda ensancharlo. Una tarea inexistente, de otro tenant o de otra limpiadora dan el **mismo
  `404`**, con el mismo cuerpo.
- Se puede reportar mientras el trabajo está vivo — `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`. Sobre
  una tarea ya cerrada, rechazada o cancelada responde `409`: PRD §12 dice «durante checklist».
- La respuesta es un acuse de **tres campos** —`id`, `status`, `created_at`— y nada más. No
  devuelve la descripción: no hay nada que aprender de ella y es texto libre.

**Reportar no le bloquea cerrar la limpieza**, que es la duda inmediata en cuanto existe el botón.
La incidencia nace `MEDIUM` y el cierre solo lo frena una `CRITICAL` sin resolver **en la
vivienda**, así que empieza a bloquear si el clasificador la sube — o si ya había otra. El detalle
está en [`cleaning.md`](cleaning.md).

## Las fotos de la incidencia

`POST` y `GET /api/v1/incidents/{incident_id}/photos`. PRD §6 le concede al técnico «subir fotos
(antes y después)» y PRD §12 lo pide dos veces; esto es esa evidencia, y nada más. El *qué hace*
está en [`sdd/specs/incident-photos.md`](../sdd/specs/incident-photos.md).

**Dos etapas y sólo dos**: `BEFORE` (la de llegada) y `AFTER` (la de cierre). Es un enum cerrado,
no un texto: cualquier otro valor responde `422`. A diferencia de las fotos de limpieza, aquí no
hay plantilla que declare los tipos admisibles, así que el conjunto lo fija el dominio.

Cómo se opera:

- **Sube el técnico asignado**, y también el manager para desatascar. Se pide `EXECUTE_INCIDENTS`,
  el mismo permiso que el resto de su ciclo — no hay permiso nuevo. La propietaria **no** sube.
- **Lee quien puede leer la incidencia**: propietaria, manager y el técnico asignado
  (`READ_INCIDENTS`). Leer la evidencia es lo que hacen los dos primeros; subirla es del técnico.
- **Sólo mientras el trabajo está vivo**: con la incidencia en `IN_PROGRESS` o
  `WAITING_EXTERNAL_PARTS`. Sobre una incidencia esperando la aprobación de la propietaria, o ya
  resuelta o cancelada, responde `409` — con tres mensajes distintos, para que se sepa cuál de los
  tres casos es— y **no escribe nada**: ni fila ni objeto.
- **Varias fotos de la misma etapa valen.** Dos ángulos de la misma avería es el caso normal, no un
  error.
- **El formato se decide por los bytes**, nunca por lo que declare el cliente: fuera de la
  allowlist es `422`, y por encima de 10 MB es `413` (el mismo tope que las fotos de limpieza,
  aplicado **antes** de leer el cuerpo).
- **El listado va de la más antigua a la más reciente**, y cada foto llega con una `url` firmada
  **acuñada para esa respuesta**, con caducidad. No se guarda ni se comparte: cuando caduque, se
  vuelve a listar. La clave interna del objeto (`storage_key`) no sale en ningún cuerpo.
- Una incidencia inexistente, de otro tenant, o asignada a otro técnico dan el **mismo `404`**, con
  el mismo cuerpo, igual que el resto del módulo.

**La URL firmada se abre en el navegador sin sesión, y eso es a propósito.** Con el tenant en
`storage_type = LOCAL` los bytes los sirve `GET /api/v1/incident-photos/{photo_id}`, que es
**anónima**: un `<img src>` no manda cabecera `Authorization`, así que exigir el token haría la URL
inservible para lo único que existe. **La firma es la credencial** — cubre la clave completa, que
empieza por el `tenant_id`. Una firma inválida, caducada, manipulada o que nombre una foto que no
existe dan todas el **mismo `403`**, con el mismo cuerpo, para que la ruta no sirva de sonda de qué
fotos hay. Con el tenant en `S3` esa ruta responde `404`: el navegador va directo al proveedor.

Dos avisos para quien opera:

- **No hay borrado.** Ninguna ruta de la API borra una foto. Una subida por error se queda, y el
  único borrado que existe es el compensatorio interno cuando la transacción falla después de
  escribir el objeto. Habrá superficie de borrado cuando haya una decisión de retención, no antes.
- **Cerrar no exige foto.** `resolve` sigue pidiendo únicamente `final_cost`, así que una incidencia
  puede resolverse sin ninguna `AFTER`. Es una decisión, no un olvido: poner la puerta cambia la
  tabla de transiciones y el contrato publicado.

Cada subida deja su fila en `audit_logs` con actor e IP, contra la **propia foto** y no contra la
incidencia — y **sin** la clave de almacenamiento. No genera evento de timeline: el vocabulario de
PRD §10 no tiene un tipo para una foto de incidencia, y la subida de limpieza tampoco escribe uno.

## El job de clasificación

`classify_incidents` corre cada 5 minutos y recoge lo que esté en `OPEN` **y sin
`ai_classification`**. Ese par es toda la regla, y da las dos propiedades que hacen falta:

- una incidencia cuyo adaptador **falló** vuelve a entrar, porque no se escribió nada;
- una de **confianza baja** no vuelve, porque su `ai_classification` sí está escrita — un
  adaptador determinista respondería lo mismo para siempre y el job giraría en vacío.

No se clasifica dentro de la petición que crea la incidencia, y el motivo es de seguridad: el
único escritor de `incidents` en `OPEN` es hoy una petición **anónima desde internet**, y
colgar de ella la llamada al clasificador es la forma que prohíbe la regla 12(d) de
`sdd/steering/security.md`. Con un proveedor de IA real detrás del puerto sería además un
coste por petición que decide un tercero no autenticado.

El clasificador de desarrollo (`RuleBasedIncidentClassifier`) es determinista y funciona por
palabras clave en español e inglés. Lo que no reconoce lo deja por debajo del umbral, es
decir, para triaje humano.

**Lo que hay que saber el día que se enchufe un proveedor de IA real**: una incidencia cuya
clasificación **falla** conserva `ai_classification` a `NULL`, así que vuelve a entrar en cada
tick — para siempre, si el fallo es permanente. El trabajo por tick está acotado por
`NOTIFICATION_BATCH_SIZE` y por tenant, así que no crece con el número de incidencias que
abra un anónimo (regla 12(d)), pero una avalancha de reportes que el proveedor no sepa
clasificar se convierte en carga saliente permanente y acotada. Se ve en el contador
`failed` del informe del job.

## Qué se guarda de lo que escribe la gente

`incidents.title` y `description` son la prosa de quien reporta, y se guardan tal cual — es la
excepción 2 de la regla 11 de `sdd/steering/security.md`. **Lo que se escribe desde nuestro
código es otra cosa** y va en forma estructurada:

- `ai_summary` sale del vocabulario cerrado del adaptador, nunca del texto de entrada. Si un
  adaptador devuelve un resumen que comparte ocho caracteres seguidos con lo reportado, el
  campo se descarta.
- `ai_classification` guarda cinco claves cerradas: categoría, severidad, confianza, adaptador
  e instante.
- `owner_approvals.reason` es una constante más el id de la incidencia.

Ninguna de las cuatro entra en `audit_logs.changes` ni en el `metadata` del timeline.

**Conviene decírselo a quien opera**: si el huésped teclea su número de documento en la
descripción, ahí queda. Es texto que él eligió enviar, y lo verá el técnico que reciba el
parte — la cara simétrica de la advertencia que `docs/guest-portal.md` da sobre
`properties.access_notes`.

## La pantalla del técnico: a qué piso va y cómo entra

`GET /api/v1/incidents/{id}/context` es una proyección de solo lectura que responde las dos
preguntas que el parte de incidencia no contestaba. Existe porque el rol `TECHNICIAN` tiene cinco
permisos y `READ_PROPERTIES` no está entre ellos: hasta ahora recibía `property_id` como un UUID
pelado y las rutas de propiedades le contestaban `403`.

Devuelve once campos y ni uno más:

| | de dónde sale |
|---|---|
| nombre y código interno de la vivienda | la propiedad |
| dirección postal (calle, piso, ciudad, provincia, código postal, país) | la propiedad |
| zona horaria | la propiedad |
| instrucciones de acceso | la propiedad |
| la nota que el manager dejó al asignar | la incidencia |

Los cuatro primeros —nombre, código interno, país y zona horaria— siempre vienen. Los otros
siete pueden venir a `null`, y un `null` ahí significa que la columna no está rellena, **no** que
no se pudo resolver: si la propiedad de la incidencia no resuelve dentro del tenant, la respuesta
es un `404` y nunca un contexto a medias.

Quién la alcanza: el técnico **asignado**, y el manager o la propietaria para cualquier
incidencia de su tenant. Un técnico que no es el asignatario recibe el mismo `404` que si la
incidencia no existiera. La limpiadora recibe `403`.

Lo que esta ruta **no** lleva, y conviene saberlo porque es deliberado: la contraseña del WiFi en
ninguna forma, las notas de limpieza ni las de emergencia de la vivienda, y ningún dato de la
reserva — ni importe, ni canal, ni huésped. PRD §12 no pide la reserva en esta pantalla.

### Dos avisos para quien opera

- **Lo que se escriba en las instrucciones de acceso se le enseña al técnico asignado tal cual.**
  Igual que ya se le enseña al huésped (`docs/guest-portal.md`): es la misma columna. Si ahí hay
  un código de portal, lo verán los dos. Como contrapartida, esa columna **ha salido del listado
  paginado de propiedades** —`GET /api/v1/properties` ya no la devuelve, ni ella ni las notas de
  limpieza y emergencia—, así que dejó de existir la respuesta que traía las instrucciones de
  acceso de todas las viviendas de golpe. El detalle de una vivienda sí las sigue llevando.
- **La nota de asignación se sustituye en cada asignación.** Pertenece a la asignación vigente,
  no a la incidencia: si se reasigna la incidencia sin escribir nota, la anterior **se borra**.
  Es a propósito — enseñarle al técnico B lo que el manager escribió para el técnico A es peor
  que no enseñarle nada—, pero hay que saberlo antes de reasignar.

## La app del técnico

Desde `tech-app`, el rol `TECHNICIAN` tiene sus dos pantallas y deja de ver «En preparación».
Ambas están construidas **mobile-first**: una sola columna, tarjetas en vez de tabla y objetivos
táctiles de 44 px, porque se operan de pie y con una mano en el portal de un edificio. Ambas se
recorrieron en un navegador real contra un backend vivo el 2026-08-29, a 360×780: el ciclo entero
de una incidencia, las dos subidas de foto y el cierre con coste y materiales. A ese ancho
**ninguna de las dos pantallas produce desplazamiento horizontal** —cero elementos desbordados
dentro de su contenido— y los objetivos táctiles miden 44 px. La página sí desborda, pero por la
**cabecera del shell compartido**, que estas pantallas no controlan y que se comporta igual en
`/dashboard` (entrada de roadmap `shell-topbar-overflow-360`).

El *qué hace* —las dos superficies, el ciclo, la galería y la puerta de aprobación como requisitos
EARS— está en [`sdd/specs/tech-app.md`](../sdd/specs/tech-app.md). Esta página cuenta *cómo se
opera*; no duplica esa spec.

**`/tech` — mis incidencias.** Lista `GET /api/v1/incidents` **sin enviar ningún parámetro que
identifique al técnico**: el acotamiento por fila lo deriva el backend del token, y no existe
parámetro de consulta para él. Cada fila lleva título, severidad, estado, categoría, fecha y la
**vivienda** — el nombre y el código interno salen del contexto de esa incidencia, no de las rutas
de propiedades, que a este rol le contestan `403`. Seis chips filtran por estado, de uno en uno
(el contrato no admite varios), y volver a pulsar el chip activo quita el filtro. Sin filtro la
lista sale en el orden que sirve el backend y **incluye incidencias ya cerradas**, cosa que la
propia pantalla avisa. Un botón «cargar más» acumula páginas de veinte.

El contexto de cada fila se pide bajo **la misma clave** que usará el detalle, así que abrir una
fila no vuelve a pedirlo. Si el contexto de una fila falla, esa fila enseña `—` en vivienda y
código y la lista sigue en pie.

**`/tech/incidents/[id]` — el detalle.** Reúne la avería, el bloque de «dónde y cómo entrar», la
galería de fotos y las acciones. Un `404` de la incidencia **o** de su contexto se presenta como
«incidencia no disponible», sin distinguir si no existe, es de otro tenant o es de otro técnico:
el backend los hace indistinguibles a propósito.

**El ciclo desde el móvil.** La pantalla ofrece exactamente lo que el estado admite —`ASSIGNED`:
aceptar o rechazar; `ACCEPTED`: en ruta o rechazar; `IN_PROGRESS`: esperar piezas o cerrar;
`WAITING_EXTERNAL_PARTS`: reanudar— y en `AWAITING_OWNER_APPROVAL`, `RESOLVED` y `CANCELLED` no
ofrece ninguna y explica por qué. Al aceptar y al ir en ruta se puede adjuntar una **ETA
opcional**, que se lee en la zona horaria del dispositivo; en blanco no se manda nada. La zona
horaria de la vivienda se **muestra** junto a la dirección pero no reinterpreta lo que el técnico
teclea. Nada de esto es autorización: el backend refuta con `409` de todas formas, y cuando lo
hace la pantalla vuelve a leer la incidencia y explica la razón —cerrada, a la espera de la
propietaria, o fuera de secuencia— desde el estado **refrescado**, nunca desde el mensaje del
error, que viene en inglés.

**Rechazar es el caso aparte**: tras el `200` la asignación se ha borrado y la incidencia le
contesta `404` a quien la rechazó, así que la app lo devuelve a `/tech` en vez de recargar un
detalle que ya no puede leer.

**Las fotos antes/después.** La galería pinta cada URL firmada **tal cual**, agrupada por etapa;
no se guarda, ni se reescribe, ni se reconstruye, y cuando una firma caduca lo que se hace es
volver a listar —una vez por foto, no en bucle—. Subir se ofrece **sólo** en `IN_PROGRESS` y
`WAITING_EXTERNAL_PARTS`, con `stage` de dos valores y sin campo de texto libre. No hay
comprobación de tamaño ni de formato en el móvil: el backend decide leyendo los bytes, así que la
frontera son sus respuestas, y cada una tiene su mensaje —`409` por el estado, que además vuelve a
leer la incidencia: si el refresco la trae cerrada o a la espera de la propietaria, el formulario
de subida **se retira** y quien explica en qué se ha convertido es la barra de acciones;
`413` por tamaño,
`422` diciendo que se admiten JPEG, PNG y WebP (la causa frecuente es un HEIC de iPhone, y lo que
lo arregla es cambiar el formato, no reintentar) y `502` por el almacenamiento—. **No se puede
borrar una foto**, porque la API no lo expone, y **ninguna foto es requisito del cierre**.

**El cierre y la puerta de la propietaria, tal como se muestran.** En `IN_PROGRESS` el técnico
cierra declarando un **coste final obligatorio** y unos materiales opcionales. La app comprueba en
local lo justo para no emitir una petición inválida (obligatorio, ≥ 0, ≤ 99 999 999,99, dos
decimales) y un `422` del servidor se enseña **sin vaciar el formulario**.

Lo que pasa después lo decide el backend y la app se limita a enseñarlo. Si la respuesta vuelve
`RESOLVED`, la incidencia se presenta cerrada con su coste, sus materiales y su fecha. Si vuelve
`AWAITING_OWNER_APPROVAL`, la app dice explícitamente que **el cierre no se ha aceptado** y queda
a la espera de la propietaria, conserva visible el coste que devolvió la respuesta y **no inventa**
una fecha de resolución que llega a `null`. El umbral `owner_approval_threshold_eur` **no se
calcula, no se muestra y no se anticipa**: el rol no puede leer la configuración del tenant, y la
puerta la resuelve el backend al recibir el cierre. La app lo muestra; no lo predice ni lo evita.

## Enterarse de una incidencia grave sin abrir la pantalla

Hasta `notification-writers-gap` una incidencia crítica no avisaba a nadie: se escribía la
incidencia, su `AuditLog` y su `TimelineEvent`, y el manager sólo se enteraba si abría la
pantalla. Un huésped podía reportar una fuga desde el portal y nadie lo sabía. Ahora:

- Cuando una incidencia queda en `CRITICAL` o en `HIGH` —la clasifique el job automático o la
  corrija un humano en el triaje— se escribe un `INCIDENT_CREATED_CRITICAL` o un
  `INCIDENT_CREATED_HIGH` a cada manager activo, o a los owners si no hay ningún manager.
- **Una vez por incidencia y severidad.** Un triaje que confirma lo que ya dijo el clasificador no
  avisa dos veces. Pero una incidencia que **sube** de `HIGH` a `CRITICAL` sí manda el aviso
  crítico, aunque el de `HIGH` ya esté: son dos hechos distintos y el segundo es el urgente.
- **Una clasificación por debajo del umbral de confianza no avisa.** Ahí la incidencia se queda
  `OPEN` con su `MEDIUM` por defecto y sólo se escribe `ai_classification`: no hay severidad que
  anunciar, y el aviso llegará —si llega— cuando alguien la tríe.
- `MEDIUM` y `LOW` no avisan nunca. Avisar de cada incidencia convertiría la bandeja en ruido.
- El aviso se escribe en la misma transacción que la clasificación o el triaje, así que no hay
  ningún instante en el que la incidencia sea crítica y el aviso no exista.

**El plazo del técnico ya se llama por su nombre.** Cuando vence el SLA de un `TECHNICIAN_ASSIGNED`
sin respuesta, el escalado al manager llega como `TECHNICIAN_NO_RESPONSE` y no como el
`SLA_BREACH` genérico de antes, así que en la bandeja se distingue de una limpieza sin responder
sin abrir la fila que lo originó. Es un cambio de etiqueta: el destinatario y el motivo son los
mismos, y la llamada telefónica de PRD §14 sigue sin existir porque no hay `PhoneAdapter`. Las
filas `SLA_BREACH` escritas antes se quedan como están — no hubo migración.

**Efecto en el seed de demo**: `make seed-demo` ahora deja notificaciones escritas —una incidencia
grave y una limpieza cerrada—, de modo que la bandeja tenga algo que enseñar. Es deliberado.

## Rastro

Cada transición deja su fila en `audit_logs` y su hito en el timeline de la propiedad, en la
**misma transacción** que el cambio. Dos matices:

- La clasificación **automática** va sin actor (`actor_user_id` y `actor_ip` a `NULL`) y con
  actor `AI` en el timeline: la dispara el reloj, no una persona. Es la cuarta excepción
  nombrada de la regla 9. La clasificación manual de un manager sí lleva su actor.
- `WAITING_EXTERNAL_PARTS` **no genera evento de timeline**: el vocabulario de PRD §10 no
  tiene un tipo para esperar una pieza, y el hito ya lo cuenta el `status` de la incidencia.
  El coste asumido es que el timeline no explica por sí solo por qué una incidencia lleva
  días abierta; eso se ve en la incidencia.

## Lo que este change no trae

El `Expense` al resolver (es de `revenue`), la expiración automática de una aprobación, la
detección del intent desde la mensajería (`messaging-ai`) y la alerta de cerradura como fuente.
**La UI del técnico sí llegó**, con `tech-app`, y está descrita arriba. Cada uno tiene dueño declarado en el proposal del change. **Las fotos de la
incidencia sí llegaron**, con `incident-photos` (2026-08-23), y están descritas arriba: el patrón
fue el de `cleaning-photos-storage`, como estaba previsto, y la capa de servido firmado se extrajo
a `app/integrations/` para que los dos dominios la compartan en vez de duplicarla. Lo que **no**
trajeron es validación por IA de la foto (`ai_validation_result` sigue sin escritor) ni foto en el
alta de la incidencia: «fotos del incidente» de PRD §12 son las `BEFORE` que sube el propio
técnico, no las de quien reportó.

De la ruta de la limpiadora falta **su pantalla**: la API existe y el botón lo pone `cleaner-app`,
que declara `cleaner-incident-report` en su `needs`. Y ella sigue sin poder leer, listar ni seguir
lo que abrió: el acuse de tres campos es toda la lectura que tiene de una incidencia. Lo único que
aprende además es el bit del `409` de cierre —que en la vivienda hay una `CRITICAL` sin resolver—,
y se dice aquí porque «toda su lectura» a secas invita a tratar ese cuerpo como si no revelase
nada, que es justo el razonamiento con el que alguien lo ensancharía.

## Cómo se ven desde la web

La pantalla de **lista y detalle** de incidencias del workspace (`/incidents`,
`/incidents/[id]`) está disponible en modo solo lectura desde `incidents-web` (archivado
en `changes/archive/`). Cubre la consulta: la manager abre `/incidents`, filtra por `status`
y `severity`, paginacliente (`lastPage = max(1, ceil(total / perPage))`, porque el endpoint
no expone `total_pages`), y abre cada fila en `/incidents/[id]`. El detalle pinta los 20
campos de `IncidentResponse` — incluido `description` como **texto plano** (regla 11 de
`sdd/steering/security.md`: texto libre del huésped o de la limpiadora, nunca HTML) y
`assigned_technician_id` bajo una sección secundaria etiquetada con su nota de limitación
(no hay `GET /api/v1/users` en el contrato, así que el UUID no se resuelve a nombre aquí).

Quedan fuera de esa pantalla, hasta que lleguen sus entradas propias:

- Las **cuatro operaciones del manager** (`classify`, `triage` vía `PATCH`, `assign`, `cancel`),
  que llevan `MANAGE_INCIDENTS`. Las **seis de `EXECUTE_INCIDENTS`** —`accept`, `reject`,
  `en-route`, `wait-parts`, `resume` y `resolve`— ya no están fuera de la web: viven en la app del
  técnico descrita arriba, y de esta pantalla del workspace siguen ausentes. Cada una lleva su
  validación de transición (`IncidentAlreadyClosedError`, `InvalidIncidentTransitionError`,
  `IncidentBlockedByPendingApprovalError`) y su auditoría.
- **Responder una aprobación** (`POST /owner-approvals/{id}/respond`): la ruta `/approvals`
  sigue como `RoutePlaceholder` y la regla 11 ata esa pantalla a una decisión de UX sobre
  el flujo de la propietaria.
- **Selector de propiedad** y **resolución nombre↔id de `assigned_technician_id`**: ambos
  son `M` por derecho propio. No los desbloquea `tech-app`: la app del técnico resuelve **su**
  vivienda con `tech-incident-context`, que proyecta el contexto de una incidencia y no ofrece
  ningún catálogo con el que poblar un selector ni ninguna forma de resolver un UUID de usuario.
