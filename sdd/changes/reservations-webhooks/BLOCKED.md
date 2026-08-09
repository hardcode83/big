# BLOCKED — reservations-webhooks

**Dos entradas, y ninguna es una decisión.** Las ocho decisiones que ha habido en este change las
resolvió Jose —cinco el 2026-08-08, tres el 2026-08-09— y cada una quedó escrita en su sitio
(`design.md`, `steering/security.md`, ADR 0007), no aquí: una entrada resuelta se borra, no se marca.
Lo que queda es el estado de la implementación y un re-review a medias, para que se pueda reanudar sin
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

---

## 1. La implementación está a medias (secciones 1 a 3 de 6)

- **Fase**: run
- **Tipo**: `deferred` — el flujo puede reanudarlo sin decisión humana
- **Qué y por qué**

  `tasks.md` es la verdad de lo hecho y lo pendiente. Al cerrar esta sesión:

  - **Sección 1 completa y verificada, con commit propio cada tarea**: 1.1 (entidad `WebhookEndpoint`,
    puerto y las tres primitivas de autenticación), 1.2 (tabla `webhook_endpoints` + las dos columnas
    de reintento), 1.3 (repositorio + test de aislamiento propio), 1.4 (vocabulario de auditoría +
    denylist de la regla 11 para los dos secretos), 1.5 (casos de uso de alta y rotación), 1.6 (los dos
    endpoints con RBAC) y 1.7 (las dos mitades del contrato regeneradas).
  - **Sección 2 completa y verificada** (2.1 a 2.7): los dos limitadores, la evidencia del tope de
    cuerpo, el caso de uso de recepción, la frontera de tarjeta, el router anónimo, el guard de
    fixtures y las dos mitades del contrato.
  - **Sección 3 completa y verificada** (3.1 y 3.2): `free_text.py` y su aplicación a
    `special_requests` en los dos mapeos externos. Su panel **no está cerrado**, ver la entrada 2.
  - **Los paneles de las secciones 1 y 2 cerrados en PASS**, siete reviewers cada uno, con dos rondas
    de arreglo en la sección 2 (el máximo). Catorce hallazgos aceptados y arreglados entre ambos.
  - **Pendiente**: las secciones 4, 5 y 6 completas. La 4 (procesamiento asíncrono) es la más grande
    del change, ocho tareas, y es la que convierte la cola en reservas.
  - **Verde en lo que se ha tocado**: 1646 pasan en `tests/integrations` + `tests/reservations` +
    `tests/test_layering.py`. **La suite completa no se ha vuelto a correr desde la sección 2** (allí
    fueron 4065 pasan, 35 se saltan, todos placeholders preexistentes de
    `tests/properties/test_state_machine.py`, ajenos a este change). La tarea 6.1 la corre al cerrar.

  **Dos deudas con disparador, que no bloquean nada ahora pero no deben perderse** (las dos están
  razonadas en `design.md`, esto es sólo el recordatorio):

  1. **La allowlist de IPs del proveedor** (D6), cuando se llegue a 25-50 unidades o a la primera
     rotación que provoque un `429` cruzado, lo que ocurra primero.
  2. **La Transform Rule de Cloudflare** que redacte `/api/v1/webhooks/*` en los logs del borde (D1),
     **antes de que entre el primer tenant real**. Hoy la exposición es a la propia cuenta de Jose;
     con un segundo cliente deja de serlo.

  Y una **tercera deuda con disparador**, nueva de la sección 3: `csv_parser.py` llena
  `special_requests` sin redactar, aceptado porque el import de CSV lo sube un operador autenticado.
  Se revisa si el CSV deja de ser una reintroducción revisada por una persona y pasa a ser reingesta
  cruda de una exportación del PMS (D8).

  Dos observaciones de texto obsoleto que **no** son de este change y que los paneles dejaron dichas:
  el comentario del servicio `frontend` en `docker-compose.deploy.yml` y la entrada
  `sdd/roadmap/api-ingress-routing.md` siguen redactados como si el camino de entrada de Beds24
  estuviera sin decidir; y `sdd/specs/pms-beds24-adapter.md` sigue describiendo la frontera de
  `special_requests` en futuro (*"se vuelve exigible en cuanto…"*) cuando el disparador ya se ha
  cumplido — eso último lo corrige `/sdd:archive`, que es quien escribe `sdd/specs/`.

- **Dónde vive el trabajo**: worktree
  `/Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+reservations-webhooks`, rama
  `sdd/reservations-webhooks`, publicada en `origin`. Su stack de Docker está levantado; `make down`
  antes de borrar el worktree.
- **Comando para reanudar**: `/sdd:run reservations-webhooks 4` — **con `/clear` antes**, que es donde
  está el ahorro: la sección 4 no necesita nada del contexto de esta sesión.

## 2. El re-review de QA de la sección 3 se quedó a medias

- **Fase**: run
- **Tipo**: `deferred` — no hace falta ninguna decisión humana, sólo volver a correrlo
- **Qué y por qué**

  El panel de la sección 3 corrió entero (siete reviewers, un mensaje). Tres sin hallazgos
  (`sdd-review-cicd`, `sdd-review-i18n`, `sdd-review-tenancy`); arquitectura, seguridad, QA y
  documentación con hallazgos. Se arreglaron ocho en la primera ronda —incluidos los dos que
  importaban, los dos demostrados: el guard de fixtures que conservaba la banda cerrada 13-19 que el
  redactor ya había abandonado, y el matcher ASCII que dejaba pasar un espacio duro y los dígitos
  fullwidth o arábigo-indios— y las tres decisiones que quedaban las resolvió Jose ese mismo día.

  De los re-reviews de la ronda 1, **seguridad devolvió PASS** (verificado plantando un PAN en un
  fixture real y comprobando que el guard se pone en rojo, más una medición de ReDoS contra el patrón
  nuevo hasta 600k caracteres, lineal). **El de QA murió por límite de uso de sesión** antes de emitir
  veredicto. Por eso la sección 3 **no** lleva la anotación `panel: PASS` en `tasks.md`: no se marca un
  panel que no ha cerrado.

  Lo que le quedaba por comprobar a QA, para no reconstruirlo: que su hallazgo de dígitos no-ASCII está
  cerrado; que `\d` no ensancha de más (`isdigit()`, `\d` e `isdecimal()` son tres conjuntos distintos)
  y que el test del `²` fija algo real; **que `\s` no ensancha de más** — ahora incluye el salto de
  línea, así que dos números cortos en líneas consecutivas se funden y pueden pasar de 13 dígitos: se
  aceptó a conciencia, en el mismo saco que el falso positivo de los dos teléfonos que D8 ya acepta,
  pero **el tamaño real no está medido**; que los cinco tests nuevos fallarían si se revirtiera el
  arreglo; y que el guard de fixtures reescrito sigue probando lo que dice.

- **Comando para reanudar**: `/sdd:review reservations-webhooks` — a escala de feature cubre esto y lo
  demás, que es la forma recomendada de retomar un panel interrumpido. Si se prefiere acotar,
  `/sdd:run reservations-webhooks 3` re-dispara el panel de la sección.
