# BLOCKED — reservations-webhooks

**Una entrada, y no es una decisión.** Las cinco que había las resolvió Jose el 2026-08-08 y cada una
quedó escrita en su sitio —`design.md`, `steering/security.md`, ADR 0007—, no aquí: una entrada
resuelta se borra, no se marca. Lo que queda es el estado de la implementación, para que se pueda
reanudar sin reconstruir nada de la conversación.

Lo resuelto, por si alguien llega buscándolo: **D8** (forma de la redacción de `special_requests`,
ratificada), **D9** (columnas de reintento, ratificada → [ADR 0007](../../../docs/adr/0007-webhook-event-retry-columns.md)),
**D15** (no auditar la lectura anónima, ratificada → tercera excepción nombrada de la regla 9 de
`sdd/steering/security.md`), **D6** (presupuesto por IP, aceptado con disparador) y **D1** (el token en
los logs del borde, aceptado en dev con Transform Rule antes del primer tenant real). La tabla de
cierre está en `design.md` § Open questions.

---

## 1. La implementación está a medias (secciones 1 y 2 de 6)

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
  - **Los dos paneles cerrados en PASS**, siete reviewers cada uno, con dos rondas de arreglo en la
    sección 2 (el máximo). Catorce hallazgos aceptados y arreglados entre ambos.
  - **Pendiente**: las secciones 3 a 6 completas. **La 3 ya no está bloqueada**: D8 quedó ratificada,
    así que 3.1 y 3.2 se implementan tal como están escritas, sin reescribir nada.
  - **Suite completa en verde**: 4065 pasan, 35 se saltan (los `skip` son placeholders preexistentes
    de `tests/properties/test_state_machine.py`, ajenos a este change). `alembic upgrade head`,
    `alembic check` y `alembic downgrade base` limpios; las dos mitades del contrato sin deriva.
    La tarea 6.1 vuelve a correrla al cerrar el change.

  **Dos deudas con disparador, que no bloquean nada ahora pero no deben perderse** (las dos están
  razonadas en `design.md`, esto es sólo el recordatorio):

  1. **La allowlist de IPs del proveedor** (D6), cuando se llegue a 25-50 unidades o a la primera
     rotación que provoque un `429` cruzado, lo que ocurra primero.
  2. **La Transform Rule de Cloudflare** que redacte `/api/v1/webhooks/*` en los logs del borde (D1),
     **antes de que entre el primer tenant real**. Hoy la exposición es a la propia cuenta de Jose;
     con un segundo cliente deja de serlo.

  Una observación que el panel de CI/CD dejó y que **no** es de este change: el comentario del
  servicio `frontend` en `docker-compose.deploy.yml` y la entrada `sdd/roadmap/api-ingress-routing.md`
  siguen redactados como si el camino de entrada de Beds24 estuviera sin decidir, cuando el proxy
  genérico ya lo resuelve. Texto obsoleto, no un hueco funcional: candidato a un change propio.

- **Dónde vive el trabajo**: worktree
  `/Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+reservations-webhooks`, rama
  `sdd/reservations-webhooks`, publicada en `origin`. Su stack de Docker está levantado; `make down`
  antes de borrar el worktree.
- **Comando para reanudar**: `/sdd:run reservations-webhooks 3` — **con `/clear` antes**, que es donde
  está el ahorro: esta sesión llegó a ~$95 y la sección 3 no necesita nada de su contexto.
