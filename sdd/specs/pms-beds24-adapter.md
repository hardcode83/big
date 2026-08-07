# Adapter de Beds24

## Purpose

La integración real con Beds24, el proveedor PMS/Channel Manager que
[ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) elige para el MVP. Una propiedad
declarada como `BEDS24` sincroniza sus reservas contra la API V2 del proveedor, usando la
credencial de cuenta cifrada que resuelve `pms-provider-resolution`.

Es **enteramente de lectura**: el puerto declara `list_reservations` y `get_reservation`, ambos
`GET`. La mensajería llega con `beds24-messaging-adapter` y la recepción de webhooks con
`reservations-webhooks`.

Operación y runbook: [`docs/beds24-adapter.md`](../../docs/beds24-adapter.md). Las mediciones que
lo sostienen: [`docs/beds24-spike.md`](../../docs/beds24-spike.md).

## Requirements

### Transporte y credencial

- THE SYSTEM SHALL construir el adapter con el secreto descifrado que la factory obtiene de
  `pms_credentials` (scope `ACCOUNT`), y NOT SHALL leer ninguna variable de entorno de credencial
  de Beds24. `BEDS24_REFRESH_TOKEN` pertenece solo al banco de medición de `scripts/`, que
  gobierna la regla 8 de `steering/security.md`; la credencial de la aplicación la gobierna la
  regla 3.
- THE SYSTEM SHALL canjear el access token de 24 h en la primera petición que lo necesite y
  mantenerlo **solo en memoria**, nunca en disco ni en base de datos.
- THE SYSTEM SHALL realizar **como máximo un canje por instancia de adapter**, protegido por un
  lock: la comprobación sin él no sostiene la garantía, porque varias llamadas concurrentes
  observan el token ausente antes de que ninguna lo asigne. Con el agrupado por proveedor del
  sync, un adapter por ejecución es un canje por ejecución.
- THE SYSTEM SHALL exigir esquema `https` y comparar el **hostname exacto** contra una allowlist
  **constante del módulo**, validando la URL **que realmente se va a pedir** y no una compuesta a
  mano: `httpx` ignora la URL base cuando la ruta es absoluta, así que validar la concatenación
  deja pasar cualquier destino.
- THE SYSTEM SHALL derivar esa allowlist de una constante y no de configuración. Beds24 no tiene
  entorno de staging, así que una URL base configurable sería una palanca sin caso de uso
  guardando una credencial que concede escritura sobre todas las propiedades de la cuenta.
- THE SYSTEM SHALL no incluir el valor del refresh token ni del access token en ningún `repr`,
  log, mensaje de error o traceback, **incluida su forma escapada**, y SHALL tachar sus propios
  secretos de cualquier mensaje compuesto a partir de una respuesta del proveedor.
- IF el canje devuelve un refresh token distinto al enviado, THEN THE SYSTEM SHALL fallar
  nombrando el hecho **sin el valor** y apuntando al CLI de rotación, y NOT SHALL persistir el
  valor nuevo: escribir la credencial desde el adapter sería una segunda vía de aprovisionamiento.

### Ventana de sincronización

- WHEN se invoca `list_reservations(since)`, THE SYSTEM SHALL pedir las reservas por **fecha de
  modificación**, de modo que devuelva las creadas, las modificadas **y las canceladas** desde ese
  instante.
- THE SYSTEM SHALL enumerar explícitamente los estados que son reservas —`new`, `request`,
  `confirmed`, `cancelled`, `inquiry`— en **parámetros repetidos**. No es una optimización: el
  listado por defecto **omite las cancelaciones**, la forma con comas devuelve `400`, e
  `includeCancelled=true` se ignora en silencio.
- THE SYSTEM SHALL omitir `black` de esa enumeración, con lo que los bloqueos de calendario quedan
  excluidos en la consulta. El predicado que los reconoce permanece en el adapter como defensa en
  profundidad, no como el mecanismo.
- WHEN se consulta una reserva por su id, THE SYSTEM SHALL no aplicar filtro de estado: filtrar
  por `id` devuelve la reserva sea cual sea su estado, y enumerar ahí perdería una reserva cuyo
  estado no esté en la lista.
- THE SYSTEM SHALL acotar la consulta a una propiedad cuando el llamante lo pida.
- WHEN el proveedor no conoce el id consultado, THE SYSTEM SHALL devolver `None` y no un error.
  Beds24 no tiene ruta por id para reservas: se filtra la colección, así que un id desconocido es
  un `data` vacío y no un `404`.

### Veredicto, paginación y créditos

- THE SYSTEM SHALL determinar si el proveedor aceptó una petición **por el cuerpo de la respuesta
  y no por el código HTTP**, reconociendo las cuatro formas medidas: sobre de lectura, éxito de
  escritura con `new`, rechazo por elemento con `errors` o `warnings` bajo HTTP `201`, y petición
  malformada devuelta como objeto en vez de lista. Un sobre irreconocible es fallo, nunca un
  `data` supuesto.
- THE SYSTEM SHALL componer los mensajes de error a partir del error estructurado del proveedor,
  **nunca del cuerpo crudo**, y SHALL acotarlos a texto imprimible de longitud limitada: un valor
  largo con un salto de línea falsifica una línea de informe con nuestra forma.
- THE SYSTEM SHALL paginar con su propio contador y **ignorar el enlace a la página siguiente que
  llega en el cuerpo**: seguirlo dejaría que el proveedor eligiera el destino de una petición que
  transporta una credencial de cuenta.
- WHEN se alcanza el tope de páginas, THE SYSTEM SHALL lanzar en vez de truncar: una lista corta
  dentro de un sync es indistinguible de «el PMS no tenía más».
- THE SYSTEM SHALL leer el coste por petición de la cabecera `x-request-cost` como **decimal**, y
  WHEN el proveedor no la envía SHALL registrarlo como desconocido y **nunca como `0`**.
- THE SYSTEM SHALL emitir una línea de log estructurada por petición con endpoint, estado, coste y
  crédito restante, sin payload y sin credenciales, y NOT SHALL repetir en el código la cifra de
  coste por ciclo: vive en `docs/beds24-spike.md`, generada desde el registro commiteado.
- IF el proveedor señala cuota agotada, THEN THE SYSTEM SHALL detenerse propagando el error del
  puerto, **sin reintentar**: la cuota es por cuenta, así que reintentar compite con el sync
  legítimo y con cualquier otro consumidor.

### Mapeo

- THE SYSTEM SHALL identificar la reserva por el `id` del proveedor, que sobrevive al ciclo
  completo de creación, modificación y cancelación — lo que hace útil la ventana de modificación.
  NOT SHALL usar la referencia de API (vacía en reservas creadas por API) ni el id maestro (agrupa
  reservas de varias habitaciones).
- THE SYSTEM SHALL identificar la propiedad por el `propertyId` del proveedor, de modo que **cada
  vivienda es una propiedad distinta en Beds24**. IF dos propiedades del mismo grupo comparten ese
  identificador, THEN el emparejamiento SHALL fallar en vez de adjudicar una reserva a la vivienda
  equivocada.
- THE SYSTEM SHALL traducir el vocabulario de estados del proveedor al del dominio, y WHEN
  encuentra uno desconocido SHALL pasarlo **sin traducir** para que la validación lo rechace y el
  ingestor reporte la fila: un estado conduce la máquina de estados de la propiedad, y adivinarlo
  significa llevar una vivienda real a un estado que no le corresponde.
- WHEN encuentra un canal desconocido, THE SYSTEM SHALL degradarlo a genérico y conservar la
  reserva. La asimetría con el estado es deliberada: un canal no conduce nada.
- THE SYSTEM SHALL registrar como `EXTERNAL_DEPENDENCY` lo que el proveedor no entrega: la reserva
  **no trae moneda** —vive en la cuenta, no en la reserva— ni hora de salida.
- WHEN un elemento no se puede mapear, THE SYSTEM SHALL devolverlo como fila fallida junto a las
  que sí mapeó, **sin abortar la página** y sin descartarlo en silencio. Esto incluye elementos que
  no son diccionarios: el transporte los entrega tal cual y el adapter los reporta.
- THE SYSTEM SHALL componer la razón de descarte de un vocabulario cerrado y la referencia de un
  identificador escalar acotado y sin caracteres de control: el mensaje de una excepción suele
  llevar incrustado el valor con el que tropezó.

### Datos de titular de tarjeta (regla 13)

- THE SYSTEM SHALL eliminar en la frontera los campos con forma de dato de tarjeta o credencial de
  pago antes de que el elemento entre en el DTO, **en todos los adapters de PMS**, sustituyendo la
  rama entera por un marcador constante.
- THE SYSTEM SHALL descartar además, y por completo, las ramas de **texto libre opaco** del
  proveedor. Un denylist por clave no puede ver dentro de una cadena, y el mensaje original de la
  OTA es precisamente de donde el proveedor extrae los datos de tarjeta.
- THE SYSTEM SHALL acotar la profundidad de ese recorrido y **descartar** lo que quede por debajo
  en vez de inspeccionarlo: una recursión sin tope no falla de forma segura.
- THE SYSTEM SHALL mantener una sola definición de las agujas de tarjeta por artefacto y fijarlas
  por test contra la exportación con nombre del anonimizador, incluida la comprobación de que esa
  lista es la que el anonimizador aplica de verdad.

**Frontera declarada**: el texto libre que un mapeo promueve a un campo **persistido** —hoy las
peticiones especiales de la reserva— queda **fuera** del alcance del scrubber. No hay ninguna
observación medida de datos de tarjeta en ese campo, y detectarlos dentro de texto libre exige una
comprobación con falsos positivos reales sobre un campo que el personal de limpieza lee. **Se
vuelve exigible** en cuanto exista una escritura no autenticada desde internet sobre esa misma
columna, que es lo que traen `reservations-webhooks` y `beds24-messaging-adapter`.

### Resolución y auditoría

- WHEN la factory resuelve una propiedad `BEDS24` con credencial guardada y válida, THE SYSTEM
  SHALL devolver el adapter real. IF la credencial falta o no descifra, THEN SHALL fallar con el
  error correspondiente y en ningún caso SHALL degradar al mock.
- WHEN una resolución automática descifra la credencial, THE SYSTEM SHALL registrarla con la
  granularidad que fija la entrada nombrada de la **regla 9** de `steering/security.md` — una fila
  por credencial distinta y por ejecución. Esta spec la cita y no la reformula.
- THE SYSTEM SHALL verificar por test la conformidad estructural del adapter con su puerto, y que
  **no** implementa los métodos de mensajería.

## Key files

- `backend/app/integrations/infrastructure/beds24/client.py` — transporte: allowlist de host,
  canje de token, sobre, paginación y contabilidad de créditos.
- `backend/app/integrations/infrastructure/beds24/mapping.py` — donde muere el vocabulario de
  Beds24; incluye el predicado de bloqueo de calendario.
- `backend/app/integrations/infrastructure/beds24/adapter.py` — el puerto, con la enumeración de
  estados que hace visibles las cancelaciones.
- `backend/app/integrations/infrastructure/card_data.py` — el descarte de la regla 13, compartido
  por los dos adapters de PMS.
- `backend/app/integrations/infrastructure/pms_factory.py` — la rama `BEDS24` de la resolución.
- `backend/tests/integrations/fixtures/beds24/` — reserva confirmada, modificada y cancelada,
  capturadas del proveedor real.
