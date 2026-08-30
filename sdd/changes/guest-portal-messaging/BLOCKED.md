# Blocked — guest-portal-messaging

## El gate ejecutable del panel no tiene canal de resultados (toolkit 0.40.0)

- **phase**: run
- **type**: decision
- **what & why**: `skills/reviewer-panel/reviewer_plan.py` de `sdd-toolkit` 0.40.0 valida un
  envelope JSON de resultados **que le entrega quien despacha el panel**. Entre un subagente de
  Claude y el gate **no hay canal automático**: el transporte es el propio modelo. Así que
  «satisfacer el gate» significa transcribir a mano los veredictos y pedirle al gate que valide
  esa transcripción — un PASS que certifica la transcripción, no la revisión.

  Por eso las secciones se anotan con `core-reviewers: … CLEAN` y **no** con `panel: PASS`: el
  panel se corrió de verdad (los siete revisores, en paralelo, con sus referentes en el prompt) y
  sus veredictos y cifras son la evidencia que son, pero el gate ejecutable no participó.
  `STATE.md` no puede distinguir un gate satisfecho de uno no ejecutado, y quien lo lea después
  merece saber cuál fue. Mismo criterio que `notifications-inbox-web` (2026-08-29).

  La salida real es un toolkit con un protocolo de resultados que la ruta Claude pueda producir,
  y esa decisión es del usuario.

- **exact resume command**: `/sdd:review guest-portal-messaging` (con la decisión del usuario
  sobre cómo proceder con el gate)

### Corregido el 2026-08-30 — lo que esta entrada afirmaba y ya no es cierto

La versión anterior decía que el gate **no podía pasar** porque `_parse_project` admitía
exactamente tres claves de frontmatter y los cuatro reviewers de proyecto caían a
`lens: unavailable`. **Eso está resuelto**: el parche local
(`~/.claude/local/sdd-toolkit-patches/apply_reviewer_plan_frontmatter.py`) está aplicado a
0.40.0, y verificado en este worktree el 2026-08-30 los **siete** revisores resuelven con lente
real y `planned`. El parche se revierte en silencio con cada upgrade del toolkit, porque el caché
de plugins está fijado por versión: hay que re-aplicarlo después de actualizar.

Queda en pie sólo el segundo problema, que es el de arriba y el importante. Y sigue vigente **no
tocar `.claude/agents/`** para esto: son ficheros compartidos con otras sesiones vivas y quitarles
`description` rompe cómo los lanza Claude Code.

## 12.6 — la comprobación manual extremo a extremo no se puede hacer desde este worktree

- **phase**: run
- **type**: deferred
- **what & why**: la tarea 12.6 pide abrir `/guest/[token]` en un navegador, escribir un mensaje,
  ver aparecer la respuesta automática, forzar una escalación y comprobar que el hilo llega a la
  bandeja del manager con el canal traducido. **Desde un worktree enlazado no es posible**, y no
  por falta de permisos: `sdd/project.md` lo documenta en dos pasos. Un worktree enlazado **no
  publica ningún puerto**, así que no hay `localhost:3000` que abrir; y `make up PORT_OFFSET=<n>`,
  que sí los publica, sirve el HTML pero **la página no hidrata** —medido el 2026-08-23 en
  `cleaning-assign-preconditions`— porque `next dev` bloquea el origen cruzado sin
  `allowedDevOrigins`. Sin hidratación no hay envío de formulario que probar, que es justo lo que
  12.6 quiere ver.

  Todo lo demás de la sección 12 está verificado y en verde por otras vías; lo que falta es
  específicamente la pasada visual. La salida es correrla **desde el worktree principal o desde
  `dev`**, que es lo que la propia tarea dice.

  Lo que sí está cubierto automáticamente, para que quien la ejecute sepa qué está confirmando y
  qué no: el ciclo completo huésped → pipeline → respuesta/escalación → incidencia está probado
  extremo a extremo sobre la app real en `backend/tests/guests/test_portal_messages_api.py` y
  `backend/tests/messaging/test_free_text_sink_contract.py`; la sección de conversación, sus
  estados y su sondeo, en `frontend/features/guest-portal/`. Lo que **ninguna** de las dos cubre
  es el navegador de verdad: hidratación, la traducción del canal vista en la bandeja, y que las
  cuatro secciones del portal convivan en una página real.

- **exact resume command**: desde el worktree principal (o contra `dev`), `make up` y recorrer el
  flujo; después marcar 12.6 en `tasks.md`. El resto de la sección 12 ya está.
