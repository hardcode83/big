# Blocked — guest-portal-messaging

## 12.6 — la comprobación manual extremo a extremo no se puede hacer desde este worktree

- **phase**: review
- **type**: deferred
- **what & why**: la tarea 12.6 pide abrir `/guest/[token]` en un navegador, escribir un mensaje,
  ver aparecer la respuesta automática, forzar una escalación y comprobar que el hilo llega a la
  bandeja del manager con el canal traducido. **Desde un worktree enlazado no es posible**, y no
  por falta de permisos: `sdd/project.md` §«Worktree bootstrap» lo documenta en dos pasos. Un
  worktree enlazado **no publica ningún puerto**, así que no hay `localhost:3000` que abrir; y
  `make up PORT_OFFSET=<n>`, que sí los publica, sirve el HTML pero **la página no hidrata**
  —medido el 2026-08-23 en `cleaning-assign-preconditions`— porque `next dev` bloquea el origen
  cruzado sin `allowedDevOrigins`. Sin hidratación no hay envío de formulario que probar, que es
  justo lo que 12.6 quiere ver.

  **Tampoco vale el worktree principal**: git no permite hacer checkout de
  `sdd/guest-portal-messaging` allí mientras la rama esté montada en este worktree. Comprobado el
  2026-08-30.

  Todo lo demás de la sección 12 está verificado y en verde por otras vías; lo que falta es
  específicamente la pasada visual. Lo que sí está cubierto automáticamente, para que quien la
  ejecute sepa qué está confirmando y qué no: el ciclo completo huésped → pipeline →
  respuesta/escalación → incidencia está probado extremo a extremo sobre la app real en
  `backend/tests/guests/test_portal_messages_api.py` y
  `backend/tests/messaging/test_free_text_sink_contract.py`; la sección de conversación, sus
  estados y su sondeo, en `frontend/features/guest-portal/`. Lo que **ninguna** de las dos cubre
  es el navegador de verdad: hidratación, la traducción del canal vista en la bandeja, y que las
  cuatro secciones del portal convivan en una página real.

  **Camino decidido con Jose el 2026-08-30**: arreglar el origen de dev del worktree en un change
  aparte —declarar `allowedDevOrigins` en `frontend/next.config.ts`— en vez de aplazar 12.6 a
  post-merge. Es la opción que desbloquea toda verificación visual futura en cualquier worktree,
  no sólo ésta. Ese change **completa `worktree-port-offset`** (archivado el 2026-08-19), cuyo
  objetivo declarado era «recuperar el navegador en un worktree enlazado» y que no lo consiguió:
  publica los puertos, pero la página no hidrata. La causa que da `sdd/project.md:104` está
  marcada **«no confirmada al cien por cien»**, así que ese change valida la premisa midiéndola
  antes de escribir el proposal.

  Consecuencia mientras tanto, y es la que importa: `ensure_local_gates()`
  (`sdd_lifecycle.py:363`) rechaza **tanto** una tarea sin marcar **como** un `BLOCKED.md` no
  vacío, y lo llama `mark-local-verified` (`:1460`), no sólo ship. Así que este change **no puede
  certificarse** hasta que 12.6 esté hecha, por mucho que el panel de siete haya dado el código
  por bueno el 2026-08-30 (34/34 criterios EARS con implementación y test).

- **exact resume command**: primero `/sdd:new` para el arreglo del origen de dev; una vez
  mergeado y traído a esta rama (merge de la base, nunca rebase: un rebase borra el
  `implementation_sha`), `make up PORT_OFFSET=<n>` aquí, recorrer el flujo, marcar 12.6 en
  `tasks.md` y volver con `/sdd:review guest-portal-messaging`.
