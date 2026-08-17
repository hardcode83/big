# Design: channex-validation-limits

## Context

Change **sin código de producto**: corrige tres documentos y no toca `backend/`. Está al borde
de lo trivial —no hay dependencias nuevas, ni esquema, ni interfaces— y se escribe este design
por dos motivos concretos: R3.3 obliga a **elegir** una única casa para las cifras del turno, y
la investigación encontró una **tercera** afirmación en presente que el proposal no nombra.

El estado actual de los tres documentos:

- `sdd/specs/pms-channex-staging.md` §Purpose (líneas 5-13) — abre con *«Existe para **validar el
  backend contra un PMS de verdad**»*, en presente, y **no dice en ninguna parte** que el valor de
  regresión sea permanente ni que la validación en vivo fuera un tiro único. Su §«Fixtures y su
  anonimización» (líneas 106-124) es **normativa** (qué debe cumplir la captura) y no inventaría
  qué hay capturado; `message_threads.json` solo aparece bajo el glob `fixtures/channex/*.json`
  de §Key files.
- `sdd/steering/product.md` línea 11 — blockquote *«Matiz sobre Channex…»* con la afirmación
  *«su entorno de staging **ya se usa hoy**»*.
- `docs/channex-staging.md` — runbook y hallazgos. Su §«Reserva end-to-end contra Booking.com»
  (líneas 144-198) **ya contiene medidos** cuatro de los cinco hechos que pide R3, con fechas y
  números. Y su **frase de apertura** (líneas 3-4) repite la misma afirmación en presente:
  *«Cómo se opera el sandbox de Channex **que valida el backend contra un PMS real**»*.

Un `grep` de la redacción vieja por todo el árbol da exactamente esos tres sitios más dos que
**no** se tocan: `sdd/roadmap/channex-validation-limits.md`, que cita las frases viejas *como
enunciado del problema* y lo supera `/sdd:archive`, y
`sdd/changes/archive/2026-08-03-channex-staging-adapter/proposal.md`, que es registro histórico.

## Decisions

### D1 — La casa de las cifras del turno es `docs/channex-staging.md`; la spec cita

**Chosen:** el registro de coste operativo de R3 vive en `docs/channex-staging.md`
§«Reserva end-to-end contra Booking.com», donde **ya está casi entero y medido**, y la spec añade
un puntero de una línea. Es la casa natural: R3 pide *hechos operativos observados*, y la spec es
un documento EARS de comportamiento del sistema, no un runbook. Además evita mover mediciones
crudas de sitio, que es la operación con más riesgo de perder matiz.

Rejected: mover el registro a la spec — convertiría una spec de comportamiento en runbook y
dejaría el runbook citando hacia arriba.
Rejected: escribirlo en los dos — R3.3 lo prohíbe explícitamente.

**Delta real en el runbook**, porque lo demás ya está: R3.1 (pool por franjas ✓, unicidad global
entre cuentas ✓) y R3.2 (sin cola ✓, IDs que no aceptan reservas con el aviso solo en la ficha ✓)
están cubiertos hoy. **Falta la duración de la ventana**, que el documento no declara en ninguna
parte. Ver D2 para cómo se escribe.

### D2 — La ventana se escribe como lo observado, no como una asignación garantizada

**Chosen:** registrar que **se hereda el resto de la franja ajena, no una ventana nueva** —el
panel muestra un instante absoluto (*"In use until … HH:MM"*), no una duración—, y que la única
sesión observada duró **del orden de tres horas**. Derivación, toda desde el propio documento:
el turno se ganó tras ~16 min de barrido siguiendo el intento fallido de las 13:50 sobre el ID en
EUR, y el arrendamiento expiró a las **17:00 Madrid** (§«Al desconectar un canal…»).

Escribir «la ventana útil es de dos o tres horas» a secas, como dice R3.2, cometería **el mismo
defecto que este change corrige**: convertir una observación única en una capacidad con la que
contar. Se conserva la cifra como orden de magnitud, con su n=1 y su procedencia.

Rejected: la cifra pelada de R3.2 — afirma una asignación que nadie ha medido dos veces.
Rejected: omitir la cifra — R3.2 la exige y es el dato que hace la planificación posible.

### D3 — La tercera afirmación en presente se corrige en este change

**Chosen:** corregir también la frase de apertura de `docs/channex-staging.md` (líneas 3-4).
Es el mismo defecto, en el documento que D1 convierte en **la referencia que lee quien planifica**;
dejarla viva ahí sería corregir dos de tres y dejar la que más se lee. No amplía el alcance de
ficheros: el runbook ya se modifica por R3.

Rejected: dejarla — ver arriba; `sdd/roadmap/` ya tiene el precedente de que una redacción vieja
sobrevive en el sitio equivocado.
Rejected: change aparte para una frase — desproporcionado.

→ **OQ1**: es una afirmación fuera de la lista literal del proposal, así que se confirma en el gate.

**Añadido en `/sdd:run` (2026-08-17): había una cuarta, en `docs/README.md` línea 8.** El índice de
`docs/` describía el runbook como *«runbook del sandbox de Channex **que valida el backend contra un
PMS real**»* — la misma frase, en el fichero que es la puerta de entrada al runbook. La encontró la
tarea 4.1, que es exactamente el criterio que la mandaba encontrar («cero aciertos en `docs/`; …
cualquier cuarto acierto es un sitio que se olvidó»). Se corrige aquí por el mismo razonamiento de
D3, y el índice se queda además con el puntero al coste del turno **sin ninguna cifra** (R3.3).
`docs/README.md` es por tanto un cuarto fichero modificado, no previsto en la tabla de abajo.

### D4 — §Purpose se reescribe en tres tiempos, no se le añade una nota

**Chosen:** reescribir §Purpose de la spec con la estructura **permanente / tiro único / vigente**:

1. *Qué aporta de forma permanente* — regresión del mapeo sobre los payloads reales commiteados en
   `backend/tests/integrations/fixtures/channex/` (`bookings.json`, `revisions.json`,
   `message_threads.json`), **sin ninguna llamada de red**, de modo que la suite de CI no depende de
   la cuenta de staging (R1.1). Hoy §Purpose no lo dice; solo lo dice §Fixtures como obligación.
2. *Qué fue un tiro único*, en pasado — la validación end-to-end contra Booking.com vivo, ya
   amortizada, y sus hallazgos con carácter normativo, nombrando el `guarantee` con `card_number`,
   `cvv` y `expiration_date` que originó la **regla 13** de `steering/security.md` (R1.2, R1.3).
3. *Qué sigue vigente* — el `ChannexAdapter` no se retira y Channex sigue siendo la única vía
   documentada al entorno de test de Booking.com (R1.4), con el puntero al coste del turno (D1).

Rejected: dejar la frase de apertura y añadir un aviso debajo — el defecto **está en la frase que
se lee y se cita**; un aviso que la contradice deja dos versiones vivas.
Rejected: cambiar solo el tiempo verbal — R1.1 exige **afirmar** el valor de regresión, que hoy
no está afirmado en ninguna parte de §Purpose.

### D5 — R4 va en §«Fixtures y su anonimización», con los campos donde de verdad están

**Chosen:** añadir al final de esa sección el inventario de `message_threads.json` (R4.1-R4.3):
qué es (hilo real de Booking.com capturado el 2026-08-03), qué campos trae, y **qué no permite
validar** — `title` y `last_message.message` llegan `***scrubbed***` por la política fail-closed,
así que sirve para el sobre y el mapeo y nunca para el tratamiento del contenido; y es forma de
**Channex**, de la que `beds24-messaging-adapter` no hereda nada.

**Precisión que el proposal no tiene y el documento sí debe tener**: en el fichero real `sender` y
`attachments` **no cuelgan del thread**, viven dentro de `last_message`. Al nivel del thread están
`provider`, `ota_message_thread_id`, `message_count`, `is_closed`, `title`, `inserted_at`,
`updated_at`, `last_message_received_at`, más `relationships` a `property`, `channel` y `booking`.
Describirlo como lo lista R4.2 mandaría a buscar dos campos donde no están.

Rejected: sección nueva «Fixtures capturados» — fragmenta un tema que ya tiene casa.
Rejected: inventariar los tres ficheros — solo el de mensajes es requisito (R4.1);
`bookings.json` y `revisions.json` se nombran en D4.1 y no necesitan ficha.

### D6 — `product.md` conserva el blockquote y cambia su premisa

**Chosen:** mantener el blockquote y reescribir su contenido para que afirme solo lo permanente:
Channex es el único proveedor evaluado con acceso al entorno de test de Booking.com, existe un
`ChannexAdapter` operativo de dev/staging y no de producción, y **esto no reabre ADR 0006**
(R2.1-R2.3). La validación en vivo se menciona en pasado, con puntero a la spec.

El título del blockquote —*«para que "fase SaaS" no se lea como "todavía no existe"»*— se ajusta:
tras la corrección tiene que blindar contra **las dos** malas lecturas, «no existe» y «está
disponible a demanda».

Rejected: borrar el matiz entero — R2.2 manda conservar los dos hechos que lo justifican.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Spec Channex | `sdd/specs/pms-channex-staging.md` | §Purpose reescrito en tres tiempos (D4, R1.1-R1.4) + puntero al coste del turno (D1, R3.3); ficha de `message_threads.json` al final de §Fixtures (D5, R4.1-R4.3) |
| Steering producto | `sdd/steering/product.md` | Blockquote línea 11 reescrito (D6, R2.1-R2.3) |
| Runbook | `docs/channex-staging.md` | Duración de la ventana + «se hereda la franja ajena» en §Reserva end-to-end (D1+D2, R3.2); frase de apertura líneas 3-4 corregida (D3) |
| Índice de docs | `docs/README.md` | Cuarta afirmación en presente (línea 8) corregida + puntero al coste del turno sin cifras (D3 ampliado en run, R3.3) |
| — | `backend/**` | **Nada.** El change no toca código, tests ni fixtures (Out of scope del proposal) |

## Data & interfaces

Ninguno. Sin esquema, sin endpoints, sin variables de entorno, sin migraciones.

## Risks & mitigations

- **Sobre-corregir y que se lea como retirada de la capacidad.** Es exactamente lo que R1.4 y
  *What changes* prohíben. Mitigación: R1.4 es criterio verificable y D4.3 lo escribe como párrafo
  propio, no como coletilla.
- **Que la cifra de la ventana se convierta en la próxima afirmación falsa.** Es el riesgo
  específico de este change: n=1, inferida de dos marcas horarias del mismo documento y con
  ambigüedad de zona horaria en una de ellas (`13:50` no lleva zona). Mitigación: D2 la escribe con
  su procedencia y su carácter observado.
- **Duplicar las cifras y romper R3.3.** Mitigación: la verificación del change incluye un `grep`
  de los números del turno por el árbol; deben aparecer en `docs/channex-staging.md` y en ningún
  otro sitio salvo como cita con enlace.
- **Que el archivado no vea `product.md` ni `docs/channex-staging.md`.** No son `sdd/specs/`.
  Mitigación: ya están declarados en §Affected specs del proposal, que es lo que `/sdd:archive` lee.

## Open questions

Las dos se resolvieron con Jose en el gate de design (2026-08-17). Ninguna queda abierta.

- **OQ1 (D3) — RESUELTA: sí.** La frase de apertura de `docs/channex-staging.md` (líneas 3-4) se
  corrige **en este change**, aunque no esté en la lista literal del proposal: es el mismo defecto,
  el runbook ya se modifica por R3, y es el documento que D1 convierte en la referencia de quien
  planifica. D3 queda firme.
- **OQ2 (D2) — RESUELTA: con procedencia.** La ventana se escribe como *«se hereda el resto de la
  franja ajena, no una ventana nueva»* más *«la única sesión observada duró del orden de tres
  horas»*, y **no** con el literal de R3.2. El literal afirmaría una asignación que nadie ha medido
  dos veces — el mismo defecto que este change corrige. D2 queda firme.

**Nota para `/sdd:tasks`**: OQ2 significa que el texto entregado **no reproducirá literalmente**
R3.2. El criterio se cumple en fondo (queda registrado que la ventana es corta, acotada y ajena),
no en cita textual; la tarea que lo implemente debe decirlo para que el panel de review no lo lea
como criterio incumplido.
