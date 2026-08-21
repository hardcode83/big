# Blocked / pending — conversations-inbox

## 1. El panel de revisión de las secciones 7 y 8 no llegó a correr

- **phase**: run
- **type**: deferred
- **what & why**: las secciones 1 a 6 pasaron su panel completo (7 reviewers cada
  una, con los hallazgos aceptados corregidos y re-verificados por el propio
  reviewer). El de la **sección 7** (compositor, transcripción, escalar/resolver,
  puerta de rol) se lanzó con sus siete reviewers y **los siete murieron a la vez**
  al agotarse el límite semanal de uso; ninguno emitió veredicto. El de la
  **sección 8** (vista maestro-detalle, ruta y responsive) no se llegó a lanzar por
  el mismo motivo.

  Lo que sí está verificado de esas dos secciones, y por eso esto es `deferred` y
  no `decision`: la suite completa del frontend en verde (635/636, con el único
  fallo siendo dos ficheros que ya fallaban por el montaje del contenedor),
  `typecheck`, `lint` y `build` de producción limpios, el contrato generado sin
  derivar, y el diff revisado contra el alcance declarado (tarea 9.5). Lo que falta
  es el juicio de los siete lentes contra los referentes: arquitectura frente a
  D5/D11/D12/D13/D16/D18/D19/D20, seguridad sobre la **primera superficie de este
  change que escribe** (regla 11 y su excepción 4, con la transcripción como nuevo
  escritor de `messages.content`), QA, i18n, tenancy, documentación y CI/CD.

  Tres cosas que el panel de la sección 7 debe mirar con calma, y que quedan
  escritas aquí para que no se pierdan:
  1. `use-conversation-actions.ts` **es código de la sección 4, ya aprobado**, y se
     modificó en la 7: los cuatro hooks de escritura llevan ahora
     `onError: refreshOnConflict`, que invalida las mismas tres claves **solo** en
     un 409, porque D18 pide «refrescar el estado real tras un 409». Eso obligó a
     cambiar un test que la sección 4 ya había aprobado (el que afirmaba que un
     fallo no invalida nada usaba un 409; ahora usa un 500, y dos tests nuevos
     cubren el 409).
  2. `MAX_MESSAGE_LENGTH = 4000` vive en `reply-composer.tsx` y lo importa
     `transcribe-dialog.tsx`, aunque es un dato del contrato y el resto de datos
     del contrato viven en `lib/`.
  3. `ConfirmDialog` es no controlado y cierra siempre al confirmar, así que
     `transcribe-dialog.tsx` **no** lo reutiliza —un fallo tiene que dejar el
     diálogo abierto para decir que no se guardó nada (D13)—, y eso duplica el
     armazón de overlay/contenido entre los dos diálogos.
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
- **exact resume command**: `/sdd:review conversations-inbox`
