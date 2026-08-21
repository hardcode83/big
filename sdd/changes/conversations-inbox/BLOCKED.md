# Blocked / pending — conversations-inbox

## 1. El estado por conversación del compositor no está acotado: tercer caso

- **phase**: review
- **type**: deferred
- **what & why**: **los ocho hallazgos del panel del 2026-08-21 están cerrados y
  re-verificados** por los reviewers que los levantaron (dos mayores en `a56fb2e`,
  seis menores en `e72d3f1`; los cinco re-reviews dieron PASS sin hallazgos nuevos).
  Lo que queda abierto es lo que la tercera repetición del mismo fallo dejó a la
  vista, y es estructural, no una línea más que parchear.

  `ReplyComposer` **no se desmonta al cambiar de conversación** cuando el hilo
  destino ya está cacheado: `useConversation` no lleva `placeholderData`, así que no
  hay early return que lo remonte, y `conversations-view.tsx` mantiene el mismo
  elemento en la misma posición. Tres piezas de estado por conversación han resultado
  mal acotadas por ese mismo motivo, y las tres se descubrieron por separado:

  1. `content` — el borrador de una conversación aparecía bajo el id de otra
     (**mayor**, arreglado en `a56fb2e`).
  2. `lastSent` — bloqueaba como doble envío una respuesta legítima idéntica a otra
     conversación (**mayor**, mismo arreglo).
  3. `send.isError` — **sigue abierto**: es estado de la instancia del hook, no del
     hilo, así que un fallo de envío en la conversación A pinta su banner de error
     sobre el compositor de B tras el cambio. No cruza prosa del huésped (la copia es
     una clave localizada genérica) pero atribuye un fallo a la conversación
     equivocada, y `aria-describedby` lo enlaza al campo, así que un lector de
     pantalla lo anuncia como el estado del hilo que se está viendo.

  **Por qué no se ha arreglado y por qué no debe arreglarse a la tercera igual que
  las dos primeras**: `/sdd:review` permite dos rondas de arreglo y ya se han gastado
  las dos (mayores, y luego menores). Y tres hallazgos de la misma forma no piden un
  tercer parche puntual, piden atacar la causa: el subárbol no está **keyed** por
  conversación. Un `key={conversationId}` en `ConversationThread` —o en el compositor—
  remonta y reinicia de golpe *todo* el estado por conversación: borrador, `lastSent`,
  el estado de la mutación y también el apaño de `selection` que
  `conversation-thread.tsx:49-55` usa hoy para la página. Es un cambio de una línea
  que hace innecesarias las tres derivaciones manuales, y por eso merece decidirse
  con la cabeza fría y no al final de una ronda de arreglos: hay que comprobar qué
  coste tiene el remontaje (una query cacheada no se re-pide, pero el foco y el
  scroll sí se pierden) frente a seguir acotando estado a mano.

  Verificación al cerrar la revisión, en `HEAD`: **662 tests en verde** (88 ficheros,
  0 fallos, con el árbol completo visible en el worktree), `tsc --noEmit` limpio,
  `eslint` limpio, `next build` limpio con `/conversations` entre las 24 rutas, y
  paridad de catálogos en verde (93 claves por locale).
- **exact resume command**: `/sdd:review conversations-inbox`

## 2. La comprobación manual de la superficie (tarea 9.4) no se pudo completar

- **phase**: run
- **type**: decision
- **what & why**: la tarea 9.4 pide recorrer la superficie **con el stack levantado**
  como `PROPERTY_MANAGER` y repetirlo en móvil y como `TENANT_OWNER`. Se preparó
  todo el entorno para hacerlo y el recorrido interactivo **no se pudo ejecutar**,
  por un fallo del servidor de desarrollo que es **ajeno a este change**.

  Lo preparado y verificado, que no hay que repetir:
  - stack del worktree en pie con puertos publicados (`make up PORT_OFFSET=10`:
    frontend 3010, backend 8010, ambos respondiendo 200);
  - tenant, propietaria y manager creados con `app.cli.bootstrap`, y el dataset de
    demo con `app.cli.seed_demo` (2 propiedades, 3 huéspedes, 3 reservas…). Las
    variables `BOOTSTRAP_*`/`SEED_*` quedaron rellenadas en el `.env` local, que
    está en `.gitignore`;
  - **el seed no crea conversaciones**, así que se crearon dos por API como
    manager —una `WHATSAPP` y una `AIRBNB_MSG` sobre `PAJARITOS8`—, y
    `GET /api/v1/conversations` las devuelve. Los siete endpoints responden.
  - `GET /conversations` sirve 200 con el HTML correcto: `<title>Conversaciones |
    AutoHostAI</title>` de `generateMetadata`, la copia del fallback de la frontera
    de `Suspense` («Cargando conversaciones…») y el `aria-label` del panel de la
    bandeja («Bandeja»). Es decir: la ruta, los metadatos, la frontera de suspense
    y la resolución de copia en servidor funcionan.

  **El blocker**: el bundle de cliente del servidor de desarrollo **no hidrata**.
  Comprobado con un navegador headless: los 35 scripts cargan, ninguna petición
  falla, y sin embargo el `button[type="submit"]` no tiene ninguna propiedad
  `__react*`, así que ningún componente cliente está montado; el formulario de
  login se envía como GET nativo (`/login?email=…&password=…`) en 6 intentos con
  hidratación calentada. El handshake del websocket de HMR
  (`ws://127.0.0.1:3010/_next/webpack-hmr`) falla con `ERR_INVALID_HTTP_RESPONSE`.

  **Por qué no es de este change**: la página que no hidrata es `/login`, que este
  change no toca. Se intentó vaciar `.next` y reiniciar el contenedor sin cambio.

  **Acotado en `/sdd:review` el 2026-08-22, y la premisa de arriba era demasiado
  amplia.** Se sirvió el **build de producción** en un puerto libre (`next start -p
  3999`, sin contenedores ni backend) y se cargó `/login` con navegador headless:
  **hidrata perfectamente**. `input` y `button[type=submit]` llevan
  `__reactFiber$`/`__reactProps$`/`__reactEvents$`, el `<form>` tiene un `onSubmit` de
  React adjunto —así que **no** puede enviarse como GET nativo, que era el síntoma
  exacto reportado— y la única entrada de consola es un 404 de `favicon.ico`.

  Conclusión: el fallo de hidratación es **del servidor de desarrollo**, no de la
  aplicación, y la frase «sin hidratación no hay ninguna superficie interactiva» solo
  vale para `next dev`. Ojo con el aviso que imprime Next al arrancar: `next start` no
  soporta `output: "standalone"` y pide `node .next/standalone/server.js`; aun así
  sirvió e hidrató, pero la receta correcta es la del aviso.

  **Lo que esto cambia**: la 9.4 **no necesita** que se arregle el servidor de
  desarrollo. Se puede recorrer contra un build de producción con el backend
  levantado. Deja de ser «esperar a que alguien arregle el entorno» y pasa a ser
  ejecutable con receta conocida.

  **Qué falta**, y por eso es `decision` y no `deferred`: que una persona recorra
  a mano, en un entorno con hidratación sana, lista → filtros (con la nota de
  `CLOSED`) → paginación → abrir un hilo por URL → responder → transcribir y ver
  aparecer la respuesta de la IA con su `intent` y su confianza → escalar →
  resolver con confirmación; y lo repita en móvil (una columna con «volver») y como
  `TENANT_OWNER` comprobando que lee sin ningún control de gestión. La lógica de
  todo eso está cubierta por 240 tests de componente, pero R7.6 y el recorrido de
  9.4 hablan de la superficie real.

  **Nota del panel de review (2026-08-21)**: QA confirma que R7.6 queda *met* solo en
  su cláusula de layout dirigido por estado (colapso a una columna sin `matchMedia`,
  cubierto en `conversations-view.test.tsx:119-159`) y **sin verificar** en su cláusula
  literal de usabilidad: desbordamiento horizontal real, anillo de foco computado y
  orden de recorrido por teclado entre `ThreadActions`/`ReplyComposer`/
  `TranscribeDialog`/`ConfirmDialog` no son observables sin viewport real.
- **exact resume command**: `/sdd:review conversations-inbox`
