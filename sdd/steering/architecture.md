---
phases: [design, tasks]
---

# Architecture — AutoHostAI

Diagramas: `docs/diagrams/2026-07-13_autohost-{c4-contenedores,maquina-estados,secuencia-limpieza}.png`, `docs/diagrams/2026-08-09_autohost-hexagonal-dominios.png`, `docs/diagrams/2026-08-23_autohost-er-entidades.png` y `docs/diagrams/2026-08-23_autohost-secuencia-mantenimiento.png`.

El de secuencia de mantenimiento se regeneró en `tech-cycle-completion` y el `2026-08-15_...` se borró. Es la primera regeneración de esta serie que se debe a **pasos del ciclo** y no a la arquitectura que lo rodea: `start` pasa a llamarse `en_route` —mismos orígenes (`ACCEPTED`) y mismo destino (`IN_PROGRESS`), ruta `POST /api/v1/incidents/{incident_id}/en-route`, y el evento de timeline pasa a ser `TECHNICIAN_EN_ROUTE`— y entra `reject` (`ASSIGNED`/`ACCEPTED` → `CLASSIFIED`), que borra los **tres** campos de la asignación vigente (`assigned_technician_id`, `eta_at`, `assignment_note`), cancela el plazo de SLA de la notificación `TECHNICIAN_ASSIGNED`, notifica al `PROPERTY_MANAGER` con un `INCIDENT_REJECTED` **sin plazo propio** y escribe `TECHNICIAN_REJECTED`. `resume_work` conserva `TECHNICIAN_STARTED`, así que el dibujo tiene que enseñar los dos eventos y no uno; `accept` y `en-route` comparten un `eta_at` opcional, y `resolve` gana un `materials` opcional junto al `final_cost` obligatorio. Regenerado **sin abrir el PNG anterior** —mirarlo cuesta ~140k de contexto—, derivando el contenido del `_TRANSITIONS` de `maintenance/domain/entities.py`, de sus casos de uso y de `docs/maintenance.md`. El anterior, `2026-08-15_...`, salió de `maintenance`, y al generarlo se borró el `2026-07-13_...`. Aquél tampoco era una actualización cosmética: aquél dibujaba un participante `AIAdapter` clasificando **dentro de la petición que crea la incidencia**, y este change decidió lo contrario en sus dos decisiones de cabecera — D1 declara un puerto propio de `maintenance` (`IncidentClassifier`) para no colgar del `MockAIAdapter` que el repo ya asignó a `messaging-ai`, y D2 saca la clasificación a un job de Celery. Mostraba además «subir fotos», que el change deja fuera de alcance, y le faltaban el SLA, `WAITING_EXTERNAL_PARTS` y la segunda puerta de aprobación sobre `final_cost`. Un diagrama que enseña la arquitectura rechazada es peor que no tenerlo, porque nadie sospecha de él.

El de entidades se regeneró en `tech-cycle-completion` al ganar `incidents` dos columnas, `eta_at` y `materials`: **ninguna de las dos lleva clave ajena**, así que las relaciones no se movieron y sólo lo hizo el recuento de columnas, de 416 a 418. Lo que quedó obsoleto, igual que con `assignment_note`, fue el dibujo de la tabla `incidents`, a la que le faltaban dos filas. Medido contra la metadata: **31 entidades, 418 columnas, 76 relaciones** (74 pares de tablas distintos). El anterior, `2026-08-22_...`, se borró; aquél se regeneró **dos veces el mismo día** y su párrafo era el resultado de fusionar las dos: `tech-incident-context` lo regeneró al ganar `incidents` la columna `assignment_note`, que **no lleva clave ajena** y por tanto no movió los recuentos de cabecera; `cleaner-incident-report` lo regeneró al entrar `incidents.cleaning_task_id`, que **sí** es clave ajena y suma exactamente una, y dejó la cuenta en 31 entidades, 416 columnas y 76 relaciones. El anterior a ése, `2026-08-11_...`, se borró; aquél salió de `guest-portal-api` al entrar `guest_access_tokens`, con las mismas 31 entidades y **75** relaciones, y a su vez sustituyó al `2026-08-10_...`; aquel salió de `auth-account-recovery` con 30 y 73 al entrar `password_reset_tokens` y `users.must_change_password`, y a su vez había sustituido al `2026-08-09_...` de `reservations-webhooks` (29 y 71, al entrar `webhook_endpoints`), que había sustituido al `2026-08-06_...` de `pms-provider-resolution` (28 y 67), y ése a `2026-07-31_...` y a `2026-07-30_..._-core`, cuyo sufijo nunca describió su alcance real. **Se genera desde la metadata de SQLAlchemy**, no a mano, así que refleja el esquema y no lo que alguien recordaba de él.

**El criterio de cuándo se regenera el de secuencia sigue en pie, y una versión anterior de este
párrafo lo enunció al revés.** Decía «NO se regenera», que era la conclusión de un caso y no la
regla: `cleaner-incident-report` no lo tocó porque **añade una puerta de entrada nueva, no un paso
nuevo del ciclo**, y el PNG dibuja la secuencia *desde que la incidencia existe* sin enumerar las
fuentes de creación. `tech-cycle-completion` es el caso contrario —renombra un paso y añade otro— y
por eso sí lo regeneró. La regla, entonces: se regenera cuando cambia un **paso** de la secuencia
que dibuja (su nombre, sus orígenes, su destino, su ruta o el evento de timeline que escribe), no
cuando cambia quién o qué la origina. Lo que el dibujo se compromete a enseñar es lo que
`maintenance` documentó al generarlo por primera vez —el job de clasificación fuera de la petición,
el SLA, `WAITING_EXTERNAL_PARTS` y la segunda puerta de aprobación sobre `final_cost`— más los pasos
del ciclo del técnico, que es lo que `tech-cycle-completion` movió. Y se decide **sin abrir el PNG**:
la pregunta se contesta con lo que cada change escribió al generarlo.

**No hay ninguna rotura en la serie, y conviene decirlo porque una versión anterior de este párrafo afirmó que sí.** `cleaner-incident-report` llegó a decir que el esquema tenía 77 columnas con clave ajena antes del change y 78 después, y que por tanto entre `guest-portal-api` y hoy habían entrado dos columnas sin que nadie actualizase la cifra. **Era falso, y el error estaba en la forma de contar.** Medido las tres maneras sobre la metadata fusionada el 2026-08-22:

- **columnas distintas con al menos una clave ajena — la regla de este documento: 76**;
- restricciones `ForeignKeyConstraint`: **76**, que coincide con la anterior;
- objetos `ForeignKey` a nivel de columna: **78**, que es la cifra que se coló.

Las dos últimas difieren porque hay dos claves ajenas **compuestas** —`fk_guest_access_tokens_reservation_within_tenant` y `fk_reservations_guest_within_tenant`—, y cada una mete un `tenant_id` que ya pertenecía a otra clave ajena, de modo que contar objetos duplica `guest_access_tokens.tenant_id` y `reservations.tenant_id`. Bajo la regla de aquí la serie encaja sin saltos: **75** en `guest-portal-api`, más la única clave ajena que añade `cleaner-incident-report`, son **76**. El «76» con el que llegó su proposal era, por tanto, el correcto, y lo que estaba mal era la corrección. **Y para quien vaya a contar las flechas del dibujo en vez de las columnas: son 78**, porque el generador traza una arista por objeto `ForeignKey` y las dos compuestas duplican su `tenant_id`. El PNG y esta cifra no se contradicen; cuentan cosas distintas, y la de este documento es la de columnas.

**Qué cuenta «relaciones», que hasta ahora no estaba escrito**: una por **columna con clave ajena**. Conviene fijarlo porque la cifra se venía arrastrando sin regla y no había forma de saber si dos cifras eran comparables. Bajo esta regla la serie sí lo es —71 de `reservations-webhooks`, más las dos claves ajenas de `password_reset_tokens` son las 73 de `auth-account-recovery`, más las dos de `guest_access_tokens` (`tenant_id` y `reservation_id`) son las **75** con las que `guest-portal-api` dejó esta serie— y sólo la de `pms-provider-resolution` queda fuera: aquel «67» contaba otra cosa, porque su propio esquema daba 70 con esta regla. Si se cuentan **pares de tablas distintos** en vez de columnas, aquellas 75 eran **73**: hay dos columnas que participan cada una en dos claves ajenas, `guest_access_tokens.tenant_id` y `reservations.tenant_id`, por las compuestas que `guest-portal-api` estrenó. **Las cifras vigentes son las de arriba —76 columnas y 74 pares—, no estas dos**, que son las del párrafo tal y como quedó en `guest-portal-api` y se conservan aquí porque son las que fijan la regla.

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
