# Tasks: channex-validation-limits

Change **sin código de producto**: solo `docs/channex-staging.md`, `sdd/specs/pms-channex-staging.md`,
`sdd/steering/product.md` y —**hallado en run por la tarea 4.1**— `docs/README.md`, cuya línea 8
repetía la misma afirmación en presente. El orden de las secciones no es casual — el runbook va primero porque
D1 lo convierte en **la casa** de las cifras del turno, y la spec (sección 2) solo puede apuntar a
algo que ya esté escrito.

## 1. Runbook `docs/channex-staging.md` — la casa de las cifras del turno <!-- panel: PASS 2026-08-17 -->

- [x] 1.1 Corregir la frase de apertura (líneas 3-4) — `docs/channex-staging.md`. Hoy dice *«Cómo se
  opera el sandbox de Channex **que valida el backend contra un PMS real**»*, en presente: es la
  tercera afirmación del mismo defecto y está en el documento que más se lee. Reescribirla para que
  describa lo que el documento es (runbook + hallazgos medidos de una operación ya hecha) sin
  afirmar una capacidad disponible. Hecho = ningún verbo en presente que prometa validación en vivo
  a demanda. [D3]

- [x] 1.2 Registrar la ventana del turno en §«Reserva end-to-end contra Booking.com» —
  `docs/channex-staging.md`. Es el **único hecho de R3 que falta**: el documento no declara la
  duración en ninguna parte. Escribirlo como manda D2/OQ2, **no** con el literal de R3.2:
  (a) que **se hereda el resto de la franja ajena, no una ventana nueva** — el panel muestra un
  instante absoluto (*"In use until … HH:MM"*), no una duración; (b) que la **única sesión
  observada** duró del orden de tres horas, con su procedencia dentro del propio documento (turno
  ganado tras ~16 min de barrido siguiendo el intento fallido de las 13:50 sobre el ID en EUR;
  arrendamiento expirado a las **17:00 Madrid**, §«Al desconectar un canal…», línea 275); (c) que es
  **n=1** y que una de las dos marcas horarias (`13:50`) no lleva zona. Hecho = la cifra aparece con
  su carácter observado y nunca como asignación garantizada. [R3.2]

- [x] 1.3 Verificar que los cuatro hechos restantes de R3 ya están medidos en esa misma sección y
  **no reescribirlos** — `docs/channex-staging.md`. Confirmar en el texto vivo: pool con reserva por
  franjas y no recursos a demanda (línea 152), unicidad **global entre cuentas** con el turno
  perdido ante otro integrador (líneas 155-158), ausencia de cola o reserva de turno (línea 158), e
  IDs que no aceptan reservas con el aviso visible solo en la ficha por hotel y no en la lista
  resumen (línea 150). Hecho = cada uno localizado por línea; si alguno no dijera lo que R3 exige,
  ampliarlo aquí y solo aquí. [R3.1, R3.2]

## 2. Spec `sdd/specs/pms-channex-staging.md` <!-- panel: PASS 2026-08-17 -->

- [x] 2.1 Reescribir §Purpose en tres tiempos — `sdd/specs/pms-channex-staging.md` (líneas 3-13).
  Sustituir la apertura *«Existe para **validar el backend contra un PMS de verdad**»* por la
  estructura **permanente / tiro único / vigente** de D4, no por una nota añadida debajo:
  1. **Permanente**: el valor de regresión no depende del hotel de test — los payloads reales están
     capturados y commiteados en `backend/tests/integrations/fixtures/channex/` (`bookings.json`,
     `revisions.json`, `message_threads.json`) y la propia spec ya exige alimentar con ellos los
     tests del mapeo **sin ninguna llamada de red**, de modo que la suite de CI no depende de la
     cuenta de staging ni volverá a depender. [R1.1]
  2. **Tiro único, en pasado**: la validación end-to-end contra una OTA viva fue un tiro único ya
     amortizado — nunca descrita en presente como capacidad disponible [R1.2] —, y produjo hallazgos
     con carácter normativo: nombrar al menos el `guarantee` con `card_number`, `cvv` y
     `expiration_date` que originó la **regla 13** de `steering/security.md` (línea 82). [R1.3]
  3. **Vigente**: el `ChannexAdapter` no se retira y Channex sigue siendo la única vía documentada
     al entorno de test de Booking.com — **párrafo propio, no coletilla**, porque el riesgo de este
     change es que se lea como retirada de la capacidad. [R1.4] Cierra con el puntero de **una
     línea** al coste del turno en `docs/channex-staging.md`, sin repetir ninguna cifra. [R3.3]

  Hecho = §Purpose afirma el valor de regresión (que hoy no afirma en ninguna parte), habla de la
  validación en vivo solo en pasado, y ADR 0006 sigue citado sin reabrirse.

- [x] 2.2 Añadir la ficha de `message_threads.json` al final de §«Fixtures y su anonimización» —
  `sdd/specs/pms-channex-staging.md` (tras la línea 124). Hoy el fichero solo aparece bajo el glob
  `fixtures/channex/*.json` de §Key files. La ficha declara:
  - **Qué es**: un hilo de mensajes **real de Booking.com** capturado el 2026-08-03. [R4.1, R4.2]
  - **Qué campos trae, donde de verdad están** (verificado contra el fichero, corrige la lista de
    R4.2): al nivel del thread `provider`, `ota_message_thread_id`, `message_count`, `is_closed`,
    `title`, `inserted_at`, `updated_at`, `last_message_received_at`, más `relationships` a
    `property`, `channel` y `booking`; **`sender` y `attachments` NO cuelgan del thread, viven
    dentro de `last_message`**. [R4.2, D5]
  - **Qué NO permite validar**: `title` y `last_message.message` llegan `***scrubbed***` por la
    política fail-closed de anonimización —correctamente—, así que sirve para el **sobre y el
    mapeo** y nunca para el tratamiento del contenido; y es forma de **Channex**, de la que
    `beds24-messaging-adapter` no hereda nada. [R4.3]

  Hecho = la sección, hoy solo normativa, inventaría este fichero sin convertirse en inventario de
  los tres (D5: `bookings.json` y `revisions.json` se nombran en 2.1 y no llevan ficha).

  **Ampliado por el panel de review (2026-08-17)**: la ficha lleva además un bullet con la **forma
  del fichero** —envoltorio JSON:API: `data`/`meta` en la raíz, el thread en `data[0]`, y
  `attributes` y `relationships` como **hermanos**, así que la ruta real es
  `data[0]["attributes"][…]`—. Sin eso, decir «al nivel del thread» mandaba a buscar los campos en
  la raíz del documento, que es el mismo defecto que D5 corrige un nivel más abajo. Verificado
  campo a campo contra el fixture.

## 3. Steering `sdd/steering/product.md` <!-- panel: PASS 2026-08-17 -->

- [x] 3.1 Reescribir el blockquote de la línea 11 — `sdd/steering/product.md`. Conservar el
  blockquote y cambiar su premisa (D6): eliminar *«su entorno de staging **ya se usa hoy** como
  banco de pruebas del backend contra un PMS real»* [R2.1], conservando en esa misma línea los dos
  hechos que sí siguen siendo ciertos y que justifican su existencia — Channex es el único proveedor
  evaluado con acceso al entorno de test de Booking.com, y existe un `ChannexAdapter` operativo de
  dev/staging y no de producción [R2.2] — y manteniendo explícito que **esto no reabre ADR 0006**:
  Beds24 sigue siendo el proveedor del MVP y Channex sigue siendo de fase SaaS [R2.3]. La validación
  en vivo se menciona **en pasado**, con puntero a `specs/pms-channex-staging.md`. Ajustar además el
  título del blockquote —hoy *«para que "fase SaaS" no se lea como "todavía no existe"»*— para que
  blinde contra **las dos** malas lecturas: «no existe» y «está disponible a demanda». [D6]

## 4. Verificación

Sin comandos de suite: el change no toca `backend/` ni `frontend/`, y la tarea 4.3 es justamente lo
que hace innecesario correr la suite. La verificación de un change documental es textual.

- [x] 4.1 Grepear la redacción vieja por **todo el árbol** y confirmar que solo sobrevive donde debe:
  `grep -rn "valida el backend contra un PMS real\|validar el backend contra un PMS de verdad\|ya se usa hoy" .`
  Esperado tras el change: **cero** aciertos en `sdd/specs/`, `sdd/steering/` y `docs/`; siguen vivos
  solo `sdd/roadmap/channex-validation-limits.md` (cita las frases viejas *como enunciado del
  problema*; lo supera `/sdd:archive`) y
  `sdd/changes/archive/2026-08-03-channex-staging-adapter/proposal.md` (registro histórico, no se
  reescribe). Cualquier cuarto acierto es un sitio que se olvidó.

  **Resultado en run (2026-08-17): hubo cuarto acierto** — `docs/README.md` línea 8, el índice de
  `docs/`, describía el runbook con la misma frase. Corregido en este change (ver D3). El archivo
  histórico esperado **no** aparece: usa otra redacción (*«validar nuestro backend contra un PMS
  real»*, *«un PMS de verdad y no de un mock»*), así que no la cazan estos tres patrones — lo cual no
  cambia nada, porque tampoco se reescribiría. Cierre: cero aciertos en `sdd/specs/`,
  `sdd/steering/` y `docs/`; sobrevive solo `sdd/roadmap/channex-validation-limits.md`.

- [x] 4.2 Grepear las cifras del turno y confirmar **una sola casa** (R3.3): los números y hechos del
  turno —ocho IDs, franjas, unicidad global, ventana— aparecen en `docs/channex-staging.md` y en
  ningún otro fichero salvo como cita **con enlace y sin cifra**. Comprobar en particular que 2.1 no
  reprodujo ninguna magnitud. [R3.3]

- [x] 4.3 Confirmar que el diff no toca código: `git diff --stat` no lista **ningún** fichero bajo
  `backend/` ni `frontend/`. Es el criterio de *Out of scope* del proposal y lo que hace que la
  suite no sea parte de esta verificación.

- [x] 4.4 Confirmar el fondo de R3.2 frente a su literal (OQ2 del design): el texto entregado en 1.2
  **no reproduce** la frase «la ventana útil es de dos o tres horas» a secas, deliberadamente —
  escribirla así cometería el mismo defecto que este change corrige. El criterio se cumple **en
  fondo**: queda registrado que la ventana es corta, acotada, heredada y ajena, con su n=1 y su
  procedencia. Dejarlo dicho aquí para que el panel de review no lo lea como criterio incumplido.

- [x] 4.5 Checklist de `steering/documentation.md` aplicado: sin endpoints, sin variables de entorno,
  sin strings de UI, sin cambios de arranque local ni de estructura → README raíz y `.env.example`
  intactos; sin diagramas afectados; `docs/channex-staging.md` **es** la página de capability y queda
  al día; ninguna doc referencia comportamiento eliminado (este change no elimina ninguno — R1.4).
