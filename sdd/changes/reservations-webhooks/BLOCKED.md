# BLOCKED — reservations-webhooks

**Dos entradas, y ninguna es una decisión.** Las ocho decisiones que ha habido en este change las
resolvió Jose —cinco el 2026-08-08, tres el 2026-08-09— y cada una quedó escrita en su sitio
(`design.md`, `steering/security.md`, ADR 0007), no aquí: una entrada resuelta se borra, no se marca.
Lo que queda es un puñado de correcciones que sólo puede escribir `/sdd:archive` y tres deudas con
disparador, para que se pueda reanudar sin reconstruir nada de la conversación.

**El panel de `/sdd:review` cerró el 2026-08-09 con veredicto APROBADO**, y por eso su entrada ya no
está aquí. Levantó seis hallazgos y todos se arreglaron en dos rondas (`c95df4e`, `43f7372`), con
re-review de seguridad y de QA en PASS sobre el estado final. El único que tocaba producción era
`webhook_events.event_type`, que se rellenaba con lo que el cuerpo trajera bajo `event`/`type`/
`action`: una columna de texto libre escrita desde fuera que el censo de la regla 11 no miraba. La
segunda ronda existió porque la primera regla —un `\d{5,}` liso— la derrotaba su propio alfabeto, y
eso está contado en D7 de `design.md` junto con los **tres residuos declarados** del enfoque. Lo
demás fueron la capa de test y dos docstrings. Suite completa: 4163 passed, 35 skipped.

Lo resuelto, por si alguien llega buscándolo. **El 2026-08-08**: **D8** (forma de la redacción de
`special_requests`, ratificada), **D9** (columnas de reintento, ratificada →
[ADR 0007](../../../docs/adr/0007-webhook-event-retry-columns.md)), **D15** (no auditar la lectura
anónima, ratificada → tercera excepción nombrada de la regla 9 de `sdd/steering/security.md`), **D6**
(presupuesto por IP, aceptado con disparador) y **D1** (el token en los logs del borde, aceptado en dev
con Transform Rule antes del primer tenant real). **El 2026-08-09**, las tres que levantó el panel de la
sección 3, las tres escritas dentro de D8: el **umbral** (13 o más, no la banda cerrada — se corrige el
diseño, no el código), la **capa** de `free_text.py` (se queda en `infrastructure/`, razonado, cerrando
el `DESIGN-CONFLICT` del arquitecto) y el **CSV** (`csv_parser.py` no se redacta: residuo aceptado con
disparador). La tabla de cierre está en `design.md` § Open questions.

**Y la implementación ya no está en esta lista: las seis secciones de `tasks.md` están completas y
verificadas** (la sección 6 cerró el 2026-08-09). `tasks.md` sigue siendo la verdad de lo hecho.

---

## 1. Texto y un diagrama que sólo puede escribir `/sdd:archive`

- **Fase**: archive
- **Tipo**: `deferred` — mecánico, sin decisión humana
- **Qué y por qué**

  `sdd/specs/` lo escribe `/sdd:archive`, no `run`, así que estas correcciones se anotan en vez de
  hacerse. Las páginas equivalentes de `docs/` **ya se corrigieron** en la sección 5.

  1. **`sdd/specs/celery-jobs.md`**: «SHALL registrar exactamente **cuatro** tareas periódicas» — con
     `process_webhook_events` ya son cinco.
  2. **`sdd/specs/local-environment.md`**: «el worker ejecuta las **cuatro** tareas periódicas de PRD
     §8.3». Es literalmente cierta si se lee «de PRD §8.3» como el calificativo que es —el quinto no lo
     es—, pero se lee como censo del scheduler, así que conviene tocarla igual.
  3. **`sdd/specs/pms-beds24-adapter.md`**: describe la frontera de `special_requests` en futuro
     (*"se vuelve exigible en cuanto…"*) cuando el disparador ya se ha cumplido.
  4. **El diagrama ER**: `webhook_endpoints` es una **entidad nueva**, así que
     `docs/diagrams/2026-08-06_autohost-er-entidades.png` —28 entidades, 67 relaciones, generado desde
     la metadata de SQLAlchemy— queda obsoleto y toca regenerarlo con `/sdd:diagram`, borrando el
     anterior (`steering/documentation.md`; el precedente exacto es la tarea 9.3 de
     `pms-provider-resolution`, cuando entró `pms_credentials`). **No se hizo en la sección 5 a
     propósito**: `documentation.md` declara `phases: [tasks, archive]` y esto vive en su *Checklist de
     archivado*. Nótese que es un caso distinto del de la tarea 9.7 de `properties-crud`, donde se
     razonó **no** regenerar: allí la migración sólo creaba y borraba un índice, y un índice no es ni
     entidad ni relación. Aquí sí hay tabla nueva.

  Dos observaciones más que los paneles dejaron dichas y que **no son de este change** (van sueltas, a
  criterio de quien archive): el comentario del servicio `frontend` en `docker-compose.deploy.yml` y la
  entrada `sdd/roadmap/api-ingress-routing.md` siguen redactados como si el camino de entrada de Beds24
  estuviera sin decidir.

- **Comando para reanudar**: `/sdd:archive reservations-webhooks`, **después** de que el PR esté
  mergeado.

## 2. Tres deudas con disparador

- **Fase**: run
- **Tipo**: `deferred` — no bloquean nada hoy; cada una tiene su disparador
- **Qué y por qué**

  Las tres están razonadas en `design.md`; esto es sólo el recordatorio para que no se pierdan al
  archivar.

  1. **La allowlist de IPs del proveedor** (D6), cuando se llegue a 25-50 unidades o a la primera
     rotación que provoque un `429` cruzado, lo que ocurra primero.
  2. **La Transform Rule de Cloudflare** que redacte `/api/v1/webhooks/*` en los logs del borde (D1),
     **antes de que entre el primer tenant real**. Hoy la exposición es a la propia cuenta de Jose;
     con un segundo cliente deja de serlo.
  3. **`csv_parser.py` llena `special_requests` sin redactar** (D8), aceptado porque el import de CSV lo
     sube un operador autenticado. Se revisa si el CSV deja de ser una reintroducción revisada por una
     persona y pasa a ser reingesta cruda de una exportación del PMS.

- **Comando para reanudar**: ninguno automático — se abren como changes propios cuando salte el
  disparador.

---

**Dónde vive el trabajo**: worktree
`/Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+reservations-webhooks`, rama
`sdd/reservations-webhooks`. La rama existe en `origin` pero está **25 commits por detrás** de HEAD
(el remoto apunta a `05b6ad1`, HEAD es `3c3feef`) y no hay upstream configurado: es un push viejo, no
la publicación del change. Su stack de Docker está levantado; `make down` antes de borrar el worktree.

**Un fallo de sesión que conviene no repetir**: un test nuevo del receptor usaba la fixture `api`
compartida, que **no** sustituye el throttle, así que ataba el cliente Redis de proceso
(`app.core.redis.get_redis`) al bucle de ese test y mataba a otro más tarde con «Event loop is closed».
Los docstrings de `test_webhook_receiver_api.py` y `test_login_throttle_over_http.py` avisan de
exactamente eso. La convención es construir el cliente en el propio test y sustituir
`get_webhook_throttle` salvo que el test *sea* sobre el límite de tasa.
