# Datos de demo — `make seed-demo`

Llena un entorno recién levantado con el dataset de PRD §27 para que el producto se pueda
recorrer sin escribir SQL a mano. Es lo que convierte un dashboard vacío en dos viviendas, tres
reservas y una plantilla de limpieza.

**El *qué hace* está en `sdd/specs/seed-data-demo.md`; aquí va el *cómo se usa*.**

## La secuencia

```bash
make up          # levanta el stack
make bootstrap   # crea el tenant, su config y dos usuarios: TENANT_OWNER y PROPERTY_MANAGER
make seed-demo   # completa ese tenant con el dataset de §27
```

El orden no es una recomendación. `seed-demo` **completa** el tenant que `bootstrap` creó: si no
lo encuentra, sale con código 1 diciéndote que corras `bootstrap` primero, y **no escribe nada** —
la comprobación va antes de abrir transacción.

## Lo que siembra

| Entidad | Qué |
|---|---|
| Propiedades | `Redes 11` (REDES11) y `Pajaritos 8` (PAJARITOS8), en Madrid, con las plazas, habitaciones, baños y horas de §27 |
| Usuarios | Dos: `CLEANER` y `TECHNICIAN`. El owner y el manager ya los creó `bootstrap` |
| Reservas | Tres sobre REDES11: una pasada (`DIRECT`, hoy−10 → hoy−7), una activa (`AIRBNB`, hoy−2 → hoy+1) y una próxima (`BOOKING`, hoy+3 → hoy+7) |
| Huéspedes | Pedro López, John Smith y María García |
| Plantilla de limpieza | La de §7.10: 18 tareas y 6 fotos obligatorias, para las dos viviendas |
| Incidencias | Las tres de §27: WiFi lento y código de acceso en REDES11, lavadora ruidosa en PAJARITOS8 |
| Limpieza | La del checkout de la estancia pasada, **cerrada**: 18 ítems marcados y 6 fotos subidas |

## Y luego hace correr el reloj

Desde `seed-data-demo-extension` el comando no entrega un dataset quieto: después de sembrar,
**reproduce los hechos que §27 describe, en el orden en que habrían ocurrido y por las mismas vías
que los produciría el sistema en marcha**. Nada de esto se escribe a mano en una columna.

| Cuándo | Qué ocurre | Por dónde |
|---|---|---|
| hoy | La estancia `DIRECT` se confirma | `UpdateReservationUseCase` |
| hoy−10 | Entra Pedro López: ventana de check-in y check-in | los disparadores de reloj de `celery-jobs` |
| hoy−7 | Sale, y su salida **provisiona la limpieza** y se la asigna a la limpiadora | el aprovisionador del checkout |
| hoy−7 | La limpiadora acepta, empieza, marca 18 ítems, sube 6 fotos y cierra | los casos de uso de `cleaning` |
| hoy−2 | Entra John Smith, y su estancia pasa a `CHECKED_IN_ESTIMATED` | reloj + `UpdateReservationUseCase` |
| hoy | Se crean las tres incidencias y **el clasificador** les pone categoría y severidad | `maintenance` |
| hoy | Se abre una conversación de WhatsApp sobre la estancia activa y entran **dos mensajes del huésped** por la vía real de entrada: uno de wifi que la IA contesta desde el catálogo de plantillas, y uno de emergencia que **escala** por palabra clave | `ProcessInboundGuestMessageUseCase` + `MockAIAdapter` |

**Los disparadores de reloj van por tenant, no por vivienda**, porque son los mismos que el
scheduler ejecuta cada pocos minutos y ésa es su unidad. En un tenant recién bootstrapeado eso son
exactamente las dos viviendas de la demo; en uno que ya tuviera viviendas propias, el comando
también las haría avanzar si estuvieran en un estado que admita el disparador. Otra razón para
correr `seed-demo` sobre el tenant que `bootstrap` acaba de crear y no sobre uno en uso.

**El orden es contrato y no presentación.** Sembrar las incidencias antes que las estancias deja
REDES11 en `MAINTENANCE_REQUIRED` desde el primer paso, y desde ahí la máquina de estados no admite
la apertura de la ventana de check-in: el dataset acabaría en el mismo estado final con la mitad
del recorrido perdido, sin que nada fallara. Hay un test que afirma la secuencia entera de
transiciones por ese motivo.

### La conversación, y por qué no depende de red

Los dos textos del huésped son **constantes del módulo**, igual que los títulos de las incidencias,
y cada uno está pineado por test contra el intent que debe producir. No es celo: el adaptador de IA
del seed es `MockAIAdapter` —determinista, sin estado, sin I/O y sin credenciales, así que la
siembra funciona en un portátil sin llaves de ningún proveedor—, y `generate_response` lanza
`KeyError` **a propósito** para tres intents. Un texto que cayera en uno de ellos rompería el seed,
así que los intents son parte del contrato y no del azar.

El hilo queda por tanto con las **dos ramas** que la bandeja tiene que poder enseñar: una respuesta
automática y una escalada. Cómo se opera eso, y las dos cosas que sorprenden (apagar la IA no apaga
la alarma; una vez escalada la IA deja de contestar): [`messaging-ai.md`](messaging-ai.md).

**El enlace de portal de huésped no lo emite este comando.** `make seed-demo` imprime
`0 guest_access_tokens` a propósito: acuñar un token **revoca el vivo**, así que una segunda siembra
invalidaría el enlace que alguien ya tuviera, y eso rompería la idempotencia que el resto de este
módulo sostiene. El que sí lo acuña cada vez —porque su fase de borrado deja la tabla vacía antes— es
el reset del tenant de demostración: [`demo-tenant.md`](demo-tenant.md).

## Tres cosas que la demo enseña y que no son defectos

**REDES11 abre en `MAINTENANCE_REQUIRED`.** Hay un huésped dentro, una incidencia de acceso de
severidad `HIGH` y un técnico asignado, así que la vivienda aparece como no reservable — y eso es
correcto, no un fallo del seed. El **recorrido** (ventana de check-in, ocupada, limpieza, ocupada
otra vez) está en el **timeline**, que es donde la demo lo cuenta; el estado operacional es la foto
final, no la historia.

**Las incidencias 1 y 3 quedan en `CLASSIFIED` y no en el `OPEN` que §27 dibuja.** `classify` es la
única puerta de salida de `OPEN`, y el job de beat clasifica cualquier incidencia abierta cada cinco
minutos: una sembrada en `OPEN` habría cambiado sola al poco de mirarla, y un dataset que cambia
solo no es un dataset. La 2 sí queda en el `ASSIGNED` que §27 pide.

**`make seed-demo` depende de red y de credenciales cuando el tenant guarda sus ficheros en `S3`**
—el caso de `dev` desde `object-storage-provisioning`—, porque la limpieza sube seis fotos de
verdad y el almacenamiento `S3` **nunca** cae de vuelta al disco local. Si falta el bucket, la
región o la credencial, el comando lo dice y **sale antes de escribir nada**. Con `storage_type`
en `LOCAL` —lo que trae cualquier tenant nuevo, y el caso de tu portátil— no cambia nada.

## Las credenciales son tuyas, no del comando

§27 publica cuatro correos (`owner@adamar.test`, `manager@adamar.test`…) y una contraseña
común para las cuatro cuentas. **Ningún código lee esos valores** —el PRD los publica, pero
no hay ningún default en el árbol y nada los inyecta— y el comando no los impone:

- El owner y el manager son los que pusiste en `BOOTSTRAP_OWNER_EMAIL` / `BOOTSTRAP_MANAGER_EMAIL`.
  El seed los busca **por rol**, no por correo — si buscara por los correos de §27 y los tuyos
  fueran otros, crearía una quinta cuenta y un segundo `TENANT_OWNER`.
- La limpiadora y el técnico salen de seis variables **obligatorias sin valor por defecto**:
  `SEED_CLEANER_NAME/EMAIL/PASSWORD` y `SEED_TECHNICIAN_NAME/EMAIL/PASSWORD`. Están declaradas
  vacías en `.env.example`; hasta que las rellenes, el comando lista todas las que faltan y sale
  sin escribir.

Las cuatro cuentas quedan operativas al instante, sin cambio de contraseña forzado: una demo que
exige rotar cuatro contraseñas antes del primer clic no es una demo.

> **Dónde puedes rellenarlas.** No hay rechazo por entorno: el comando siembra allí donde lo
> ejecutes. No cuelga de ningún workflow de CD, y ponerlo en uno sería publicar credenciales
> conocidas en un entorno alcanzable.

## Se puede correr dos veces (pero envejece)

Una segunda ejecución no crea ninguna fila, no modifica ninguna, e imprime todos los recuentos a
cero. La identidad de cada entidad es algo que no se mueve con el calendario: el `internal_code` de
la propiedad, el correo normalizado de la cuenta, y los identificadores `SEED-AIRBNB-1`,
`SEED-BOOKING-1` y `SEED-DIRECT-1` de las reservas.

**Y de ahí la consecuencia que conviene leer despacio: el dataset envejece y `seed-demo` no lo
arregla.** Las fechas se calculan el día de la siembra. Un entorno sembrado hace dos semanas
enseña una reserva «activa» que ya terminó, y volver a correr el comando **no** la re-ancla — eso
sería modificar filas existentes, justo lo que la idempotencia prohíbe.

Para refrescarlo se tira la base y se empieza de cero:

```bash
docker compose down -v
make up && make bootstrap && make seed-demo
```

## Cosas que sorprenden

**Los tres estados iniciales no son el mismo, y está bien.** La reserva `DIRECT` nace `PENDING` y
las dos de OTA nacen `CONFIRMED`. No es una incoherencia: una reserva tecleada a mano está
pendiente de confirmar, mientras que una que llega de un feed sin estado es una reserva que
alguien ya aceptó. Cada una nace en el default **de su camino**.

**Borrar a mano la reserva `DIRECT` y volver a sembrar duplica a Pedro López.** Es el único
huésped sin clave de identidad, porque §27 no le da correo (los otros dos se identifican por el
suyo). Su creación va atada a la de la reserva, así que una segunda siembra normal no lo duplica;
pero si borras la reserva por tu cuenta, la siembra siguiente crea una reserva nueva y un segundo
Pedro, dejando huérfano al primero. Si has llegado a ese punto, tira la base con la receta de
arriba.

**El `MockPMSAdapter` contiene otra versión de estas mismas reservas.** Es un *fixture de
pruebas*, no el dataset de demo: sus fechas se derivan de la ventana del sync, emite dos filas
rotas a propósito, y sus datos ya divergen de §27 (dice `adults: 2` donde §27 dice 3). Si lees los
dos, ninguno está mal — son cosas distintas. Y las propiedades sembradas **no** llevan
`pms_external_id`, precisamente para que `make pms-sync` no importe las del mock encima de éstas.

**Quién figura como autor, que ya no es una sola persona.** Hasta que el dataset incluyó trabajo de
campo, todo lo que el comando escribía iba a nombre del `TENANT_OWNER`. Ahora cada escritura lleva
el actor que su caso de uso exige, y no por gusto:

- **la limpieza es de la limpiadora**, porque aceptar, empezar, cerrar y subir fotos exigen que
  quien actúa sea la persona asignada — el `TENANT_OWNER` sería rechazado;
- **los disparadores de reloj van como `SYSTEM`**, que es lo que hace el scheduler;
- **la clasificación no lleva actor ninguno**, y en el timeline figura como `AI`: no hubo persona
  detrás, y ponerla diría que la propietaria clasificó tres incidencias que no miró;
- **todo lo demás sigue siendo del `TENANT_OWNER`**, incluidas el alta de las incidencias y la
  asignación al técnico.

**Borrar a mano la estancia pasada cuesta más que antes.** Ahora arrastra su limpieza: la tarea, sus
18 ítems y sus 6 fotos apuntan a ella, así que la base de datos se niega a borrarla suelta. La
receta sigue siendo la de arriba — tirar la base y volver a sembrar.

**Una segunda ejecución no vuelve a subir las fotos.** La comprobación es una sola: si la limpieza
de la demo ya está cerrada, la fase no hace nada. Importa porque las filas de una siembra fallida se
revierten y **los objetos del almacenamiento no**: si algo falla después de subirlas, el comando
enumera en su salida las claves que quedaron sin fila que las referencie. Enumerar no es limpiar —
borrarlas es trabajo de operación, no del seed.

Y conviene saberlo antes de buscar un borrón y cuenta nueva: **`docker compose down -v` no toca esos
objetos**. Se lleva el volumen de Postgres, así que las filas desaparecen, pero los ficheros viven en
el volumen del almacenamiento local —y en `dev`, directamente en el bucket—, de modo que la
siguiente siembra empieza con la base vacía y el almacén no. No rompe nada: las claves llevan el
`task_id` y el `photo_id` nuevos, así que no colisionan; simplemente quedan ahí ocupando sitio, y
sólo un borrado explícito se los lleva.

## Cuando falla

| Código | Qué pasó |
|---|---|
| 0 | Sembrado, o no había nada que hacer |
| 1 | Falta configuración, los dos correos `SEED_*` son el mismo, la zona horaria del tenant no se resuelve, el tenant guarda en `S3` y le falta bucket, región o credenciales, no existe el tenant, falta el owner o el manager, un correo ya pertenece a otro tenant, **el clasificador no produce la categoría y la severidad que §27 declara**, **la cuenta de `SEED_TECHNICIAN_EMAIL` ya existía y no es un `TECHNICIAN` activo**, o **la limpieza de la demo no está asignada a la cuenta de `SEED_CLEANER_EMAIL`** (o el checkout la aprovisionó y luego no aparece) |
| 2 | El ingest devolvió filas saltadas o con error. Aquí **sí** se imprimen los motivos |
| 2 | Fallo inesperado. Se imprime **solo la clase** de la excepción, nunca su detalle |

Ese código 2 es deliberadamente parco: los errores de SQLAlchemy anexan la sentencia **con sus
parámetros**, y entre esos parámetros va el hash de una contraseña. Si necesitas el detalle,
míralo en los logs del stack.

La salida normal son recuentos por tipo de entidad. Nunca una contraseña, un hash ni un token.
