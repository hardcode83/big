# plaintext-sink-encryption-at-rest

Nota larga de la entrada `[TECH]` del mismo nombre en `sdd/roadmap.md`. La escribe
`tech-incident-context` (2026-08-21) al rechazar esta mitad en su OQ1, para que no quede como
deuda tácita: el design encarga explícitamente que se anote con nombre, y lo que sigue es el
razonamiento con el que se rechazó, no un recordatorio genérico de que «habría que cifrar cosas».

## Qué cubre

Cifrado en reposo, con Fernet y `ENCRYPTION_KEY`, de las cuatro columnas de texto libre del
esquema por las que puede colarse un valor de la regla 3 de `sdd/steering/security.md` —un código
de acceso, una contraseña, un número de documento— sin que el nombre de la columna lo anuncie:

- `properties.access_notes`
- `properties.cleaning_notes`
- `properties.emergency_notes`
- `access_records.notes`

Las cuatro juntas, y eso es la mitad del argumento: es lo que separa esta entrada de un parche
sobre una columna.

## La amenaza que cubre, y la que no

**Cubre**: lectura offline de la base de datos, de un backup o de una réplica. Quien obtenga un
dump lee hoy las instrucciones de acceso de todas las viviendas en claro.

**No cubre**: la exposición por API. Y esto hay que decirlo al dimensionarla, porque es la razón
por la que la entrada es `M` y no `L` de valor: `GET /api/v1/guest/info/{token}` devuelve
`access_notes` **verbatim** como `arrival_notes` a un portador anónimo de token, y el detalle de
propiedades la devuelve a quien tenga `READ_PROPERTIES`. Cifrar la columna no cambia ninguna de
las dos: se descifra para servirla. Quien venga a hacer este change y lo venda como «cerramos la
exposición de las notas» estará describiendo mal lo que hizo.

## Por qué `tech-incident-context` no la pagó

Aquel change amplió el público de `access_notes` al rol `TECHNICIAN`, así que le tocaba decidir la
forma de la regla 11 para esa columna. Eligió **excepción 6 más la salida del listado paginado**, y
rechazó el cifrado con tres motivos que constan en su OQ1:

1. El disparador era de **audiencia** —el conjunto de lectores crece—, y la salida del listado es
   el remedio con la misma forma que el problema. El cifrado responde a otra amenaza, cuya
   exposición aquel change no movía.
2. No reduce la exposición por API, que es donde estaba el cambio.
3. Su argumento cubre por igual a las cuatro columnas, así que pagarlo allí habría sido
   arbitrario (una de cuatro) o habría arrastrado las cuatro y una migración de datos a un change
   sobre la pantalla de un técnico.

Lo que aquel change **sí** dejó hecho, y por eso esto es el resto y no el problema completo: las
tres notas de `properties` salieron del listado paginado —que era la única superficie que las
servía a granel—, y `access_notes` entró en el censo de la regla 11 con su forma decidida y su
precio escrito.

## Alcance, cuando se haga

- Migración de datos sobre filas existentes, no sólo `ALTER TABLE`: las cuatro columnas tienen
  contenido en dev desde el 2026-08-10.
- Descifrado en cada camino de lectura vivo, que hoy son tres para `access_notes` (detalle de
  propiedades, portal del huésped, proyección de contexto del técnico), uno para
  `cleaning_notes`/`emergency_notes` (el detalle) y, para `access_records.notes`, los del owner y
  el manager que `access-notifications` ya entregó. **No el de `cleaner-app`**: su `/sdd:new` del
  2026-08-23 comprobó que esa app no muestra accesos ni puede —`CLEANER` no tiene
  `READ_ACCESS_RECORDS`—, así que ese cuarto lector no va a existir y no hay que contarlo.
- El patrón ya existe en el repo: `properties.wifi_password_encrypted` y las credenciales de
  proveedor. Conviene calcarlo antes que inventar otro.
- Las filas del censo de la regla 11 cambian de **forma** al hacerlo, así que la excepción 6 se
  reescribe —no se borra: seguirá siendo texto libre de una persona autenticada, sólo que cifrado
  en reposo—, y el resto de sus cláusulas «lo que NO concede» siguen aplicando.

## De quién es qué

La mitad de la regla 11 de `access_records.notes` **ya no es de `cleaner-app`**, y desde el
2026-08-23 no es de nadie: aquel `/sdd:new` comprobó que su disparador —que la app de la limpiadora
muestre accesos— no ocurre, porque PRD §11 y §6 no le dan accesos al rol y `policy.py` le niega
`READ_ACCESS_RECORDS` por escrito. Queda aparcada **sin disparador y sin change asignado**, que es
un estado distinto de «pendiente en el change siguiente»; la despertaría una superficie nueva que
conceda `READ_ACCESS_RECORDS` a un rol que hoy no lo tiene, y hoy no hay ninguna planificada.
Razonamiento entero en `sdd/roadmap/cleaner-app.md` §4.

Eso **no** afecta a esta entrada: la mitad de cifrado en reposo de las cuatro columnas sigue viva y
sigue siendo de aquí. La amenaza que responde —lectura offline de la base, de un backup o de una
réplica— es idéntica para las cuatro y no la mueve ningún change de audiencia, así que perder el
disparador de audiencia de una de ellas no le quita ni una columna.
