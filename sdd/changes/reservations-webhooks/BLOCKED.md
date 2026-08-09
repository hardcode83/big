# BLOCKED — reservations-webhooks

**Tres entradas, y ninguna es una decisión.** Las ocho decisiones que ha habido en este change las
resolvió Jose —cinco el 2026-08-08, tres el 2026-08-09— y cada una quedó escrita en su sitio
(`design.md`, `steering/security.md`, ADR 0007), no aquí: una entrada resuelta se borra, no se marca.
Lo que queda son los hallazgos que dejó abiertos el panel de `/sdd:review`, un puñado de correcciones
que sólo puede escribir `/sdd:archive` y tres deudas con disparador, para que se pueda reanudar sin
reconstruir nada de la conversación.

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

## 1. Seis hallazgos abiertos del panel de `/sdd:review` (2026-08-09)

- **Fase**: review
- **Tipo**: `deferred` — ninguno necesita decisión humana; son correcciones acotadas
- **Qué y por qué**

  **Lo que este review sí cerró, para que nadie lo repita.** Los dos huecos que esta entrada recogía
  antes ya no existen: el re-review de QA de la sección 3 **corrió entero** (sus cinco comprobaciones
  pendientes están resueltas, incluida la medición del falso positivo de `\s`) y el compare-and-swap
  del lease del lote **quedó auditado** por seguridad, tenencia y QA — QA lo probó además con dos
  sesiones concurrentes reales contra Postgres, no sólo con la lectura secuencial del repo. La matriz
  de completitud da **los 22 criterios de R1–R6 cumplidos**, con implementación y test localizados, y
  la suite de los módulos del change pasa (1727 tests). Cuatro de los siete reviewers devolvieron PASS
  limpio (arquitectura, tenencia, documentación, CI/CD, i18n).

  Lo que queda abierto son seis correcciones, ninguna de las cuales rompe un requisito:

  1. **`event_type` se deriva del cuerpo sin escurrir y su columna no tiene contrato** — *medio, el
     único que merece arreglo antes de mergear*. `application/webhooks.py:171` construye
     `event_type=_event_type(payload)` sobre el diccionario crudo mientras la línea 176 sí escurre
     `payload`. Escurrir antes no cambiaría nada —`event`/`event_type`/`type`/`action` no son claves
     "card-shaped"—, así que el fondo no es el orden: es que `webhook_events.event_type` es una columna
     de 200 caracteres escrita desde un cuerpo que controla el proveedor, sin `scrub_card_data` y sin
     `redact_long_digit_runs`, y **la tabla de la regla 11 no la reclama** (nombra seis columnas y ésta
     no está). Referente: regla 13(a), *"eliminarlos… antes de que **nada** pueda persistirlos"*.
     Agravante menor: el docstring de las líneas 172-175 afirma *"there is no moment at which an
     unscrubbed payload exists on an object headed for the database"*, y para este campo es falso.
     Arreglo: derivarlo del payload ya escurrido y darle forma cerrada (o pasarlo por
     `redact_long_digit_runs`), y reclamar la columna en la tabla de la regla 11.
  2. **La banda cerrada `13-19` sobrevive en un guard PCI hermano** — *medio*.
     `backend/tests/integrations/test_channex_probe.py:405` conserva
     `assert not re.search(r"\b\d{13,19}\b", raw)` sobre el **mismo** `FIXTURE_ROOT` que ahora cubre
     `test_fixture_card_guard.py`. Es el defecto exacto que la sección 3 identificó y corrigió aquí, y
     que centralizar `find_long_digit_runs` pretendía impedir que volviera a divergir. Fichero
     **pre-existente** —no lo introdujo este change, su diff en `main...HEAD` está vacío—, pero un
     fixture con `4111111111111111 1225` pegado pondría en rojo un guard y dejaría el otro en verde.
     Referente: R4.4, D8.
  3. **Un test que no puede fallar** — *medio*.
     `test_the_matcher_and_the_counter_agree_on_what_a_digit_is` (`test_free_text.py`) afirma que
     `redact_long_digit_runs("²" * 13)` no cambia, para fijar que `isdigit()` y `\d` discrepan. Pero
     `\d` no matchea `²` en absoluto, así que la cadena nunca entra en `_DIGIT_RUN` y el contador nunca
     se ejecuta: el test pasaría igual si el conteo usara `str.isdigit()`. Documenta una distinción
     real sin ejercitar ninguna rama que pueda romperse. Referente: `steering/testing.md`, R4.1/D8.
  4. **El falso positivo multilínea de `\s`, medido pero no fijado en la suite** — *bajo*. La medición
     (encargo explícito, ya hecha): con etiquetas de campo —`"Phone: 600123456\nBooking ref: …"`, el
     patrón operativo típico— **no dispara**, porque el texto de la etiqueta rompe la racha; sólo
     dispara con dos números **adyacentes sin nada entre ellos** al cruzar la línea
     (`"600123456\n1234567890"` → se funde en 19 dígitos y se redacta). Es más estrecho que el peor
     caso temido y cae en el mismo saco de riesgo que D8 ya ratifica, pero el módulo sólo documenta el
     caso del espacio. Arreglo: un caso multilínea en
     `test_the_accepted_false_positive_is_documented_by_a_case`. Referente: R4.1, D8.
  5. **Canal lateral por tiempo entre los tres rechazos** — *bajo*. Cuerpo, cabeceras y código son
     idénticos en los tres `404` (D4 se cumple), pero el **coste** no: provider no soportado corta sin
     tocar la base de datos, token desconocido cuesta un `SELECT`, y token válido con cabecera mala
     cuesta además un descifrado Fernet y un `compare_digest`. No es accionable —256 bits de CSPRNG y
     20 fallos/min por IP— pero es un residuo sin escribir. Arreglo: declararlo coste aceptado dentro
     de D4, como D1 hace con el suyo, o igualar el trabajo en la rama "no encontrado". Referente:
     R1.2/R1.6, D4.
  6. **Un docstring que promete un invariante que su llamador incumple** — *bajo*.
     `infrastructure/repositories.py:44-46` dice que `SqlAlchemyWebhookEventRepository` corre *"on an
     **unmarked** session by construction"*, pero `scheduler/tasks.py:202` lo construye sobre la sesión
     **marcada** que abre `run_in_marked_session`. Hoy es inofensivo —por esa vía sólo se invocan
     `mark_processed`/`record_failure`/`exhaust`, que son `UPDATE`, nunca `select_pending`— y tenencia
     confirmó que el filtro global añade el predicado correcto. El riesgo es que ese docstring es lo
     que leerá quien añada mañana una lectura por esa vía. Arreglo: decir qué método exige sesión sin
     marcar y cuál no. Referente: R5.5, D11.

  **Y un fichero que hay que borrar antes de mergear**, contado aparte porque es higiene y no lleva
  R#: `backend/tests/integrations/conftest_zzz_probe.py` (26 líneas, entró en `bd12d65`) se
  autodescribe como *"Throwaway probe"* y define un fixture `autouse=True` que monkeypatchea
  `_to_endpoint` a su forma **pre-fix** de un hallazgo de seguridad ya cerrado. Hoy es inerte —pytest
  no colecciona ese nombre y no hay `python_files` que amplíe el patrón—, pero es escombro commiteado
  con forma de mina: un cambio de configuración de pytest lo activaría en silencio sobre todo
  `tests/integrations/`.

- **Comando para reanudar**: `/sdd:run reservations-webhooks` para los arreglos (el 1 es el único que
  toca código de producción; el resto son tests, docstrings y un borrado), y después
  `/sdd:review reservations-webhooks` acotado a lo tocado. **Ojo**: cualquier commit que cierre estos
  hallazgos mueve HEAD, así que hay que re-correr `mark-ready` para que la evidencia de merge
  certifique el rango arreglado y no el que falló.

## 2. Texto y un diagrama que sólo puede escribir `/sdd:archive`

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

## 3. Tres deudas con disparador

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
