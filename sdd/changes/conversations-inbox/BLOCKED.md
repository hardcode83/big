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
