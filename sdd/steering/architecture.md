---
phases: [design, tasks]
---

# Architecture — AutoHostAI

Diagramas: `docs/diagrams/2026-07-13_autohost-{c4-contenedores,maquina-estados,secuencia-limpieza,secuencia-mantenimiento}.png`, `docs/diagrams/2026-08-09_autohost-hexagonal-dominios.png` y `docs/diagrams/2026-08-06_autohost-er-entidades.png`.

El de entidades se regeneró en `pms-provider-resolution` al entrar `pms_credentials` y `properties.pms_provider`: 28 entidades, 67 relaciones. El anterior, `2026-07-31_...`, se borró; y aquel a su vez había sustituido a `2026-07-30_..._-core`, cuyo sufijo nunca describió su alcance real. **Se genera desde la metadata de SQLAlchemy**, no a mano, así que refleja el esquema y no lo que alguien recordaba de él.

El hexagonal se regeneró en `dashboard-api` (el `2026-07-13_...` se borró). Dibujaba **trece** cajas de dominio y ya le faltaban `reviews` y `audit` desde `domain-foundation-financial`; ahora dibuja **dieciséis**, con `dashboard` marcado aparte porque es el único de solo lectura y sin `infrastructure/` propia.

**Dieciséis cajas y diecisiete dominios no se contradicen**, y conviene decirlo porque la cuenta no cuadra a simple vista (el panel de documentación de `dashboard-api` la encontró sin cuadrar en una redacción anterior de este párrafo): el 17.º es **`integrations`**, que el diagrama sitúa en el anillo de adaptadores y no dentro del hexágono, porque eso es exactamente lo que es — el borde por el que se habla con sistemas externos. El diagrama anterior ya lo dibujaba así. `README.md` cuenta diecisiete porque cuenta directorios bajo `backend/app/`.

Al contrario que el de entidades, éste **no** se genera desde el código: describe una decisión de arquitectura, así que lo actualiza a mano el change que la cambia.

## Forma del sistema

**Monolito modular** con arquitectura hexagonal, separado por dominios de negocio (PRD §3.2): `auth`, `tenants`, `properties`, `reservations`, `guests`, `cleaning`, `maintenance`, `messaging`, `access`, `pricing`, `statements`, `notifications`, `timeline`, `integrations`. Sin microservicios en MVP; el código debe permitir extraer servicios en el futuro.

`integrations` está en esa lista y es un dominio de pleno derecho en el código —tiene su directorio bajo `backend/app/`, y por eso `README.md` lo cuenta—, pero el diagrama hexagonal lo dibuja **en el anillo de adaptadores y no dentro del hexágono**, porque es el borde por el que se habla con sistemas externos y no una regla de negocio que proteger. Las dos cosas son ciertas y describen ejes distintos: dónde vive el código y qué papel juega. Se dice aquí porque leídas seguidas parecen contradecirse (panel de documentación de `dashboard-api`).

Dos dominios más que **no** están en la lista de PRD §3.2, añadidos en `domain-foundation-financial`: `reviews` (PRD §7.20-7.21) y `audit` (§7.25). Se descartó plegar las reviews en `statements` —mezclaría reporting financiero con contenido de OTAs— y alojar `AuditLog` en `app/core/`, que es infraestructura compartida y no aloja entidades de negocio. La divergencia se justifica en que `audit` es transversal exactamente igual que `timeline`, que el propio §3.2 ya lista como dominio de pleno derecho.

Monorepo: `/backend` (FastAPI + Celery, con `backend/devops/Dockerfile`), `/frontend` (Next.js, con `frontend/devops/Dockerfile`). Sin `/docker` a nivel de raíz — `docker-compose.yml` y `Makefile` orquestando todo el stack viven en la raíz del repo (change `local-environment`). Despliegue remoto (IaC/CI-CD): convención en `infra/` — ver `steering/infra.md`, ortogonal a este layout por dominio.

## Decisiones firmes

- **Todo sistema externo detrás de adapter** (PRD §3.3): PMSAdapter, AccessProviderAdapter, AIAdapter, WhatsAppAdapter, EmailAdapter, PhoneAdapter, SESHospedajesAdapter, PricingDataAdapter, StorageAdapter, DoorSensorAdapter. El core nunca se acopla a un proveedor. MVP = implementaciones mock/manual con la interfaz definitiva.
- **PropertyStateMachine es el único lugar donde ocurren transiciones de estado** (PRD §8). Estados y transiciones son los del PRD, nombres exactos. Cada transición persiste `PropertyStateTransition` + `TimelineEvent`.
- **Timeline inmutable y ciudadano de primera clase** (PRD §10): nunca se editan eventos pasados; toda acción relevante lo genera.
- **Capa de accesos: decisión abierta** ([ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md), decisión 5). PRD §5.5 la daba por cerrada ("el flujo pasa por el PMS" porque GrinPass no tendría API); su premisa no se sostiene —GrinPass no tiene API pública *todavía* pero está receptivo— y Beds24 trae TTLock/Nuki nativos más una Arrivals API para sistemas de accesos, así que puede resolverse sin GrinPass. Nada debe asumir una vía concreta hasta que se decida; el MVP va con `ManualAccessAdapter`. Lo que **sí** sigue firme de §5.5-5.6: `OCCUPIED_ESTIMATED` se calcula sin sensor de puerta y nada puede requerir `DOOR_OPENED`.
- Jobs programados = Celery beat (PRD §8.3), SLA enforcement cada minuto sobre `NotificationLog`.
- API REST `/api/v1/` con las convenciones del PRD §23 (paginación, errores `{error:{code,...}}`, ISO 8601 UTC, Bearer JWT).

## Anti-patrones (prohibido)

- Acoplar dominio a proveedor externo sin adapter.
- Transiciones de estado fuera de `PropertyStateMachine`.
- Lógica dependiente de eventos de apertura de puerta.
- Scraping o automatización no autorizada contra GrinPass.
- Empezar módulos por la UI (el orden es backend-first, PRD §26).
- Queries sin scope de tenant (ver `security.md`).
