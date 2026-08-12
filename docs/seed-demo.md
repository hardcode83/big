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

Lo que **no** siembra, y no es un olvido: las tres incidencias de §27 (las define `maintenance`,
que aún no existe) y los estados avanzados que §27 dibuja —`CHECKED_IN_ESTIMATED`, `COMPLETED`,
la limpieza cerrada con fotos—. Esos no se asignan: se **alcanzan**, por la máquina de estados y
por el scheduler de `celery-jobs`. Sembrarlos a mano sería falsificar el recorrido que la demo
existe para enseñar.

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

**Quién figura como autor.** Todo lo que el comando escribe queda atribuido al `TENANT_OWNER`, en
`audit_logs` y en `timeline_events`. Los casos de uso exigen una identidad y un comando no tiene la
suya, así que se elige la única cuenta cuya existencia el tenant garantiza.

## Cuando falla

| Código | Qué pasó |
|---|---|
| 0 | Sembrado, o no había nada que hacer |
| 1 | Falta configuración, los dos correos `SEED_*` son el mismo, no existe el tenant, falta el owner o el manager, o un correo ya pertenece a otro tenant |
| 2 | Fallo inesperado. Se imprime **solo la clase** de la excepción, nunca su detalle |

Ese código 2 es deliberadamente parco: los errores de SQLAlchemy anexan la sentencia **con sus
parámetros**, y entre esos parámetros va el hash de una contraseña. Si necesitas el detalle,
míralo en los logs del stack.

La salida normal son recuentos por tipo de entidad. Nunca una contraseña, un hash ni un token.
