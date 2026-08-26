# assignment-note-storable-text

[TECH] **`incidents.assignment_note` es el único sumidero de texto libre vivo de `maintenance` que no pasa por `storable_text`.** Su esquema de petición la declara como `str` con `max_length` a secas (`backend/app/maintenance/api/schemas.py`, cuerpo de `assign`), mientras `incidents.materials` entró con `MultiLineText` desde el primer día.

La consecuencia es medible y **asimétrica dentro del mismo módulo**: un `U+0000` —o un surrogate suelto— en la nota de asignación llega a asyncpg y sale como un **`500` sin declarar**; el mismo carácter en los materiales se rechaza como `422`. Las dos columnas se teclean en la misma pantalla, por personas autenticadas, bajo la misma excepción 3 del censo de la regla 11 de `sdd/steering/security.md`.

## Por qué no lo cerró quien lo encontró

Lo levantó `tech-cycle-completion` (2026-08-22) en § Risks de su `design.md`, como observación fuera de alcance y con el motivo escrito en vez de omitido: **el cuerpo de `assign` no es suyo**. Lo sirve [`tech-incident-context`](../specs/tech-incident-context.md), que es donde vive el contrato de `assignment_note`. Cambiar la validación de una ruta ajena de paso habría ensanchado un change que ya tocaba la tabla de transiciones, dos columnas nuevas, el contrato publicado y el censo de sumideros.

Es la misma disciplina que aplicó `plaintext-sink-encryption-at-rest`: la mitad que no te toca se aplaza **con nombre**, no se deja sin escribir.

## Alcance

- El `Annotated` del esquema: `MultiLineText` con su cota, como `materials`.
- El test que fija el `422`, junto a los de `materials` en `backend/tests/maintenance/`.
- Una pasada por el resto de cuerpos del módulo buscando la misma omisión — la asimetría existía sin que nadie la viera precisamente porque nadie la había enumerado.

## Ojo al dimensionarlo

**Es cambio de contrato en el código de error**, no sólo endurecimiento interno: un llamante que hoy recibe `500` con un `U+0000` empezará a recibir `422`. Es lo correcto —el `500` no estaba declarado en ninguna parte— pero conviene que esté escrito antes de que alguien lo lea como regresión.

Y no confundirlo con [`plaintext-sink-encryption-at-rest`](plaintext-sink-encryption-at-rest.md): aquello es cifrado en reposo contra la amenaza offline, esto es validación de entrada contra un `500`. Columnas vecinas, amenazas distintas.
