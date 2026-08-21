# Blocked / pending — conversations-inbox

## 1. Hallazgos menores abiertos del panel de revisión

- **phase**: review
- **type**: deferred
- **what & why**: el panel corrió el 2026-08-21 sobre el ancla `a1b348f` (siete
  reviewers) con veredicto **FAIL**: dos mayores y seis menores. **Los dos mayores
  están cerrados** en `a56fb2e` y re-verificados por los dos reviewers que los
  levantaron (`sdd-security` y `sdd-review-cicd`, ambos PASS, cero hallazgos nuevos):

  1. *Borrador entre conversaciones* — `reply-composer.tsx` guardaba `content` y
     `lastSent` sin reset al cambiar `conversationId`, así que con el hilo destino
     cacheado el borrador de una conversación quedaba bajo el id de otra. Ahora el
     borrador se guarda con su conversación y se deriva en render; cuatro tests de
     regresión, verificados como fallidos si se revierte el fix.
  2. *La guardia de `Suspense` no guardaba nada* — la justificación de D5 («sin
     frontera, `next build` falla») era falsa: `getServerT()` lee `cookies()` en cada
     página, así que las 24 rutas ya son dinámicas. La aserción solo hacía
     `toContain("Suspense")`. Ahora se ignoran comentarios y se exige `fallback`,
     que la frontera **envuelva** al componente cliente y que ese componente siga
     llamando a `useSearchParams()`. Verificado con cuatro mutaciones distintas: las
     cuatro hacen fallar el test. La afirmación falsa quedó corregida en `design.md`
     (D5, Risks, tabla de cobertura), `tasks.md` (8.3), `proposal.md` y el comentario
     de `page.tsx`, y no sobrevive ninguna copia viva en el árbol.

  **Lo que sigue abierto son los seis menores**, ninguno tocado:
  1. `transcribe-dialog.tsx:120-124` — el título de error afirma «no se ha guardado
     nada» para **cualquier** fallo, cuando D13 solo lo deriva del 422; un 5xx tras el
     commit miente al operador sobre prosa del huésped ya persistida
     (`steering/security.md` regla 11 excepción 4, cuya única obligación en esta
     superficie es precisamente decírselo).
  2. `reply-composer.tsx:13` — `MAX_MESSAGE_LENGTH` es el único dato de contrato
     exportado de componente a componente (lo importa `transcribe-dialog.tsx`) en vez
     de vivir en `lib/` como el resto (D1).
  3. `confirm-dialog.tsx` es no controlado y cierra siempre al confirmar, así que
     `transcribe-dialog.tsx` duplica el armazón Radix en lugar de reutilizarlo, lo que
     socava el motivo declarado de D20.
  4. Cuatro claves i18n huérfanas en ambos catálogos —`composer.empty`, `filters.any`,
     `message.sentAt`, `thread.channel`—, verificadas con 0 referencias en 254 ficheros
     fuente (D7 prohíbe interpolar claves, así que no hay construcción dinámica que las
     justifique).
  5. La tabla *Changes by area* de `design.md` omite `lib/channels.ts`,
     `lib/channels.test.ts`, `components/thread-role-gate.test.tsx` y
     `components/ui/confirm-dialog.test.tsx`, y la tarea 9.5 afirma «dos ficheros más»
     de los previstos cuando son cuatro.
  6. `docs/conversations-inbox.md` no aparece en *Affected specs*, así que la
     obligación de `steering/documentation.md` de dar página `docs/<capability>.md` a
     una capability nueva de cara a usuario no tiene casa en ningún artefacto.

  **Además, un hallazgo pre-existente descubierto al re-verificar el fix** (no es
  regresión de `a56fb2e`; ya estaba en `a1b348f` y queda fuera del alcance del fix):
  `send.isError` es estado de la instancia del hook, no del hilo, así que un fallo de
  envío en la conversación A pinta su banner de error sobre el compositor de B tras un
  cambio por el camino cacheado. No cruza prosa del huésped —la copia es una clave
  localizada genérica— pero atribuye un fallo a la conversación equivocada. Mismo
  patrón que el borrador, y la misma forma de arreglarlo.
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
  Sin hidratación no hay ninguna superficie interactiva en la aplicación, ni la de
  esta bandeja ni la del panel que ya existía.

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
