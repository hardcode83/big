# Propiedades — cómo se operan

Cómo se da de alta, se corrige y se retira una vivienda, y las cosas que sorprenden al hacerlo.
El *qué hace* con sus criterios verificables vive en [`sdd/specs/properties-crud.md`](../sdd/specs/properties-crud.md); aquí no se repite.

## Por qué esto es lo primero

Hasta este change **no había ninguna forma de crear una propiedad**: ni endpoint, ni comando, ni
seed. La consecuencia era que `POST /api/v1/reservations` estaba implementado y probado y devolvía
`404` en todas las peticiones, porque no podía existir un `property_id` que citar. Lo mismo el
import CSV (resuelve por `internal_code`) y el sync del PMS (por `pms_external_id`).

Así que el orden operativo es: `make bootstrap` → login → **dar de alta las viviendas** → ya se
pueden crear reservas por cualquiera de las tres vías.

## Quién puede hacer qué

| Rol | Leer | Crear / editar |
|---|---|---|
| `PROPERTY_MANAGER` | sí | **sí** |
| `TENANT_OWNER` | sí | no |
| `CLEANER`, `TECHNICIAN`, `SUPER_ADMIN` | no (`403`) | no (`403`) |

**La propietaria no puede dar de alta su propia vivienda**, y es deliberado, no un descuido: PRD
§6 le concede «ver sus propiedades y reservas» y nada más, y es el mismo reparto que ya tiene
`reservations`. `make bootstrap` crea un `TENANT_OWNER` y un `PROPERTY_MANAGER`, así que el
recorrido no se bloquea — lo hace el manager. Si algún día se decide lo contrario, es un cambio de
`ROLE_PERMISSIONS` con su razón escrita, no una excepción puntual.

`SUPER_ADMIN` recibe `403` como en el resto del producto: no tiene ningún permiso con ámbito de
tenant, y la visibilidad cross-tenant está aplazada a la fase SaaS.

## Alta

`POST /api/v1/properties`. Solo `name` e `internal_code` son obligatorios; el resto toma los
valores por defecto del esquema (España, `Europe/Madrid`, 2 huéspedes, entrada 15:00, salida
11:00, estado `VACANT_READY`).

Dos choques posibles, ambos `409`:

- **`internal_code` repetido dentro del tenant.** Es el nombre con el que las personas se refieren
  a la vivienda (`REDES11`) y con el que el CSV la resuelve, así que no puede haber dos.
- **`pms_external_id` repetido *para el mismo proveedor*.** Ojo al matiz: **sí** puedes tener dos
  propiedades con el mismo id externo si están en proveedores distintos — es lo normal en un tenant
  a medio migrar de un PMS a otro. Lo que no puede haber son dos en el mismo proveedor, porque
  entonces el sync no sabría a cuál atribuir una reserva, y adjudicarla a cualquiera ataría a un
  huésped a la casa equivocada.

  **Consecuencia práctica**: el proveedor se elige **en el alta y no se cambia después**. `PATCH`
  no acepta `pms_provider` — enviarlo da `422`, no un `200` silencioso—, así que si vas a poner una
  propiedad en un proveedor concreto, indícalo al crearla.

  Mover una vivienda de proveedor no es un cambio de columna cualquiera: el índice agrupa por
  `coalesce(pms_provider, 'MOCK')`, de modo que trasladarla puede chocar con otra que hoy comparte
  legítimamente su id externo. Eso necesita su propia operación con su propio manejo de conflicto,
  y ninguna capability la pide todavía. Mientras tanto se hace por SQL o rehaciendo el alta.

## El estado operacional no se toca desde aquí

`current_operational_state` (`VACANT_READY`, `AWAITING_CLEANING`…) **no se acepta ni en el alta ni
en la edición**, y no es una omisión: toda transición pasa por `PropertyStateMachine`, que es quien
comprueba que el salto es legal y deja su rastro en `property_state_transitions`. Un endpoint que
permitiera escribir esa columna dejaría el historial con agujeros sin que nada lo señalara.

Crear una propiedad **no** genera evento de timeline, por lo mismo: crear no es transitar.

**Sí se puede leer**, desde `dashboard-api`: `GET /api/v1/properties/{id}/state` devuelve el
estado canónico y el instante ISO-8601 UTC de la última transición — ambos **leídos**, nunca
recalculados, que es la otra cara de la misma regla. `last_transition_at` llega `null` en una
vivienda que nunca se ha movido, porque el alta no dejó transición que datar. La vivienda
también aparece en el agregado `GET /api/v1/properties/{id}/dashboard` y en la colección
`GET /api/v1/dashboard/properties`; los tres están documentados en
[`docs/dashboard.md`](dashboard.md).

## La contraseña del wifi entra y no vuelve a salir

Se puede enviar en el alta y en la edición, y se guarda cifrada. **No se puede leer de vuelta por
ninguna vía**: ni entera, ni enmascarada, ni en un mensaje de error. Lo que devuelve la lectura es
`has_wifi_password: true|false`, que permite distinguir «no hay ninguna guardada» de «hay una y no
puedes verla».

Que el huésped acabe necesitando esa contraseña no autoriza a exponerla aquí; quien tenga que
hacérsela llegar lo resolverá en su propio flujo, y tendrá que justificarlo entonces.

Dos consecuencias de que no haya lectura:

- **Enviarla en un `PATCH` cuenta siempre como cambio**, aunque mandes exactamente la misma que ya
  estaba: no hay con qué compararla, así que se reescribe y se registra en la auditoría.
- Si la pierdes, no hay recuperación: se sobrescribe.

## Retirar una vivienda

No hay `DELETE`. Se retira con `PATCH` poniendo `status: "INACTIVE"`, y sigue existiendo con todo
su historial — limpiezas, incidencias, reservas y transiciones de estado cuelgan de ella y borrarla
los dejaría huérfanos.

**Una propiedad retirada deja de aceptar reservas nuevas por las tres vías.** El alta manual
responde `409`; el import CSV y el sync del PMS **saltan esa fila y siguen con el resto del lote**,
anotando en el informe que la propiedad está retirada — que es distinto de «no existe», y por eso
el mensaje lo distingue. Un lote no se aborta entero por una vivienda retirada.

Volver a activarla es el mismo `PATCH` con `status: "ACTIVE"`.

## Las tres notas de texto libre salen del listado, y siguen en el detalle

`GET /api/v1/properties` **ya no devuelve** `access_notes`, `cleaning_notes` ni
`emergency_notes`. `GET /api/v1/properties/{id}` las sigue devolviendo las tres, y el `POST` y el
`PATCH` las siguen aceptando: lo que cambia es sólo el listado paginado.

El motivo es de volumen, no de permisos. Quien tiene `READ_PROPERTIES` podía pedir una sola
respuesta con las instrucciones de acceso de **todas** las viviendas del tenant, y ésa era la
única superficie que las servía a granel. Sacarlas del listado es la forma que se eligió cuando
`tech-incident-context` amplió el público de `access_notes` al rol `TECHNICIAN`; el contrato de la
regla 11 de `sdd/steering/security.md` exige que la forma se implemente y no sólo se documente, y
ésta es la implementación. El razonamiento completo, y por qué se rechazó cifrarlas en reposo
—responde a otra amenaza, y cubre por igual a una cuarta columna que vive en otro módulo—, está
en la excepción 6 de ese documento.

**Las tres, no sólo `access_notes`**: es un solo esquema y el mismo coste, y un listado que
esconde una nota y muestra dos no es una forma que nadie pueda explicar dentro de seis meses.

Si una pantalla necesita una nota, pide el detalle de esa vivienda. Coste conocido: una pantalla
que quisiera mostrar notas de varias viviendas a la vez pasa de una petición a N — y con dos
viviendas en el MVP, N es dos.

## Ver el portfolio desde `/properties`

`properties-web` graduó la ruta: donde antes había un cartel de «en preparación» ahora está el
índice del portfolio, **sólo lectura**, sobre `GET /api/v1/properties`. Es la única pantalla donde
se ve el `status` de una vivienda —`ACTIVE` o `INACTIVE` no aparecía en ninguna parte del
frontend— y el único sitio donde un UUID de propiedad, de los que `/reservations` e `/incidents`
imprimen en crudo, se resuelve a un nombre.

Cada fila lleva **seis** cosas y nada más: nombre (que es el enlace al detalle), código interno,
ciudad, capacidad (huéspedes · habitaciones · baños), estado operacional con su color de PRD §9.1,
y `status`. El resto de lo que el listado devuelve —dirección, país, zona horaria, horas de
entrada/salida por defecto, WiFi, vínculo con el PMS, sellos de tiempo— son datos de ficha: están
en el detalle, no en la lista.

Hay **dos filtros**, que son exactamente los dos que el endpoint acepta: situación (`status`) y
estado operacional, cada uno con un «todos». No hay búsqueda por texto, ni ordenación elegible, ni
filtro por ciudad: harían falta cambios en el backend. Cambiar un filtro vuelve a la página 1 — sin
eso, filtrar desde la página 3 puede caer en una página que el conjunto filtrado no tiene y devolver
un vacío indistinguible de «no hay ninguna así».

En móvil no hay que arrastrar la tabla de lado a lado: por debajo de `sm` cada vivienda es una
tarjeta apilada con pares etiqueta/valor, y la tabla de seis columnas aparece desde `sm`. Se hizo
así a propósito, porque con scroll lateral el dato que hay que desplazar para leer es justo `status`.

**Las notas de texto libre y la contraseña del WiFi no salen ahí**, y no por omisión: el listado no
las devuelve (ver la sección de arriba) y la pantalla no pide el detalle de cada fila para
rellenarlas — eso reconstruiría la superficie de bulto que se cerró a propósito, y encima con una
llamada por vivienda.

Quién la ve es cosa del backend, no de la pantalla: no hay guarda de permiso en el frontend.
`PROPERTY_MANAGER` y `TENANT_OWNER` ven el listado; `CLEANER`, `TECHNICIAN` y `SUPER_ADMIN` reciben
un estado «prohibido» localizado, que es el `403` del backend con otra cara. Un `401` no se pinta
como error sino como carga, para que la pantalla no parpadee mientras se rota el token.

El *qué hace* con sus criterios verificables está en
[`sdd/specs/properties-crud.md`](../sdd/specs/properties-crud.md) §«La pantalla del portfolio».

## Qué queda registrado

Cada alta y cada edición escriben una fila en `audit_logs`, en la misma transacción que el cambio:
si falla el rastro, no hay cambio. Un `PATCH` que no cambia nada **no** escribe fila — la auditoría
es evidencia de cambios, no de peticiones.

De los campos sensibles y de los de texto libre (`access_notes`, `cleaning_notes`,
`emergency_notes`, y la contraseña del wifi) se registra **que cambiaron**, nunca su valor.

## Lo que todavía no existe

- **No hay pantalla para dar de alta, editar ni retirar**: eso sigue siendo sólo API. La pantalla
  que sí existe es de lectura y está arriba, en «Ver el portfolio desde `/properties`».
- **Las credenciales del PMS no se tocan por API**, ni siquiera enmascaradas. Se gestionan con
  `python -m app.integrations.cli.pms_credentials`, y es a propósito: una credencial robada da
  escritura sobre la cuenta del cliente, así que no existe superficie HTTP que pueda filtrarla.
