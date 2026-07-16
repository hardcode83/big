# AutoHostAI — PRD Técnico v5 (Fuente de Verdad)

**Versión:** v5  
**Fecha:** 2026-07-08  
**Basado en:** v4, revisado y completado por arquitecto senior.  
**Objetivo:** especificación cerrada y sin ambigüedades para programar el MVP completo de AutoHostAI sin preguntas adicionales.

---

## 0. Instrucción principal para Claude

Actúa como **Principal Software Architect, Staff Engineer y Senior Full Stack Engineer**.

Diseña e implementa AutoHostAI con rigor profesional. No inventes integraciones externas no confirmadas. Cuando falten credenciales, APIs o documentación real, crea interfaces limpias con adapters mock/stub que permitan que el sistema funcione end-to-end en modo demo/manual.

**No hagas preguntas aclaratorias.**  
Cuando falte información, usa los supuestos explícitos de este documento y marca esos puntos como `ASSUMPTION` o `EXTERNAL_DEPENDENCY` en la documentación técnica generada.

El objetivo es construir el producto completo en modo MVP operativo, no una maqueta visual.

---

## 1. Contexto de negocio

La propietaria tiene 2 viviendas turísticas gestionadas por una empresa externa llamada **MAGNO**. AutoHostAI sustituye el trabajo operativo de MAGNO, reduce la dependencia de la gestora y permite escalar posteriormente a más viviendas y finalmente venderse como SaaS.

AutoHostAI **NO es un PMS** y **NO construye un Channel Manager propio**.

AutoHostAI es una **capa inteligente operativa encima de un PMS/Channel Manager externo**.

El PMS/Channel Manager externo es la fuente de verdad para: reservas, calendarios, disponibilidad, canales OTA (Airbnb, Booking.com, Expedia), precios publicados y conexión con GrinPass/eHotel.

AutoHostAI sustituye la operación humana de la gestora:

- atención al huésped (mensajería + IA)
- coordinación de limpiezas
- coordinación de mantenimiento
- seguimiento de incidencias
- reporting operativo al propietario
- comunicación con limpiadoras y técnicos
- checklist de limpieza con fotos
- soporte operativo 24/7 con IA y escalado humano
- pricing dinámico v1 (basado en reglas)
- dashboard en tiempo real del estado de cada vivienda
- timeline completo y auditable de todos los eventos

---

## 2. Información contractual sobre MAGNO

MAGNO prestaba estos servicios que AutoHostAI debe digitalizar/automatizar:

1. creación y revisión de anuncios en OTAs
2. gestión de reservas, pre-reservas y confirmaciones
3. gestión de calendarios de ocupación
4. organización de entradas y salidas
5. avisos e instrucciones al personal de limpieza y mantenimiento
6. entrega de llaves/accesos
7. gestión de pagos
8. atención telefónica 24h
9. respuesta a comentarios y valoraciones
10. revenue management
11. limpieza
12. lavandería
13. reposición de amenities
14. mantenimiento general
15. gestión de especialistas
16. acceso a programa de gestión
17. documentación para control policial de huéspedes (SES.Hospedajes)

Las tareas físicas (limpieza, lavandería, reparaciones) siguen siendo ejecutadas por personas externas. AutoHostAI coordina, notifica y audita.

**Regla contractual clave:** gastos superiores a 100 EUR requieren aprobación del propietario. Esta regla es el umbral por defecto en el sistema.

---

## 3. Principios de arquitectura

### 3.1 Principio más importante

**Una vivienda es una máquina de estados.**

El producto no es una colección de pantallas. Es un sistema operativo que permite entender el estado real de cada vivienda en menos de 10 segundos.

Estados operacionales (definición canónica — usar estos nombres exactos en todo el código):

| Estado | Significado |
|--------|-------------|
| `VACANT_READY` | Libre, limpia, sin reserva próxima |
| `AWAITING_CHECKIN` | Reserva activa hoy, huésped aún no llega (dentro de ventana check-in) |
| `OCCUPIED_ESTIMATED` | Huésped estimado dentro según hora de check-in (no confirmado físicamente) |
| `AWAITING_CLEANING` | Huésped salido, limpieza pendiente de asignar |
| `CLEANING_SCHEDULED` | Limpieza asignada, limpiadora pendiente de empezar |
| `CLEANING_IN_PROGRESS` | Limpiadora trabajando activamente |
| `READY_FOR_NEXT_GUEST` | Limpieza completada, reserva próxima (≥1 día) |
| `MAINTENANCE_REQUIRED` | Incidencia no crítica bloquea o requiere atención |
| `CRITICAL_INCIDENT` | Incidencia crítica — requiere acción inmediata |
| `BLOCKED_BY_OWNER` | Bloqueada manualmente por propietario |
| `OUT_OF_SERVICE` | No vendible temporalmente (decisión operativa) |

Cada transición de estado genera un `TimelineEvent` persistente y auditable.

### 3.2 Arquitectura del sistema

**Modular monolith** con arquitectura hexagonal y separación por dominios de negocio.

No usar microservicios en el MVP. El código debe ser modular para extraer servicios en el futuro si es necesario.

Dominios:

- `auth` — autenticación y autorización
- `tenants` — gestión multi-tenant
- `properties` — viviendas y máquina de estados
- `reservations` — reservas e importación PMS
- `guests` — gestión de huéspedes y datos legales
- `cleaning` — módulo de limpieza completo
- `maintenance` — incidencias y técnicos
- `messaging` — conversaciones y IA
- `access` — gestión de accesos (GrinPass/manual)
- `pricing` — reglas y recomendaciones de precio
- `statements` — reporting financiero y liquidaciones
- `notifications` — sistema de notificaciones y SLA
- `timeline` — sistema de eventos centralizado
- `integrations` — adapters externos

### 3.3 Todos los sistemas externos detrás de adapters

El core de negocio nunca se acopla directamente a un proveedor externo. Siempre usar el adapter correspondiente:

| Adapter | Propósito | MVP implementation |
|---------|-----------|-------------------|
| `PMSAdapter` | PMS/Channel Manager | `MockPMSAdapter` + CSV import |
| `AccessProviderAdapter` | Cerraduras (GrinPass) | `ManualAccessAdapter` + `MockAccessAdapter` |
| `AIAdapter` | Clasificación + generación IA | `MockAIAdapter` |
| `WhatsAppAdapter` | Mensajería WhatsApp | `MockNotificationAdapter` |
| `EmailAdapter` | Email transaccional | `ConsoleEmailAdapter` dev / SMTP prod |
| `PhoneAdapter` | Llamadas y transcripciones | `MockPhoneAdapter` |
| `SESHospedajesAdapter` | Registro policial España | `MockSESHospedajesAdapter` |
| `PricingDataAdapter` | Datos externos de mercado | `MockPricingDataAdapter` |
| `StorageAdapter` | Almacenamiento de archivos/fotos | `LocalStorageAdapter` dev / S3 prod |
| `DoorSensorAdapter` | Sensor de puerta (futuro) | deshabilitado por defecto |

---

## 4. Stack tecnológico

### Frontend

- Next.js 14+ (App Router)
- TypeScript (strict mode)
- Tailwind CSS
- shadcn/ui
- TanStack Query (React Query v5)
- Zustand para estado ligero de UI
- react-i18next para internacionalización
- Diseño responsive mobile-first

### Backend

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x (async)
- Alembic para migraciones
- Pydantic v2 para validación
- PostgreSQL 16
- Redis 7 para colas, jobs y cache
- Celery con Redis broker para background jobs y SLA enforcement

### Auth

- JWT (access token 15 min + refresh token 7 días)
- RBAC enforced en backend
- Password hashing con bcrypt
- Refresh token rotation

### Infra MVP (desarrollo local)

```yaml
# docker-compose.yml services:
- postgres:16
- redis:7
- backend (FastAPI + Celery worker)
- frontend (Next.js)
```

### Testing

- Pytest + pytest-asyncio (backend)
- Testing Library (frontend)
- Playwright para flujos E2E críticos (login, cleaning flow, incident flow)
- Coverage mínima: 80% en domain services

### Almacenamiento de archivos

- Dev: `LocalStorageAdapter` guarda en `/app/media/` montado en volumen Docker
- Producción futura: S3-compatible (Cloudflare R2 o AWS S3)
- Las URLs de fotos siempre son generadas por `StorageAdapter.get_signed_url(key, expires_in_seconds)`
- Nunca exponer paths internos directamente al cliente

### Internacionalización

- Backend: todos los mensajes de sistema, logs y errores técnicos en inglés
- Frontend: traducciones ES/EN en archivos JSON bajo `locales/es/` y `locales/en/`
- Idioma de respuestas a huéspedes: detectado automáticamente, configurable por reserva
- Idioma del dashboard: preferencia del usuario autenticado

---

## 5. Decisiones cerradas

### 5.1 Mercado inicial

España.

### 5.2 Idiomas MVP

Español e inglés.

### 5.3 Plataforma

Web responsive mobile-first. Sin app nativa en MVP.

### 5.4 PMS externo

No se construye PMS propio. El PMS es externo con API abierta.

Candidatos por prioridad:

1. **Octorate** — candidato preferente MVP (posible bajo coste para 2 apartamentos)
2. **Smoobu** — alternativa fuerte (listado por GrinPass como provider compatible)
3. **Beds24** — alternativa técnica flexible
4. **Hostaway** — candidato futuro fase SaaS/enterprise

El MVP funciona con `MockPMSAdapter` y/o importación manual/CSV. La interfaz del adapter debe ser idéntica para todos los candidatos.

### 5.5 GrinPass / eHotel / IBINTEL — Decisión arquitectónica definitiva

Las cerraduras instaladas son GrinPass/IBINTEL. No se pueden cambiar (inversión realizada).

**Información confirmada de GrinPass:**
- No ofrece API directa salvo proyectos muy grandes
- Los códigos se generan importando reservas desde el PMS
- Necesita PMS con API abierta y documentada
- Si el huésped abre con PIN, **el evento de apertura no es fiable** (limitación técnica conocida)
- Solo se registra apertura si se usa la web de GrinPass
- Pueden notificar por Telegram o email alarmas de fallos de cerradura

**Conclusión arquitectónica inamovible:**

AutoHostAI **NO depende de API directa de GrinPass**. El flujo es:

```
Airbnb / Booking.com
        ↓
PMS con API abierta (Octorate / Smoobu / Beds24)
        ↓
GrinPass importa reservas del PMS
        ↓
GrinPass genera códigos de acceso automáticamente
        ↓
AutoHostAI coordina operación y comunica instrucciones al huésped
```

AutoHostAI gestiona el acceso a través de:
- `ManualAccessAdapter`: operador introduce código manualmente
- `ExternalManagedAccessAdapter`: registra que el acceso se gestiona en GrinPass
- `MockAccessAdapter`: para demo

**Prohibido:** scraping, automatización no autorizada contra GrinPass.

### 5.6 Estado de ocupación sin sensor de puerta

`OCCUPIED_ESTIMATED` se calcula por combinación de:
- hora programada de check-in superada
- reserva confirmada activa
- ausencia de incidencias críticas
- confirmaciones del huésped (mensajes recibidos)
- señales manuales del operador

**No diseñar ninguna lógica que requiera `DOOR_OPENED` como fuente obligatoria.**

Soporte futuro para sensor (GrinPass premium): implementar `DoorSensorAdapter` con eventos `DOOR_OPENED_SENSOR`, deshabilitado por defecto.

---

## 6. Roles de usuario (RBAC)

### `SUPER_ADMIN`

- ver todos los tenants
- gestionar configuración global
- activar/desactivar integraciones globales
- impersonation auditada (si se implementa)

### `TENANT_OWNER`

- ver sus propiedades y reservas
- ver ingresos y statements
- ver timeline completo
- ver y gestionar incidencias
- aprobar/rechazar gastos por encima del umbral configurado
- bloquear fechas (`BLOCKED_BY_OWNER`)
- configurar preferencias del tenant
- ver conversaciones (solo lectura)

### `PROPERTY_MANAGER`

- gestionar reservas (crear, editar, cancelar)
- gestionar limpiezas (asignar, reasignar, validar)
- gestionar mantenimiento (asignar técnicos)
- responder conversaciones
- revisar y aprobar respuestas de IA
- coordinar técnicos
- acceder a todos los datos operativos

### `CLEANER`

- ver tareas asignadas (solo las suyas)
- aceptar/rechazar tareas
- ver checklist de limpieza
- marcar items del checklist como completados
- subir fotos requeridas
- reportar incidencias durante limpieza
- finalizar tarea de limpieza

### `TECHNICIAN`

- ver tickets asignados (solo los suyos)
- aceptar/rechazar tickets
- actualizar estado del ticket
- subir fotos (antes y después)
- añadir coste y materiales
- cerrar incidencia

### `GUEST`

Sin panel completo en MVP. Acceso por token seguro de un solo uso a:
- instrucciones de check-in
- formulario de check-in
- reporte de incidencia
- contacto con soporte
- guía básica de la vivienda

---

## 7. Entidades del dominio

### 7.1 Tenant

```
id                  UUID PK
name                VARCHAR(200) NOT NULL
billing_email       VARCHAR(255) NOT NULL
country             VARCHAR(2) NOT NULL DEFAULT 'ES'
timezone            VARCHAR(50) NOT NULL DEFAULT 'Europe/Madrid'
default_language    VARCHAR(5) NOT NULL DEFAULT 'es'
status              ENUM('ACTIVE','SUSPENDED','CANCELLED') NOT NULL DEFAULT 'ACTIVE'
created_at          TIMESTAMPTZ NOT NULL
updated_at          TIMESTAMPTZ NOT NULL
```

### 7.2 TenantConfig

Un registro por tenant. Configura umbrales y comportamiento del sistema.

```
id                              UUID PK
tenant_id                       UUID FK→Tenant NOT NULL UNIQUE
owner_approval_threshold_eur    DECIMAL(10,2) NOT NULL DEFAULT 100.00
ai_confidence_threshold         DECIMAL(3,2) NOT NULL DEFAULT 0.75
sla_critical_minutes            INTEGER NOT NULL DEFAULT 5
sla_high_minutes                INTEGER NOT NULL DEFAULT 15
sla_medium_minutes              INTEGER NOT NULL DEFAULT 240
sla_low_minutes                 INTEGER NOT NULL DEFAULT 480
checkin_window_hours_before     INTEGER NOT NULL DEFAULT 2
checkout_ready_hours_after      INTEGER NOT NULL DEFAULT 1
auto_create_cleaning_task       BOOLEAN NOT NULL DEFAULT TRUE
cleaning_photo_required         BOOLEAN NOT NULL DEFAULT TRUE
storage_type                    ENUM('LOCAL','S3') NOT NULL DEFAULT 'LOCAL'
notification_email_enabled      BOOLEAN NOT NULL DEFAULT TRUE
notification_whatsapp_enabled   BOOLEAN NOT NULL DEFAULT FALSE
created_at                      TIMESTAMPTZ NOT NULL
updated_at                      TIMESTAMPTZ NOT NULL
```

### 7.3 User

```
id              UUID PK
tenant_id       UUID FK→Tenant NOT NULL
name            VARCHAR(200) NOT NULL
email           VARCHAR(255) NOT NULL
phone           VARCHAR(30)
password_hash   VARCHAR(255) NOT NULL
role            ENUM('SUPER_ADMIN','TENANT_OWNER','PROPERTY_MANAGER','CLEANER','TECHNICIAN') NOT NULL
status          ENUM('ACTIVE','INACTIVE','SUSPENDED') NOT NULL DEFAULT 'ACTIVE'
preferred_language  VARCHAR(5) NOT NULL DEFAULT 'es'
last_login_at   TIMESTAMPTZ
created_at      TIMESTAMPTZ NOT NULL
updated_at      TIMESTAMPTZ NOT NULL

UNIQUE(tenant_id, email)
INDEX(tenant_id, role)
INDEX(tenant_id, status)
```

### 7.4 Property

```
id                          UUID PK
tenant_id                   UUID FK→Tenant NOT NULL
name                        VARCHAR(200) NOT NULL
internal_code               VARCHAR(50) NOT NULL
pms_external_id             VARCHAR(200)         -- ID de la propiedad en el PMS externo
address_line1               VARCHAR(200)
address_line2               VARCHAR(200)
city                        VARCHAR(100)
province                    VARCHAR(100)
postal_code                 VARCHAR(20)
country                     VARCHAR(2) NOT NULL DEFAULT 'ES'
timezone                    VARCHAR(50) NOT NULL DEFAULT 'Europe/Madrid'
max_guests                  INTEGER NOT NULL DEFAULT 2
bedrooms                    INTEGER NOT NULL DEFAULT 1
bathrooms                   INTEGER NOT NULL DEFAULT 1
current_operational_state   ENUM(PropertyOperationalState) NOT NULL DEFAULT 'VACANT_READY'
default_check_in_time       TIME NOT NULL DEFAULT '15:00'
default_check_out_time      TIME NOT NULL DEFAULT '11:00'
wifi_name                   VARCHAR(200)
wifi_password_encrypted     TEXT                 -- cifrado en reposo con Fernet/AES
access_notes                TEXT
cleaning_notes              TEXT
emergency_notes             TEXT
status                      ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE'
created_at                  TIMESTAMPTZ NOT NULL
updated_at                  TIMESTAMPTZ NOT NULL

UNIQUE(tenant_id, internal_code)
INDEX(tenant_id, current_operational_state)
INDEX(tenant_id, pms_external_id)
```

### 7.5 PropertyStateTransition

Histórico inmutable de todos los cambios de estado de cada propiedad.

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
property_id         UUID FK→Property NOT NULL
from_state          ENUM(PropertyOperationalState)
to_state            ENUM(PropertyOperationalState) NOT NULL
triggered_by        ENUM('SYSTEM','USER','SCHEDULER','WEBHOOK') NOT NULL
triggered_by_user_id UUID FK→User
reason              VARCHAR(500)
metadata            JSONB
created_at          TIMESTAMPTZ NOT NULL

INDEX(property_id, created_at DESC)
```

### 7.6 Guest

```
id                      UUID PK
tenant_id               UUID FK→Tenant NOT NULL
full_name               VARCHAR(300) NOT NULL
email                   VARCHAR(255)
phone                   VARCHAR(30)
preferred_language      VARCHAR(5) DEFAULT 'es'
nationality             VARCHAR(2)               -- ISO 3166-1 alpha-2, requerido SES.Hospedajes
date_of_birth           DATE                     -- requerido SES.Hospedajes
document_type           ENUM('DNI','NIE','PASSPORT','RESIDENCE_CARD','OTHER')
document_number_encrypted TEXT                   -- cifrado en reposo
document_expiry_date    DATE
document_status         ENUM('NOT_PROVIDED','PENDING','PROVIDED','VERIFIED','REJECTED') NOT NULL DEFAULT 'NOT_PROVIDED'
legal_registration_status ENUM('NOT_REQUIRED','PENDING_GUEST_DATA','READY_TO_SUBMIT','SUBMITTED','FAILED','MANUAL_REVIEW') NOT NULL DEFAULT 'NOT_REQUIRED'
created_at              TIMESTAMPTZ NOT NULL
updated_at              TIMESTAMPTZ NOT NULL

INDEX(tenant_id, email)
```

### 7.7 Reservation

```
id                          UUID PK
tenant_id                   UUID FK→Tenant NOT NULL
property_id                 UUID FK→Property NOT NULL
guest_id                    UUID FK→Guest
external_pms_id             VARCHAR(200)          -- ID reserva en PMS externo
external_channel_id         VARCHAR(200)          -- ID reserva en canal OTA
channel                     ENUM('AIRBNB','BOOKING','EXPEDIA','DIRECT','MANUAL','OTHER') NOT NULL
status                      ENUM(ReservationStatus) NOT NULL DEFAULT 'PENDING'
check_in_date               DATE NOT NULL
check_out_date              DATE NOT NULL
check_in_time               TIME                  -- override del default de la propiedad
check_out_time              TIME                  -- override del default de la propiedad
nights                      INTEGER NOT NULL
adults                      INTEGER NOT NULL DEFAULT 1
children                    INTEGER NOT NULL DEFAULT 0
total_guests                INTEGER NOT NULL DEFAULT 1
gross_amount                DECIMAL(10,2)
ota_commission              DECIMAL(10,2)
net_amount                  DECIMAL(10,2)
currency                    VARCHAR(3) NOT NULL DEFAULT 'EUR'
payment_status              ENUM('PENDING','PAID','PARTIALLY_PAID','REFUNDED') NOT NULL DEFAULT 'PENDING'
access_status               ENUM('PENDING','CREATED_EXTERNAL','MANUAL_ADDED','DELIVERED','EXPIRED','NOT_REQUIRED') NOT NULL DEFAULT 'PENDING'
legal_registration_status   ENUM('NOT_REQUIRED','PENDING_GUEST_DATA','READY_TO_SUBMIT','SUBMITTED','FAILED','MANUAL_REVIEW') NOT NULL DEFAULT 'NOT_REQUIRED'
cleaning_required           BOOLEAN NOT NULL DEFAULT TRUE
special_requests            TEXT
internal_notes              TEXT
created_at                  TIMESTAMPTZ NOT NULL
updated_at                  TIMESTAMPTZ NOT NULL

UNIQUE(tenant_id, external_pms_id)    -- nullable, solo si viene de PMS
INDEX(property_id, check_in_date)
INDEX(property_id, check_out_date)
INDEX(tenant_id, status)
```

**ReservationStatus enum:**

```
PENDING
CONFIRMED
CANCELLED
CHECKED_IN_ESTIMATED
CHECKED_OUT_ESTIMATED
COMPLETED
NO_SHOW
```

### 7.8 TimelineEvent

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
property_id         UUID FK→Property NOT NULL
reservation_id      UUID FK→Reservation      -- nullable
actor_user_id       UUID FK→User             -- nullable
actor_type          ENUM('SYSTEM','USER','GUEST','SCHEDULER','WEBHOOK','AI') NOT NULL
event_type          ENUM(TimelineEventType) NOT NULL
severity            ENUM('INFO','WARNING','ERROR','CRITICAL') NOT NULL DEFAULT 'INFO'
title               VARCHAR(500) NOT NULL
description         TEXT
metadata            JSONB
created_at          TIMESTAMPTZ NOT NULL

INDEX(property_id, created_at DESC)
INDEX(tenant_id, event_type, created_at DESC)
INDEX(reservation_id, created_at DESC)
```

**TimelineEventType enum (lista completa):**

```
RESERVATION_IMPORTED
RESERVATION_CREATED_MANUAL
RESERVATION_UPDATED
RESERVATION_CANCELLED
CHECKIN_WINDOW_OPENED
CHECKOUT_WINDOW_REACHED
PROPERTY_STATE_CHANGED
ACCESS_CODE_PENDING
ACCESS_CODE_CREATED_EXTERNAL
ACCESS_CODE_MANUAL_ADDED
ACCESS_CODE_DELIVERED
GUEST_MESSAGE_RECEIVED
AI_RESPONSE_SENT
AI_ESCALATED_TO_HUMAN
HUMAN_RESPONSE_SENT
CLEANING_TASK_CREATED
CLEANER_ASSIGNED
CLEANER_ACCEPTED
CLEANER_REJECTED
CLEANING_STARTED
CLEANING_PHOTO_UPLOADED
CLEANING_COMPLETED
CLEANING_FAILED_VALIDATION
INCIDENT_CREATED
INCIDENT_CLASSIFIED
TECHNICIAN_ASSIGNED
TECHNICIAN_ACCEPTED
TECHNICIAN_EN_ROUTE
TECHNICIAN_STARTED
INCIDENT_RESOLVED
INCIDENT_CANCELLED
OWNER_APPROVAL_REQUIRED
OWNER_APPROVED_EXPENSE
OWNER_REJECTED_EXPENSE
LOCK_ALERT_RECEIVED
PRICE_RECOMMENDATION_CREATED
PRICE_UPDATED_EXTERNAL
LEGAL_REGISTRATION_SUBMITTED
REVIEW_IMPORTED
REVIEW_RESPONSE_DRAFTED
REVIEW_RESPONSE_APPROVED
SLA_BREACH_WARNING
NOTIFICATION_SENT
NOTIFICATION_FAILED
WEBHOOK_RECEIVED
```

### 7.9 CleaningTask

```
id                      UUID PK
tenant_id               UUID FK→Tenant NOT NULL
property_id             UUID FK→Property NOT NULL
reservation_id          UUID FK→Reservation      -- reserva de salida que originó la limpieza
assigned_cleaner_id     UUID FK→User             -- nullable
status                  ENUM(CleaningTaskStatus) NOT NULL DEFAULT 'CREATED'
scheduled_start         TIMESTAMPTZ
scheduled_end           TIMESTAMPTZ
accepted_at             TIMESTAMPTZ
started_at              TIMESTAMPTZ
completed_at            TIMESTAMPTZ
checklist_template_id   UUID FK→CleaningChecklistTemplate NOT NULL
notes                   TEXT
validation_status       ENUM('PENDING','PASSED','FAILED','WAIVED') NOT NULL DEFAULT 'PENDING'
validated_by_user_id    UUID FK→User
validated_at            TIMESTAMPTZ
created_at              TIMESTAMPTZ NOT NULL
updated_at              TIMESTAMPTZ NOT NULL

INDEX(property_id, status)
INDEX(assigned_cleaner_id, status)
```

**CleaningTaskStatus enum:**

```
CREATED
ASSIGNED
ACCEPTED
REJECTED
IN_PROGRESS
PENDING_REVIEW
COMPLETED
FAILED
CANCELLED
```

### 7.10 CleaningChecklistTemplate

```
id              UUID PK
tenant_id       UUID FK→Tenant NOT NULL
property_id     UUID FK→Property         -- nullable: si null aplica a todo el tenant
name            VARCHAR(200) NOT NULL
items           JSONB NOT NULL           -- ver schema abajo
required_photos JSONB NOT NULL           -- ver schema abajo
active          BOOLEAN NOT NULL DEFAULT TRUE
created_at      TIMESTAMPTZ NOT NULL
updated_at      TIMESTAMPTZ NOT NULL
```

**Schema `items` (array):**
```json
[
  {
    "id": "ventilate",
    "label_es": "Ventilar la vivienda",
    "label_en": "Ventilate the property",
    "required": true,
    "order": 1
  }
]
```

**Schema `required_photos` (array):**
```json
[
  {
    "id": "living_room",
    "label_es": "Salón",
    "label_en": "Living room",
    "required": true
  }
]
```

**Items por defecto:**
ventilate, remove_rubbish, check_fridge, clean_kitchen_surfaces, clean_sink, clean_bathroom, replace_toilet_paper, replace_towels, make_beds, check_linen, mop_floor, check_sofa, replenish_amenities, check_wifi_router, check_ac_remote, check_keys, report_damages, upload_photos.

**Fotos requeridas MVP:** living_room, bedroom, bathroom, kitchen, entrance, damage_if_found.

### 7.11 CleaningChecklistCompletion

Registro de los items completados para una tarea concreta.

```
id                  UUID PK
cleaning_task_id    UUID FK→CleaningTask NOT NULL
item_id             VARCHAR(100) NOT NULL       -- referencia a items[].id del template
completed           BOOLEAN NOT NULL DEFAULT FALSE
completed_at        TIMESTAMPTZ
completed_by        UUID FK→User
notes               TEXT

UNIQUE(cleaning_task_id, item_id)
```

### 7.12 CleaningPhoto

```
id                      UUID PK
cleaning_task_id        UUID FK→CleaningTask NOT NULL
uploaded_by             UUID FK→User NOT NULL
photo_type              VARCHAR(100) NOT NULL   -- referencia a required_photos[].id del template
storage_key             VARCHAR(500) NOT NULL   -- clave en StorageAdapter (nunca URL directa)
ai_validation_result    JSONB                   -- {passed: bool, issues: [], confidence: float}
created_at              TIMESTAMPTZ NOT NULL

INDEX(cleaning_task_id)
```

### 7.13 Incident

```
id                          UUID PK
tenant_id                   UUID FK→Tenant NOT NULL
property_id                 UUID FK→Property NOT NULL
reservation_id              UUID FK→Reservation      -- nullable
reported_by_user_id         UUID FK→User             -- nullable
reported_by_guest_token     VARCHAR(200)             -- nullable, token de huésped
source                      ENUM('GUEST','CLEANER','OWNER','SYSTEM','PMS','LOCK_ALERT') NOT NULL
category                    ENUM(IncidentCategory) NOT NULL DEFAULT 'OTHER'
severity                    ENUM('LOW','MEDIUM','HIGH','CRITICAL') NOT NULL DEFAULT 'MEDIUM'
status                      ENUM(IncidentStatus) NOT NULL DEFAULT 'OPEN'
title                       VARCHAR(300) NOT NULL
description                 TEXT NOT NULL
ai_summary                  TEXT
ai_classification           JSONB    -- {category, severity, confidence, reasoning}
assigned_technician_id      UUID FK→User
owner_approval_required     BOOLEAN NOT NULL DEFAULT FALSE
estimated_cost              DECIMAL(10,2)
approved_cost               DECIMAL(10,2)
final_cost                  DECIMAL(10,2)
resolved_at                 TIMESTAMPTZ
created_at                  TIMESTAMPTZ NOT NULL
updated_at                  TIMESTAMPTZ NOT NULL

INDEX(property_id, status)
INDEX(tenant_id, severity, status)
```

**IncidentCategory enum:**
```
ACCESS, LOCK, WIFI, ELECTRICITY, WATER, PLUMBING,
HVAC, APPLIANCE, NOISE, CLEANING, DAMAGE, SAFETY, OTHER
```

**IncidentStatus enum:**
```
OPEN
CLASSIFIED
AWAITING_OWNER_APPROVAL
ASSIGNED
ACCEPTED
IN_PROGRESS
WAITING_EXTERNAL_PARTS
RESOLVED
CANCELLED
```

### 7.14 Conversation

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
property_id         UUID FK→Property         -- nullable
reservation_id      UUID FK→Reservation      -- nullable
guest_id            UUID FK→Guest            -- nullable
channel             ENUM(ConversationChannel) NOT NULL
status              ENUM('OPEN','RESOLVED','ESCALATED','CLOSED') NOT NULL DEFAULT 'OPEN'
language            VARCHAR(5) NOT NULL DEFAULT 'es'
last_message_at     TIMESTAMPTZ
ai_enabled          BOOLEAN NOT NULL DEFAULT TRUE
escalation_status   ENUM('NONE','PENDING_HUMAN','HUMAN_HANDLING','RESOLVED') NOT NULL DEFAULT 'NONE'
created_at          TIMESTAMPTZ NOT NULL
updated_at          TIMESTAMPTZ NOT NULL

INDEX(tenant_id, status)
INDEX(reservation_id)
```

**ConversationChannel enum:**
```
WHATSAPP
AIRBNB_MSG
BOOKING_MSG
EMAIL
PHONE_TRANSCRIPT
MANUAL
```

### 7.15 Message

```
id                  UUID PK
conversation_id     UUID FK→Conversation NOT NULL
sender_type         ENUM('GUEST','OWNER','MANAGER','AI','SYSTEM') NOT NULL
sender_user_id      UUID FK→User             -- nullable
content             TEXT NOT NULL
language            VARCHAR(5)
ai_generated        BOOLEAN NOT NULL DEFAULT FALSE
confidence_score    DECIMAL(3,2)             -- 0.00 a 1.00
intent              VARCHAR(100)             -- ver intents en sección 13
metadata            JSONB
created_at          TIMESTAMPTZ NOT NULL

INDEX(conversation_id, created_at ASC)
```

### 7.16 AccessRecord

```
id              UUID PK
tenant_id       UUID FK→Tenant NOT NULL
property_id     UUID FK→Property NOT NULL
reservation_id  UUID FK→Reservation      -- nullable
provider        ENUM('GRINPASS','MANUAL','MOCK','EXTERNAL_MANAGED') NOT NULL DEFAULT 'MANUAL'
external_id     VARCHAR(200)             -- ID en sistema del proveedor si disponible
status          ENUM('PENDING','CREATED_EXTERNAL','MANUAL_ADDED','DELIVERED','EXPIRED','REVOKED') NOT NULL DEFAULT 'PENDING'
code_masked     VARCHAR(50)              -- últimos 2 dígitos visibles: "****23"
valid_from      TIMESTAMPTZ
valid_to        TIMESTAMPTZ
created_mode    ENUM('EXTERNAL_PMS_AUTOMATIC','MANUAL','MOCK') NOT NULL DEFAULT 'MANUAL'
notes           TEXT
created_at      TIMESTAMPTZ NOT NULL
updated_at      TIMESTAMPTZ NOT NULL

INDEX(reservation_id)
INDEX(property_id, valid_from, valid_to)
```

**Nota de seguridad:** nunca almacenar códigos de acceso en texto plano. Si se almacena, cifrar con la misma clave Fernet usada para datos de huésped. `code_masked` muestra solo los últimos 2 dígitos.

### 7.17 PricingRule

```
id                      UUID PK
tenant_id               UUID FK→Tenant NOT NULL
property_id             UUID FK→Property         -- nullable: si null aplica a todo el tenant
name                    VARCHAR(200) NOT NULL
active                  BOOLEAN NOT NULL DEFAULT TRUE
base_price              DECIMAL(10,2) NOT NULL
min_price               DECIMAL(10,2) NOT NULL
max_price               DECIMAL(10,2) NOT NULL
max_daily_change_pct    DECIMAL(5,2) NOT NULL DEFAULT 20.00  -- máximo cambio % por día
weekday_modifiers       JSONB NOT NULL DEFAULT '{}'          -- ver schema abajo
lead_time_rules         JSONB NOT NULL DEFAULT '[]'          -- ver schema abajo
occupancy_rules         JSONB NOT NULL DEFAULT '[]'          -- ver schema abajo
seasonality_rules       JSONB NOT NULL DEFAULT '[]'          -- ver schema abajo
event_rules             JSONB NOT NULL DEFAULT '[]'          -- ver schema abajo
created_at              TIMESTAMPTZ NOT NULL
updated_at              TIMESTAMPTZ NOT NULL
```

**Schema `weekday_modifiers`:**
```json
{
  "monday": 0,
  "tuesday": 0,
  "wednesday": 0,
  "thursday": 5,
  "friday": 15,
  "saturday": 20,
  "sunday": 10
}
```
Valores son porcentaje de variación sobre `base_price`. Positivo = incremento, negativo = descuento.

**Schema `lead_time_rules` (array, se evalúa en orden):**
```json
[
  {"days_before": 1, "modifier_pct": -20},
  {"days_before": 3, "modifier_pct": -10},
  {"days_before": 30, "modifier_pct": 5}
]
```
`days_before` = si la reserva es en menos de N días, aplicar modifier.

**Schema `occupancy_rules` (array):**
```json
[
  {"occupancy_pct_above": 80, "modifier_pct": 15},
  {"occupancy_pct_above": 50, "modifier_pct": 5},
  {"occupancy_pct_above": 20, "modifier_pct": -5}
]
```
`occupancy_pct_above` = si el calendario de la vivienda tiene más de N% de ocupación en los próximos 30 días.

**Schema `seasonality_rules` (array):**
```json
[
  {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8, "end_day": 31, "modifier_pct": 30},
  {"name": "easter", "start_month": 3, "start_day": 25, "end_month": 4, "end_day": 5, "modifier_pct": 20}
]
```

**Schema `event_rules` (array):**
```json
[
  {"name": "Local Festival", "date": "2026-08-15", "modifier_pct": 25}
]
```

**Fórmula de cálculo de precio recomendado:**

```python
def calculate_recommended_price(rule: PricingRule, date: date, days_before: int, occupancy_pct: float) -> Decimal:
    price = rule.base_price

    # 1. Modificador de día de semana
    weekday = date.strftime('%A').lower()
    price *= (1 + rule.weekday_modifiers.get(weekday, 0) / 100)

    # 2. Regla de anticipación (la que aplique con mayor days_before <= days_before)
    applicable_lead = [r for r in rule.lead_time_rules if days_before <= r['days_before']]
    if applicable_lead:
        most_specific = min(applicable_lead, key=lambda r: r['days_before'])
        price *= (1 + most_specific['modifier_pct'] / 100)

    # 3. Regla de ocupación
    applicable_occ = [r for r in rule.occupancy_rules if occupancy_pct >= r['occupancy_pct_above']]
    if applicable_occ:
        highest = max(applicable_occ, key=lambda r: r['occupancy_pct_above'])
        price *= (1 + highest['modifier_pct'] / 100)

    # 4. Reglas de temporada y eventos
    for rule_s in rule.seasonality_rules + rule.event_rules:
        if date_in_range(date, rule_s):
            price *= (1 + rule_s['modifier_pct'] / 100)

    # 5. Guardrails obligatorios
    price = max(price, rule.min_price)
    price = min(price, rule.max_price)

    return round(price, 2)
```

### 7.18 PriceRecommendation

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
property_id         UUID FK→Property NOT NULL
pricing_rule_id     UUID FK→PricingRule NOT NULL
date                DATE NOT NULL
current_price       DECIMAL(10,2)
recommended_price   DECIMAL(10,2) NOT NULL
explanation         TEXT NOT NULL
confidence          DECIMAL(3,2) NOT NULL DEFAULT 1.00
status              ENUM('DRAFT','RECOMMENDED','APPROVED','APPLIED_EXTERNAL','REJECTED') NOT NULL DEFAULT 'RECOMMENDED'
created_at          TIMESTAMPTZ NOT NULL

UNIQUE(property_id, date)
```

### 7.19 OwnerApproval

```
id              UUID PK
tenant_id       UUID FK→Tenant NOT NULL
property_id     UUID FK→Property NOT NULL
related_type    ENUM('INCIDENT','MAINTENANCE_COST','OTHER') NOT NULL
related_id      UUID NOT NULL
amount          DECIMAL(10,2) NOT NULL
reason          TEXT NOT NULL
status          ENUM('PENDING','APPROVED','REJECTED','EXPIRED') NOT NULL DEFAULT 'PENDING'
requested_at    TIMESTAMPTZ NOT NULL
responded_at    TIMESTAMPTZ
responded_by    UUID FK→User
response_notes  TEXT
```

### 7.20 Review

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
property_id         UUID FK→Property NOT NULL
reservation_id      UUID FK→Reservation      -- nullable
external_id         VARCHAR(200)             -- ID en OTA
channel             ENUM('AIRBNB','BOOKING','GOOGLE','MANUAL','OTHER') NOT NULL
reviewer_name       VARCHAR(200)
rating              DECIMAL(3,1)             -- 1.0 a 5.0
content             TEXT
language            VARCHAR(5)
sentiment           ENUM('POSITIVE','NEUTRAL','NEGATIVE')
ai_summary          TEXT
recurring_issues    JSONB                    -- ["wifi", "noise", ...]
status              ENUM('NEW','DRAFTED','APPROVED','POSTED_MANUALLY','IGNORED') NOT NULL DEFAULT 'NEW'
published_at        TIMESTAMPTZ
created_at          TIMESTAMPTZ NOT NULL
updated_at          TIMESTAMPTZ NOT NULL
```

### 7.21 ReviewResponseDraft

```
id              UUID PK
review_id       UUID FK→Review NOT NULL UNIQUE
draft_content   TEXT NOT NULL
language        VARCHAR(5) NOT NULL
ai_generated    BOOLEAN NOT NULL DEFAULT TRUE
approved_by     UUID FK→User
approved_at     TIMESTAMPTZ
created_at      TIMESTAMPTZ NOT NULL
updated_at      TIMESTAMPTZ NOT NULL
```

### 7.22 OwnerStatement

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
property_id         UUID FK→Property NOT NULL
period_start        DATE NOT NULL
period_end          DATE NOT NULL
gross_revenue       DECIMAL(10,2) NOT NULL DEFAULT 0
ota_commissions     DECIMAL(10,2) NOT NULL DEFAULT 0
net_revenue         DECIMAL(10,2) NOT NULL DEFAULT 0
cleaning_costs      DECIMAL(10,2) NOT NULL DEFAULT 0
laundry_costs       DECIMAL(10,2) NOT NULL DEFAULT 0
amenities_costs     DECIMAL(10,2) NOT NULL DEFAULT 0
maintenance_costs   DECIMAL(10,2) NOT NULL DEFAULT 0
specialist_costs    DECIMAL(10,2) NOT NULL DEFAULT 0
platform_fee        DECIMAL(10,2) NOT NULL DEFAULT 0
other_costs         DECIMAL(10,2) NOT NULL DEFAULT 0
net_owner_result    DECIMAL(10,2) NOT NULL DEFAULT 0
status              ENUM('DRAFT','READY','SENT') NOT NULL DEFAULT 'DRAFT'
notes               TEXT
created_at          TIMESTAMPTZ NOT NULL
updated_at          TIMESTAMPTZ NOT NULL

UNIQUE(tenant_id, property_id, period_start, period_end)
```

### 7.23 Expense

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
property_id         UUID FK→Property NOT NULL
statement_id        UUID FK→OwnerStatement   -- nullable hasta que se consolida
incident_id         UUID FK→Incident         -- nullable
category            ENUM('CLEANING','LAUNDRY','AMENITIES','MAINTENANCE','SPECIALIST','PLATFORM_FEE','OTHER') NOT NULL
description         VARCHAR(500) NOT NULL
amount              DECIMAL(10,2) NOT NULL
currency            VARCHAR(3) NOT NULL DEFAULT 'EUR'
date                DATE NOT NULL
receipt_storage_key VARCHAR(500)             -- StorageAdapter key si hay justificante
approved_by         UUID FK→User
created_at          TIMESTAMPTZ NOT NULL
```

### 7.24 NotificationLog

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
recipient_user_id   UUID FK→User             -- nullable si es a huésped
recipient_contact   VARCHAR(255) NOT NULL    -- email, teléfono, etc.
channel             ENUM('EMAIL','WHATSAPP','PUSH','IN_APP','CONSOLE') NOT NULL
notification_type   VARCHAR(100) NOT NULL    -- ver tipos en sección 21
subject             VARCHAR(500)
body                TEXT
status              ENUM('PENDING','SENT','FAILED','SKIPPED') NOT NULL DEFAULT 'PENDING'
attempts            INTEGER NOT NULL DEFAULT 0
last_error          TEXT
sent_at             TIMESTAMPTZ
related_type        VARCHAR(100)             -- 'CleaningTask','Incident', etc.
related_id          UUID
sla_deadline_at     TIMESTAMPTZ              -- si aplica SLA, cuándo vence
sla_breached        BOOLEAN NOT NULL DEFAULT FALSE
created_at          TIMESTAMPTZ NOT NULL
updated_at          TIMESTAMPTZ NOT NULL

INDEX(tenant_id, status, sla_deadline_at)
INDEX(related_type, related_id)
```

### 7.25 AuditLog

```
id                  UUID PK
tenant_id           UUID FK→Tenant NOT NULL
actor_user_id       UUID FK→User             -- nullable para acciones de sistema
actor_ip            VARCHAR(45)
action              VARCHAR(200) NOT NULL     -- ej: 'reservation.update', 'guest.view_document'
entity_type         VARCHAR(100) NOT NULL     -- ej: 'Reservation', 'Guest'
entity_id           UUID NOT NULL
changes             JSONB                     -- {field: {old: val, new: val}}
created_at          TIMESTAMPTZ NOT NULL

INDEX(tenant_id, entity_type, entity_id)
INDEX(tenant_id, actor_user_id, created_at DESC)
```

Debe generarse AuditLog para:
- cambios en Reservation
- cambios en PropertyOperationalState
- acceso y modificación de datos de documento de Guest
- cambios en AccessRecord
- cambios en PricingRule y PriceRecommendation
- OwnerApproval (request y respuesta)
- cambios de role de User
- acciones sobre Incident

### 7.26 WebhookEvent

```
id              UUID PK
tenant_id       UUID FK→Tenant          -- nullable si no está autenticado aún
provider        VARCHAR(100) NOT NULL   -- 'octorate', 'smoobu', 'beds24', etc.
event_type      VARCHAR(200) NOT NULL
payload         JSONB NOT NULL
processed       BOOLEAN NOT NULL DEFAULT FALSE
processed_at    TIMESTAMPTZ
error           TEXT
received_at     TIMESTAMPTZ NOT NULL

INDEX(provider, processed, received_at)
```

---

## 8. Máquina de estados de la propiedad

Implementar como state machine determinista. Cada transición es explícita. Ninguna transición puede ocurrir fuera del servicio `PropertyStateMachine`.

### 8.1 Mapa de transiciones

```
VACANT_READY
  → AWAITING_CHECKIN     [cuando hay reserva confirmada para HOY y propiedad lista]
  → BLOCKED_BY_OWNER     [acción manual del owner]
  → OUT_OF_SERVICE       [acción manual manager/owner]
  → MAINTENANCE_REQUIRED [incidencia HIGH creada]

AWAITING_CHECKIN
  → OCCUPIED_ESTIMATED   [hora de check-in alcanzada]
  → MAINTENANCE_REQUIRED [incidencia HIGH]
  → CRITICAL_INCIDENT    [incidencia CRITICAL]
  → BLOCKED_BY_OWNER     [acción manual]
  → VACANT_READY         [reserva cancelada antes de check-in]

OCCUPIED_ESTIMATED
  → AWAITING_CLEANING    [hora de check-out alcanzada]
  → CRITICAL_INCIDENT    [incidencia CRITICAL]
  → MAINTENANCE_REQUIRED [incidencia HIGH durante ocupación]

AWAITING_CLEANING
  → CLEANING_SCHEDULED   [limpiadora asignada]
  → CRITICAL_INCIDENT    [incidencia CRITICAL descubierta]
  → MAINTENANCE_REQUIRED [incidencia HIGH descubierta]
  → BLOCKED_BY_OWNER     [acción manual]

CLEANING_SCHEDULED
  → CLEANING_IN_PROGRESS [limpiadora marca inicio]
  → AWAITING_CLEANING    [limpiadora rechaza o no responde → reasignar]
  → CRITICAL_INCIDENT    [incidencia CRITICAL]

CLEANING_IN_PROGRESS
  → READY_FOR_NEXT_GUEST [limpieza completada + reserva próxima ≥ 1 día]
  → AWAITING_CHECKIN     [limpieza completada + reserva hoy]
  → VACANT_READY         [limpieza completada + sin reservas]
  → MAINTENANCE_REQUIRED [incidencia HIGH reportada durante limpieza]
  → CRITICAL_INCIDENT    [incidencia CRITICAL reportada durante limpieza]

READY_FOR_NEXT_GUEST
  → AWAITING_CHECKIN     [reserva para hoy dentro de ventana de check-in]
  → MAINTENANCE_REQUIRED [nueva incidencia HIGH]
  → CRITICAL_INCIDENT    [nueva incidencia CRITICAL]
  → BLOCKED_BY_OWNER     [acción manual]

MAINTENANCE_REQUIRED
  → [estado anterior correcto] [incidencia resuelta — calculado por contexto: reserva activa → OCCUPIED_ESTIMATED, limpieza pendiente → AWAITING_CLEANING, etc.]
  → CRITICAL_INCIDENT    [incidencia escala a CRITICAL]
  → BLOCKED_BY_OWNER     [acción manual]

CRITICAL_INCIDENT
  → MAINTENANCE_REQUIRED [incidencia crítica resuelta pero hay otras incidencias HIGH]
  → [estado contextual]  [todas las incidencias resueltas — mismo cálculo que MAINTENANCE_REQUIRED]
  → BLOCKED_BY_OWNER     [acción manual]

BLOCKED_BY_OWNER
  → [cualquier estado]   [desbloqueo manual por owner o manager]

OUT_OF_SERVICE
  → VACANT_READY         [reactivación manual por manager/owner]
```

### 8.2 Cálculo de estado contextual tras resolución de incidencia

Cuando una incidencia se resuelve y no hay más incidencias HIGH/CRITICAL activas, el estado se determina así:

```python
def compute_state_after_incident_resolved(property_id) -> PropertyOperationalState:
    current_reservation = get_active_reservation(property_id)
    pending_cleaning = get_pending_cleaning_task(property_id)

    if pending_cleaning and pending_cleaning.status in ['CREATED','ASSIGNED','ACCEPTED']:
        return AWAITING_CLEANING
    if pending_cleaning and pending_cleaning.status == 'IN_PROGRESS':
        return CLEANING_IN_PROGRESS

    if current_reservation:
        if current_reservation.check_out_date >= today:
            return OCCUPIED_ESTIMATED
        next_res = get_next_reservation(property_id)
        if next_res and next_res.check_in_date == today:
            return AWAITING_CHECKIN
        if next_res and next_res.check_in_date > today:
            return READY_FOR_NEXT_GUEST

    return VACANT_READY
```

### 8.3 Jobs programados (Celery)

| Job | Cadencia | Acción |
|-----|----------|--------|
| `check_checkin_windows` | cada 5 min | Detecta reservas que entran en ventana check-in hoy → transición `AWAITING_CHECKIN` |
| `process_checkouts` | cada 5 min | Detecta hora de checkout alcanzada → transición `AWAITING_CLEANING` + crear CleaningTask |
| `check_sla_breaches` | cada minuto | Revisa NotificationLog con sla_deadline_at expirado → escalar |
| `mark_occupied_estimated` | cada 5 min | Reserva con check_in_time ≤ now → `OCCUPIED_ESTIMATED` |
| `generate_price_recommendations` | diario 06:00 | Genera PriceRecommendation para próximos 60 días |
| `send_checkin_reminders` | cada hora | Mensajes automáticos a huésped 24h y 2h antes del check-in |

---

## 9. Dashboard del propietario

El Dashboard es la UX más crítica del producto.

Debe responder en menos de 10 segundos:

- ¿Qué pasa en cada vivienda?
- ¿Quién está dentro o cuándo llega?
- ¿Está limpia?
- ¿Hay alguna incidencia?
- ¿Quién es responsable de la próxima acción?
- ¿Cuándo es el próximo check-in/checkout?
- ¿Hay aprobaciones o gastos pendientes?

### 9.1 Pantalla principal — Property Cards

Cada card muestra:

- nombre/código de la propiedad
- estado operacional + color:
  - 🟢 verde: `VACANT_READY`, `READY_FOR_NEXT_GUEST`, `AWAITING_CHECKIN`
  - 🔵 azul: `OCCUPIED_ESTIMATED`, `CLEANING_IN_PROGRESS`
  - 🟡 amarillo: `AWAITING_CLEANING`, `CLEANING_SCHEDULED`, `MAINTENANCE_REQUIRED`
  - 🔴 rojo: `CRITICAL_INCIDENT`
  - ⚫ gris: `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE`
- reserva actual o próxima
- nombre del huésped si disponible
- check-in / check-out
- estado de limpieza
- número de incidencias abiertas
- próxima acción requerida y responsable
- tiempo del último evento

**Ejemplo card:**
```
REDES11
Estado: AWAITING_CLEANING  🟡
Última salida: ayer 11:00
Limpiadora: María — pendiente de aceptar (hace 12 min)
Próximo check-in: mañana 15:00
Incidencias abiertas: 0
Último evento: Tarea de limpieza creada hace 12 min
```

### 9.2 Página de detalle de propiedad

Debe incluir:

- timeline en tiempo real (filtrable)
- detalle de reserva actual/próxima
- datos del huésped
- estado de acceso
- estado de limpieza (si aplica)
- tickets de mantenimiento
- resumen financiero
- notas
- fotos de última limpieza
- aprobaciones pendientes

---

## 10. Timeline

El timeline es ciudadano de primera clase, no secundario.

Cada acción relevante genera un `TimelineEvent`. El timeline es inmutable: nunca se editan eventos pasados.

Filtros disponibles:
- por propiedad
- por reserva
- por tipo de evento
- por severidad
- por rango de fechas
- por actor (usuario, sistema, IA, huésped)

Las entradas deben ser legibles por humanos en el idioma del usuario autenticado.

**Ejemplo de secuencia:**
```
10:15 — Hora de checkout alcanzada para reserva Booking.com #1234.
10:16 — Tarea de limpieza creada automáticamente.
10:18 — María asignada como limpiadora.
10:22 — María aceptó la tarea de limpieza.
11:05 — María inició la limpieza.
11:52 — Foto del baño subida.
12:10 — Limpieza completada. Vivienda marcada como READY_FOR_NEXT_GUEST.
```

---

## 11. Módulo de limpieza

### Objetivo

Reemplazar la coordinación operativa de limpiezas que realizaba MAGNO.

### Flujo completo

```
Hora de checkout alcanzada (job Celery)
        ↓
CleaningTask creada automáticamente (si cleaning_required=true en reserva)
        ↓
Limpiadora asignada (automática si hay una activa, si no queda pendiente)
        ↓
Notificación a limpiadora (WhatsApp/email/mock)
        ↓
Limpiadora acepta/rechaza
  → Si rechaza: reasignar o escalar según SLA
        ↓
Limpiadora inicia tarea (→ estado CLEANING_IN_PROGRESS)
        ↓
Limpiadora completa checklist item a item
        ↓
Limpiadora sube fotos requeridas
        ↓
Limpiadora finaliza tarea
        ↓
Validación (automática con MockAIAdapter, o manual por manager)
        ↓
Tarea completada → estado de propiedad actualizado
```

### UI de limpiadora (mobile-first)

La limpiadora ve:
- propiedades asignadas
- dirección
- hora programada
- info de checkout previo
- deadline del próximo check-in
- checklist item a item (con progreso)
- botones de subir foto por categoría
- botón "reportar incidencia"
- botón "finalizar limpieza"

### Regla de validación

Una tarea NO puede marcarse como `COMPLETED` hasta que:
- todos los items `required: true` del checklist estén marcados
- todas las fotos `required: true` estén subidas
- no haya incidencias `CRITICAL` sin resolver creadas durante la limpieza

### Notificaciones con SLA

- Asignación inicial: notificar inmediatamente
- Si no hay respuesta en `TenantConfig.sla_medium_minutes` (default 240 min): escalar a manager
- Si no hay limpiadora disponible: alertar a manager inmediatamente

---

## 12. Módulo de mantenimiento

### Objetivo

Reemplazar la coordinación de mantenimiento y especialistas de MAGNO.

### Fuentes de creación de incidencias

- mensaje de huésped (IA detecta intent `MAINTENANCE_ISSUE`)
- reporte de limpiadora durante checklist
- reporte del propietario desde dashboard
- alerta de cerradura (email/Telegram de GrinPass importado manualmente o futuro automation)
- sistema (job automatizado)

### Flujo

```
Incidencia creada
        ↓
Clasificación automática (AIAdapter.classify_incident)
Severity + Category asignados automáticamente
        ↓
Si estimated_cost > TenantConfig.owner_approval_threshold_eur:
    → OwnerApproval creado
    → Notificación al propietario
    → Esperar respuesta
        ↓
Técnico asignado
        ↓
Notificación al técnico
        ↓
Técnico acepta → status ACCEPTED
        ↓
Técnico en ruta → status IN_PROGRESS
        ↓
Técnico sube fotos y coste final
        ↓
Incidencia resuelta → RESOLVED
        ↓
TimelineEvent + Expense creado
        ↓
Estado de propiedad recalculado
```

### Regla de aprobación

Default: gastos > 100 EUR requieren aprobación del propietario. Configurable en `TenantConfig.owner_approval_threshold_eur`.

Si el gasto ≤ umbral: continuar sin aprobación.

### UI del técnico (mobile-first)

El técnico ve:
- incidencias asignadas
- dirección de la propiedad
- instrucciones de contacto/acceso
- severidad y descripción
- fotos del incidente
- notas del propietario/manager
- botones: aceptar / rechazar / en ruta / finalizar
- campo ETA
- subir fotos finales
- añadir coste y materiales
- cerrar incidencia

### SLA de técnicos

- CRITICAL: notificar + 5 min → llamar si no responde
- HIGH: notificar + 15 min → escalar a manager
- MEDIUM: notificar + 240 min → recordatorio
- LOW: notificar + 480 min → recordatorio

---

## 13. Mensajería IA con huéspedes

### Objetivo

Automatizar el soporte de primer nivel a huéspedes en español e inglés.

### Canales soportados MVP

El sistema es channel-agnostic. Adapters implementados:

| Canal | Adapter MVP |
|-------|------------|
| WhatsApp | `MockWhatsAppAdapter` (imprime a consola) |
| Email | `ConsoleEmailAdapter` dev / SMTP prod |
| Airbnb mensajes | via `PMSAdapter.get_messages()` si soportado |
| Booking mensajes | via `PMSAdapter.get_messages()` si soportado |
| Transcripción telefónica | entrada manual |
| Manual (panel) | `ManualConversationAdapter` |

### Interface `AIAdapter`

```python
class AIAdapter(Protocol):
    def classify_message(
        self,
        content: str,
        language: str,
        context: ConversationContext
    ) -> MessageClassification:
        """
        Returns: intent, confidence, requires_escalation, reasoning
        """

    def generate_response(
        self,
        intent: str,
        context: ConversationContext,
        language: str,
        property_faq: dict
    ) -> GeneratedResponse:
        """
        Returns: content, confidence, suggested_actions
        """

    def classify_incident(
        self,
        title: str,
        description: str,
        property_context: dict
    ) -> IncidentClassification:
        """
        Returns: category, severity, confidence, reasoning
        """

    def validate_cleaning_photo(
        self,
        storage_key: str,
        photo_type: str
    ) -> PhotoValidationResult:
        """
        Returns: passed, issues, confidence
        """

    def summarize_incident(self, description: str, language: str) -> str: ...

    def draft_review_response(
        self,
        review_content: str,
        sentiment: str,
        language: str,
        property_name: str
    ) -> str: ...
```

MVP usa `MockAIAdapter` que devuelve respuestas predefinidas con confidence=0.80 para todos los intents conocidos.

### Intents soportados

```
CHECKIN_INSTRUCTIONS
ACCESS_PROBLEM
WIFI
PARKING
LATE_CHECKOUT
EARLY_CHECKIN
CLEANING_ISSUE
MAINTENANCE_ISSUE
NOISE
REFUND_OR_COMPENSATION
EMERGENCY
GENERAL_FAQ
REVIEW_REQUEST
UNKNOWN
```

### Flujo de procesamiento de mensaje

```
Mensaje entrante recibido
        ↓
Detección de idioma
        ↓
Clasificación de intent (AIAdapter)
        ↓
Si confidence < TenantConfig.ai_confidence_threshold (default 0.75):
    → Marcar para revisión humana
    → Escalation status = PENDING_HUMAN
        ↓
Si intent en lista de escalación inmediata:
    → Escalación inmediata
        ↓
Si no → generar respuesta (AIAdapter)
        ↓
Si ai_enabled=true y no escalado: enviar respuesta
        ↓
Crear TimelineEvent
        ↓
Si intent = MAINTENANCE_ISSUE o ACCESS_PROBLEM: crear Incident
```

### Escalación inmediata obligatoria

Escalar inmediatamente a humano si:
- intent = `EMERGENCY`
- intent = `ACCESS_PROBLEM` y quedan < 2h para check-in
- intent = `REFUND_OR_COMPENSATION`
- huésped lleva > 2 mensajes con mismo complaint sin resolución
- confidence < `TenantConfig.ai_confidence_threshold`
- mensaje contiene palabras clave de emergencia (lista configurable)

### Reglas de seguridad de la IA

La IA NUNCA debe:
- prometer reembolsos ni compensaciones
- admitir responsabilidad
- proporcionar asesoramiento legal
- revelar datos de otros huéspedes
- inventar códigos de acceso
- inventar disponibilidad ni precios
- afirmar que un técnico viene a menos que exista assignment

---

## 14. Notificaciones y SLA enforcement

### Canales MVP

| Canal | MVP |
|-------|-----|
| In-app | implementado (Notification entity + API polling/SSE) |
| Email | `ConsoleEmailAdapter` dev / SMTP prod |
| WhatsApp | `MockWhatsAppAdapter` |
| Push (futuro) | adapter placeholder |

### Interface `NotificationAdapter`

```python
class NotificationAdapter(Protocol):
    def send(
        self,
        recipient_contact: str,
        subject: str,
        body: str,
        channel: NotificationChannel
    ) -> NotificationResult: ...
```

### Tipos de notificación (notification_type)

```
CLEANING_TASK_ASSIGNED
CLEANING_NO_RESPONSE
CLEANING_COMPLETED
CLEANING_FAILED
INCIDENT_CREATED_CRITICAL
INCIDENT_CREATED_HIGH
OWNER_APPROVAL_REQUIRED
TECHNICIAN_ASSIGNED
TECHNICIAN_NO_RESPONSE
GUEST_ESCALATION
LOCK_ALERT
CHECKIN_REMINDER_24H
CHECKIN_REMINDER_2H
CHECKOUT_REMINDER
PRICE_RECOMMENDATION
SLA_BREACH
```

### SLA enforcement (Celery job `check_sla_breaches`)

Corre cada minuto. Para cada `NotificationLog` donde:
- `status = 'SENT'`
- `sla_deadline_at IS NOT NULL`
- `sla_deadline_at < now()`
- `sla_breached = FALSE`

Ejecutar acción de escalado según `notification_type`:
- `CLEANING_TASK_ASSIGNED` → crear nueva notificación al manager, marcar sla_breached=TRUE
- `TECHNICIAN_ASSIGNED` + CRITICAL → intentar `PhoneAdapter.call(technician)`
- etc.

---

## 15. Gestión de accesos

### Arquitectura

AutoHostAI NO controla GrinPass directamente. El acceso es gestionado externamente por GrinPass a través del PMS.

```
Reserva en PMS
       ↓
GrinPass importa reserva del PMS
       ↓
GrinPass crea código/acceso automáticamente
       ↓
AutoHostAI almacena estado/referencia si disponible
       ↓
AutoHostAI comunica instrucciones al huésped
```

### Interface `AccessProviderAdapter`

```python
class AccessProviderAdapter(Protocol):
    def get_access_status(self, reservation_external_id: str) -> AccessStatusResult: ...
    def create_manual_access(self, reservation_id: UUID, code: str, notes: str) -> AccessRecord: ...
    def mark_external_managed(self, reservation_id: UUID, notes: str) -> AccessRecord: ...
```

Implementaciones MVP:
- `ManualAccessAdapter`: operador introduce código manualmente
- `MockAccessAdapter`: genera código demo `****23`

### Módulo de acceso MVP

Por cada reserva confirmada, crear `AccessRecord` con status `PENDING`.

Al registrar manualmente el código: status `MANUAL_ADDED`.
Cuando se confirma que GrinPass lo gestionó: status `CREATED_EXTERNAL`.
Al confirmar que el huésped lo recibió: status `DELIVERED`.

Timeline events: `ACCESS_CODE_PENDING` → `ACCESS_CODE_CREATED_EXTERNAL` o `ACCESS_CODE_MANUAL_ADDED` → `ACCESS_CODE_DELIVERED`.

### Nota sobre apertura de puerta

PIN-based openings no producen eventos fiables. No construir lógica requerida sobre door-opening events.

Soporte futuro de sensor: `DoorSensorAdapter` + evento opcional `DOOR_OPENED_SENSOR` deshabilitado por defecto.

---

## 16. Integración con PMS / Channel Manager

### Interface `PMSAdapter`

```python
class PMSAdapter(Protocol):
    def list_reservations(self, since: datetime, property_id: str | None = None) -> list[ReservationDTO]: ...
    def get_reservation(self, external_id: str) -> ReservationDTO: ...
    def list_properties(self) -> list[PropertyDTO]: ...
    def update_price(self, property_id: str, date: date, price: Decimal) -> None: ...
    def block_dates(self, property_id: str, start: date, end: date, reason: str) -> None: ...
    def get_availability(self, property_id: str, start: date, end: date) -> AvailabilityDTO: ...
    def get_messages(self, since: datetime) -> list[MessageDTO]: ...  # si soportado
    def send_message(self, external_reservation_id: str, content: str) -> None: ...  # si soportado
```

### DTOs

```python
@dataclass
class ReservationDTO:
    external_id: str
    external_channel_id: str | None
    channel: str
    property_external_id: str
    guest_name: str
    guest_email: str | None
    guest_phone: str | None
    check_in_date: date
    check_out_date: date
    check_in_time: time | None
    check_out_time: time | None
    adults: int
    children: int
    gross_amount: Decimal | None
    ota_commission: Decimal | None
    currency: str
    status: str
    special_requests: str | None
    raw_payload: dict  # payload original sin procesar
```

### Implementaciones MVP

- `MockPMSAdapter`: devuelve reservas predefinidas del seed data
- Endpoint `/api/v1/integrations/pms/import-csv`: importación manual por CSV

### Webhook handling

Endpoint: `POST /api/v1/webhooks/{provider}`

- Valida firma HMAC si el provider lo soporta (ASSUMPTION: verificar por provider)
- Guarda `WebhookEvent` con `processed=FALSE`
- Job Celery `process_webhook_events` lo procesa asincrónicamente
- Si falla: reintenta hasta 3 veces con backoff exponencial

---

## 17. SES.Hospedajes / Registro legal de huéspedes

### Contexto

España requiere comunicación de datos de huéspedes a las fuerzas y cuerpos de seguridad para alojamiento turístico. AutoHostAI debe soportar este flujo operativamente.

### Alcance MVP

NO implementar submission oficial a SES.Hospedajes sin credenciales y proceso legal. Implementar la capa operativa completa para que cuando se tengan credenciales, solo haya que conectar el adapter real.

### Interface `SESHospedajesAdapter`

```python
class SESHospedajesAdapter(Protocol):
    def submit_guest(self, reservation_id: UUID, guest: Guest) -> SubmissionResult: ...
    def get_submission_status(self, external_id: str) -> SubmissionStatus: ...
```

MVP usa `MockSESHospedajesAdapter` que simula submission exitosa.

### Flujo operativo

1. Al confirmar reserva: `legal_registration_status = PENDING_GUEST_DATA`
2. Sistema solicita datos de documento al huésped (web token o manual)
3. Al recibir todos los datos requeridos: `legal_registration_status = READY_TO_SUBMIT`
4. Manager/manager puede hacer submit manual o automático: `SUBMITTED`
5. Si falla: `FAILED` + alerta

### Datos mínimos requeridos para submission

- `full_name`
- `nationality`
- `date_of_birth`
- `document_type`
- `document_number`
- `document_expiry_date`
- `check_in_date`
- `check_out_date`

### Protección de datos

- `document_number` cifrado en reposo (Fernet)
- Acceso auditado via `AuditLog`
- Solo roles `SUPER_ADMIN`, `TENANT_OWNER`, `PROPERTY_MANAGER` pueden ver documento completo
- En listas: mostrar siempre `document_status`, nunca el número

---

## 18. Gestión de reseñas

### Objetivo

Reemplazar la gestión de reviews que hacía MAGNO.

### Flujo

1. Importar o añadir review manualmente
2. IA analiza sentimiento y genera resumen (AIAdapter)
3. IA identifica problemas recurrentes
4. IA genera borrador de respuesta
5. Manager/owner revisa y aprueba
6. Manager postea manualmente en OTA (o via PMS si API lo soporta)

No implementar posting automático en OTAs en MVP.

---

## 19. Pricing / Revenue Management v1

Ver entidades en sección 7.17-7.18 y fórmula en sección 7.17.

**Principio:** pricing determinista basado en reglas. La IA puede explicar recomendaciones pero NO es la fuente de cálculo de precios.

### Modos de operación

- **Modo 1 (MVP):** recomendación únicamente. Manager/owner aprueba manualmente y actualiza en OTA.
- **Modo 2 (futuro):** aprobación automática + push via `PMSAdapter.update_price()`.
- **Modo 3 (futuro):** completamente automático con guardrails.

### Guardrails obligatorios (siempre)

- nunca por debajo de `min_price`
- nunca por encima de `max_price`
- cambio diario máximo ≤ `max_daily_change_pct` (default 20%)
- loggear toda recomendación y actualización en `TimelineEvent`

### Fuente de holidays locales

MVP: lista de festivos nacionales España hardcodeada para años 2025-2027.  
ASSUMPTION: festivos locales de municipio específico deben añadirse manualmente como `event_rules`.

---

## 20. Reporting financiero y liquidaciones

Ver entidades en sección 7.22-7.23.

### Objetivo

Reemplazar el reporting mensual de MAGNO al propietario.

### Outputs MVP

- Statement mensual por propiedad (PDF exportable)
- Export CSV de expenses
- Resumen visual mensual en dashboard
- Desglose financiero por reserva

No se generan facturas fiscales oficiales en MVP.

---

## 21. Notificaciones — ver sección 14

---

## 22. Auditoría y seguridad

### Requisitos de auditoría

Ver entidad `AuditLog` en sección 7.25.

Campos auditados automáticamente: cambios en Reservation, cambios de estado de propiedad, acceso a datos de Guest, cambios en AccessRecord, PricingRule, PriceRecommendation, OwnerApproval, Incident, roles de User.

### Requisitos de seguridad

- **Tenant isolation**: toda query debe incluir `WHERE tenant_id = :tenant_id`. Tests automáticos verifican que no se puede acceder a datos de otro tenant.
- **RBAC** enforced en backend (FastAPI dependencies), no solo en frontend.
- **Cifrado en reposo**: `wifi_password`, `document_number` y `access_code` con Fernet (clave en env var `ENCRYPTION_KEY`).
- **Masked fields**: códigos de acceso siempre `****XX`. Número de documento: nunca en listados.
- **Signed URLs**: fotos nunca expuestas directamente. Siempre via `StorageAdapter.get_signed_url(key, expires_in=3600)`.
- **File upload**: validar MIME type, tamaño máximo configurable (default 10MB por foto), escaneo básico de contenido.
- **Auth endpoints**: rate limiting (10 intentos/min por IP). Bloqueo tras 10 intentos fallidos.
- **Secrets**: cero secretos en repo. Todo en variables de entorno. `.env.example` con nombres pero sin valores.
- **HTTPS**: obligatorio en producción. En dev puede ser HTTP.

---

## 23. API REST

Implementar REST API con OpenAPI (Swagger) auto-generado por FastAPI.

### Convenciones

- Versión: `/api/v1/`
- Formato: JSON
- Paginación: `?page=1&per_page=20` con respuesta `{data: [], total, page, per_page, total_pages}`
- Fechas: ISO 8601 con timezone UTC
- Errores: `{error: {code: "VALIDATION_ERROR", message: "...", details: {}}}`
- Auth: `Authorization: Bearer {jwt_access_token}`

### Grupos de endpoints

```
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout

GET    /api/v1/tenants/{id}
PATCH  /api/v1/tenants/{id}

GET    /api/v1/users
POST   /api/v1/users
GET    /api/v1/users/{id}
PATCH  /api/v1/users/{id}
DELETE /api/v1/users/{id}

GET    /api/v1/properties
POST   /api/v1/properties
GET    /api/v1/properties/{id}
PATCH  /api/v1/properties/{id}
GET    /api/v1/properties/{id}/state
GET    /api/v1/properties/{id}/dashboard   -- card data completa

GET    /api/v1/reservations
POST   /api/v1/reservations
GET    /api/v1/reservations/{id}
PATCH  /api/v1/reservations/{id}
DELETE /api/v1/reservations/{id}

GET    /api/v1/timeline
GET    /api/v1/timeline/{property_id}

GET    /api/v1/cleaning-tasks
POST   /api/v1/cleaning-tasks
GET    /api/v1/cleaning-tasks/{id}
PATCH  /api/v1/cleaning-tasks/{id}
POST   /api/v1/cleaning-tasks/{id}/accept
POST   /api/v1/cleaning-tasks/{id}/reject
POST   /api/v1/cleaning-tasks/{id}/start
POST   /api/v1/cleaning-tasks/{id}/complete
GET    /api/v1/cleaning-tasks/{id}/checklist
POST   /api/v1/cleaning-tasks/{id}/checklist/{item_id}/complete
POST   /api/v1/cleaning-tasks/{id}/photos
GET    /api/v1/cleaning-tasks/{id}/photos

GET    /api/v1/incidents
POST   /api/v1/incidents
GET    /api/v1/incidents/{id}
PATCH  /api/v1/incidents/{id}
POST   /api/v1/incidents/{id}/assign
POST   /api/v1/incidents/{id}/resolve
POST   /api/v1/incidents/{id}/cancel

GET    /api/v1/conversations
POST   /api/v1/conversations
GET    /api/v1/conversations/{id}
GET    /api/v1/conversations/{id}/messages
POST   /api/v1/conversations/{id}/messages
POST   /api/v1/conversations/{id}/escalate
POST   /api/v1/conversations/{id}/resolve

GET    /api/v1/access-records
POST   /api/v1/access-records
GET    /api/v1/access-records/{id}
PATCH  /api/v1/access-records/{id}

GET    /api/v1/pricing-rules
POST   /api/v1/pricing-rules
GET    /api/v1/pricing-rules/{id}
PATCH  /api/v1/pricing-rules/{id}

GET    /api/v1/price-recommendations
POST   /api/v1/price-recommendations/generate
PATCH  /api/v1/price-recommendations/{id}

GET    /api/v1/owner-approvals
GET    /api/v1/owner-approvals/{id}
POST   /api/v1/owner-approvals/{id}/approve
POST   /api/v1/owner-approvals/{id}/reject

GET    /api/v1/statements
POST   /api/v1/statements/generate
GET    /api/v1/statements/{id}
GET    /api/v1/statements/{id}/export-csv

GET    /api/v1/reviews
POST   /api/v1/reviews
GET    /api/v1/reviews/{id}
POST   /api/v1/reviews/{id}/draft-response
POST   /api/v1/reviews/{id}/approve-response

GET    /api/v1/notifications
PATCH  /api/v1/notifications/{id}/read

GET    /api/v1/integrations/pms/status
POST   /api/v1/integrations/pms/sync
POST   /api/v1/integrations/pms/import-csv

POST   /api/v1/webhooks/{provider}         -- recibe webhooks externos

# Guest token endpoints (sin auth JWT, con token de un solo uso)
GET    /api/v1/guest/checkin/{token}
POST   /api/v1/guest/checkin/{token}
POST   /api/v1/guest/incident/{token}
GET    /api/v1/guest/info/{token}
```

---

## 24. Frontend — páginas

### Auth (público)

- `/login` — login
- `/forgot-password` — recuperación de contraseña (opcional MVP)

### App propietario/manager

- `/dashboard` — property cards
- `/properties` — lista de propiedades
- `/properties/[id]` — detalle: timeline + reserva + acceso + limpieza + incidencias + financiero
- `/timeline` — timeline global
- `/reservations` — lista y detalle de reservas
- `/cleaning` — lista de tareas de limpieza
- `/incidents` — lista de incidencias
- `/conversations` — bandeja de mensajes
- `/pricing` — reglas y recomendaciones
- `/statements` — statements y exports
- `/reviews` — gestión de reseñas
- `/approvals` — aprobaciones pendientes
- `/settings` — configuración de tenant y cuenta
- `/settings/integrations` — estado de integraciones

### App limpiadora (mobile-first, accesible desde `/cleaner`)

- `/cleaner` — mis tareas
- `/cleaner/tasks/[id]` — detalle + checklist + fotos + reportar incidencia

### App técnico (mobile-first, accesible desde `/tech`)

- `/tech` — mis incidencias
- `/tech/incidents/[id]` — detalle + actualizar estado + fotos + coste

### Portal huésped (acceso por token)

- `/guest/[token]` — instrucciones + checkin form + soporte

---

## 25. Variables de entorno

Archivo `.env.example` en la raíz del repo con todos los nombres. Nunca valores reales en repo.

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/autohost_db

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=<random 64 chars>
ENCRYPTION_KEY=<Fernet key base64>
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# AI Provider (EXTERNAL_DEPENDENCY: requiere API key del proveedor IA)
AI_PROVIDER=mock           # 'mock' | 'claude' | 'openai'
AI_API_KEY=                # solo si AI_PROVIDER != mock
AI_MODEL=                  # ej: claude-sonnet-4-6

# Storage
STORAGE_TYPE=local         # 'local' | 's3'
STORAGE_LOCAL_PATH=/app/media
STORAGE_S3_BUCKET=         # solo si STORAGE_TYPE=s3
STORAGE_S3_REGION=         # solo si STORAGE_TYPE=s3
STORAGE_S3_ACCESS_KEY=     # solo si STORAGE_TYPE=s3
STORAGE_S3_SECRET_KEY=     # solo si STORAGE_TYPE=s3

# Email (EXTERNAL_DEPENDENCY: requiere SMTP en producción)
EMAIL_PROVIDER=console     # 'console' | 'smtp'
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
EMAIL_FROM=noreply@autohost.local

# WhatsApp (EXTERNAL_DEPENDENCY)
WHATSAPP_PROVIDER=mock     # 'mock' | 'twilio' | 'meta'
WHATSAPP_API_KEY=

# PMS (EXTERNAL_DEPENDENCY)
PMS_PROVIDER=mock          # 'mock' | 'octorate' | 'smoobu' | 'beds24'
PMS_API_KEY=
PMS_API_URL=

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# App
ENVIRONMENT=development    # 'development' | 'production'
DEBUG=true
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
DEFAULT_TIMEZONE=Europe/Madrid
```

---

## 26. Orden de desarrollo

Claude debe seguir este orden. **No empezar con UI.**

1. Estructura del repositorio (monorepo: `/backend`, `/frontend`, `/docker`)
2. Modelos de dominio en Python (entidades + enums del dominio)
3. Esquema de base de datos + migraciones Alembic (todas las entidades de sección 7)
4. Sistema de auth (JWT + RBAC + middleware)
5. Tenant isolation (middleware que scopa todas las queries)
6. Sistema de timeline / events (servicio central `TimelineService`)
7. Máquina de estados de la propiedad (`PropertyStateMachine`)
8. Jobs Celery (scheduler, SLA enforcement)
9. Módulo de reservas (CRUD + `MockPMSAdapter` + import CSV + webhook handler)
10. Módulo de limpieza (CleaningTask + checklist + fotos + StorageAdapter)
11. Módulo de mantenimiento (Incident + OwnerApproval + Technician flow)
12. Módulo de mensajería (Conversation + Message + `MockAIAdapter`)
13. Módulo de acceso (AccessRecord + `ManualAccessAdapter`)
14. Sistema de notificaciones + SLA (`NotificationAdapter` + `NotificationLog`)
15. Dashboard API (`/properties/{id}/dashboard` endpoint aggregado)
16. Frontend layout, auth y dashboard (property cards)
17. Frontend property detail + timeline
18. Frontend módulo limpieza (manager view)
19. Frontend app limpiadora (mobile-first)
20. Frontend app técnico (mobile-first)
21. Frontend conversaciones
22. Pricing v1 (reglas + recomendaciones)
23. Statements y financiero
24. Reviews module
25. Settings + integraciones
26. Seed data completo (ver sección 27)
27. Tests (pytest unit + integration + Playwright E2E)
28. Docker Compose + README de arranque

---

## 27. Seed data

### Tenant

```
name: "Adamar Inmuebles"
billing_email: "adamar.inmuebles@gmail.com"
country: "ES"
timezone: "Europe/Madrid"
default_language: "es"
```

### TenantConfig (defaults)

```
owner_approval_threshold_eur: 100.00
ai_confidence_threshold: 0.75
sla_critical_minutes: 5
sla_high_minutes: 15
sla_medium_minutes: 240
sla_low_minutes: 480
```

### Properties

```
Property 1:
  name: "Redes 11"
  internal_code: "REDES11"
  address_line1: "Calle de las Redes, 11"
  city: "Madrid"
  province: "Madrid"
  max_guests: 4
  bedrooms: 2
  bathrooms: 1
  default_check_in_time: "15:00"
  default_check_out_time: "11:00"

Property 2:
  name: "Pajaritos 8"
  internal_code: "PAJARITOS8"
  address_line1: "Calle Pajaritos, 8"
  city: "Madrid"
  province: "Madrid"
  max_guests: 2
  bedrooms: 1
  bathrooms: 1
  default_check_in_time: "15:00"
  default_check_out_time: "11:00"
```

### Users

```
owner@adamar.test — TENANT_OWNER — password: demo1234
manager@adamar.test — PROPERTY_MANAGER — password: demo1234
cleaner@adamar.test — CLEANER — password: demo1234
tech@adamar.test — TECHNICIAN — password: demo1234
```

### Reservations (seed para REDES11)

```
Reserva 1 (activa ahora):
  channel: AIRBNB
  guest: "John Smith" <john.smith@example.com>
  check_in: hoy - 2 días
  check_out: hoy + 1 día
  status: CHECKED_IN_ESTIMATED
  adults: 2
  gross_amount: 350.00
  ota_commission: 52.50
  net_amount: 297.50

Reserva 2 (próxima):
  channel: BOOKING
  guest: "María García" <maria.garcia@example.com>
  check_in: hoy + 3 días
  check_out: hoy + 7 días
  status: CONFIRMED
  adults: 3

Reserva 3 (pasada, limpieza completada):
  channel: DIRECT
  guest: "Pedro López"
  check_in: hoy - 10 días
  check_out: hoy - 7 días
  status: COMPLETED
```

### Incidents (seed)

```
Incident 1 (REDES11):
  category: WIFI
  severity: LOW
  status: OPEN
  title: "WiFi va lento"
  description: "El huésped reporta que el WiFi va muy lento en la habitación"
  source: GUEST

Incident 2 (REDES11):
  category: ACCESS
  severity: HIGH
  status: ASSIGNED
  title: "Problema con código de acceso"
  description: "El código de acceso no funciona. Huésped bloqueado en la entrada."
  source: GUEST
  assigned_technician_id: tech@adamar.test

Incident 3 (PAJARITOS8):
  category: APPLIANCE
  severity: MEDIUM
  status: OPEN
  title: "Lavadora hace ruido extraño"
  description: "La limpiadora reporta que la lavadora hace un ruido metálico al centrifugar"
  source: CLEANER
```

### CleaningChecklistTemplate (una por tenant, para ambas propiedades)

Usar el template por defecto definido en sección 7.10.

---

## 28. Definition of Done del MVP

El MVP está terminado cuando:

1. El propietario puede hacer login.
2. El propietario ve property cards con estado operacional en tiempo real y código de colores.
3. El propietario puede abrir el detalle de una propiedad y ver el timeline.
4. Las reservas pueden crearse manualmente y/o importarse via MockPMSAdapter o CSV.
5. El checkout automáticamente crea una CleaningTask (job Celery).
6. La limpiadora puede aceptar la tarea, completar el checklist y subir fotos.
7. Completar la limpieza cambia el estado de la propiedad correctamente según contexto.
8. Huésped/limpiadora/propietario puede crear una incidencia.
9. MockAIAdapter clasifica automáticamente severity y category de la incidencia.
10. El técnico puede aceptar y resolver una incidencia.
11. Incidencias CRITICAL ponen la vivienda en rojo.
12. OwnerApproval se genera para gastos > umbral configurado.
13. El estado del acceso puede rastrearse manualmente (AccessRecord).
14. Existen conversaciones con respuesta automática de MockAIAdapter.
15. Las recomendaciones de precio se generan por reglas configuradas.
16. El statement mensual puede generarse y exportarse a CSV.
17. Todas las acciones relevantes generan TimelineEvents.
18. El tenant isolation está implementado y testeado.
19. Los tests cubren todas las transiciones de la state machine.
20. La app corre localmente con un solo `docker compose up`.

---

## 29. Non-goals explícitos del MVP

**NO construir en MVP:**

- PMS propio
- Channel Manager propio
- Integración directa con API de Airbnb
- Integración directa con API de Booking.com
- Integración directa con API de GrinPass
- Scraping de GrinPass u otras plataformas
- Submission oficial a SES.Hospedajes sin credenciales y proceso legal
- App nativa iOS/Android
- ML/AI para pricing (solo reglas deterministas)
- Decisiones automáticas de reembolso
- Facturación fiscal oficial
- Lógica de apertura de puerta basada en PIN
- Integración OAuth con OTAs
- Sistema de inventario de amenities

---

## 30. Instrucción final para Claude

Construir el sistema como MVP de calidad producción, no como prototipo visual.

Donde un proveedor sea desconocido: crear el adapter y un mock funcional.

Donde no haya datos reales: usar el seed data de sección 27.

Donde una integración no pueda implementarse sin credenciales: documentar la firma exacta del método y el payload esperado con `EXTERNAL_DEPENDENCY` en comentario.

Prioridad de entrega:

1. visibilidad del estado operacional (state machine + dashboard)
2. sistema de timeline
3. flujo de limpieza completo
4. flujo de mantenimiento completo
5. mensajería/escalado
6. adapters PMS/acceso
7. pricing
8. statements

El producto debe ser usable por la propietaria en mobile para entender en menos de 10 segundos qué está pasando en cada vivienda.

---

## Changelog v4 → v5

| # | Tipo | Descripción |
|---|------|-------------|
| 1 | FIX | Eliminado estado `OCCUPIED` de sección 3.1; unificado a `OCCUPIED_ESTIMATED` en todo el documento |
| 2 | ADD | Añadidos estados `VACANT_READY` y `AWAITING_CHECKIN` a la tabla de estados de sección 3.1 |
| 3 | FIX | State machine de sección 8 completada con todas las transiciones faltantes: `VACANT_READY`, `AWAITING_CHECKIN`, `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE` |
| 4 | ADD | Algoritmo `compute_state_after_incident_resolved` explicitado |
| 5 | ADD | Jobs Celery con cadencia y descripción completa |
| 6 | ADD | Entidad `TenantConfig` con todos los umbrales configurables |
| 7 | ADD | Entidad `PropertyStateTransition` para histórico de cambios de estado |
| 8 | ADD | Entidad `CleaningChecklistCompletion` para almacenar respuestas al checklist |
| 9 | ADD | Entidad `AuditLog` requerida por sección de seguridad |
| 10 | ADD | Entidad `NotificationLog` con campos SLA |
| 11 | ADD | Entidad `WebhookEvent` para handling de webhooks externos |
| 12 | FIX | Entidad `Guest` ampliada con `nationality`, `date_of_birth`, `document_type`, `document_number_encrypted`, `document_expiry_date`, `legal_registration_status` |
| 13 | FIX | Entidad `Property` añadido campo `pms_external_id` |
| 14 | FIX | Entidad `Reservation` — `access_status` con enum completo definido |
| 15 | FIX | Entidad `AccessRecord` — enums `provider`, `status`, `created_mode` definidos |
| 16 | FIX | Entidad `CleaningTask` — `validation_status` con enum definido |
| 17 | FIX | Entidades `OwnerStatement`, `Expense` — campos completos |
| 18 | FIX | Entidades `Review`, `ReviewResponseDraft` — campos completos |
| 19 | FIX | `PricingRule` — schemas JSON de todos los campos JSONB documentados con ejemplos |
| 20 | ADD | Fórmula explícita de cálculo de precio recomendado en Python |
| 21 | FIX | Canal `Conversation` — enum unificado (`AIRBNB_MSG`, `BOOKING_MSG` en lugar de genérico) |
| 22 | ADD | Interface `AIAdapter` completa con todos los métodos |
| 23 | ADD | `MockAIAdapter` especificado con comportamiento concreto |
| 24 | ADD | Umbral de confianza IA definido: `0.75` (configurable en TenantConfig) |
| 25 | ADD | Interface `StorageAdapter` — estrategia local dev / S3 prod |
| 26 | ADD | Sección de variables de entorno completa (sección 25) |
| 27 | ADD | Mecanismo de SLA enforcement via Celery job `check_sla_breaches` |
| 28 | FIX | Sección GrinPass/acceso consolidada (eliminada redundancia entre secciones 5.5 y 15 de v4) |
| 29 | ADD | Webhook handling completo (WebhookEvent entity + endpoint + procesamiento async) |
| 30 | FIX | Seed data "PAJARITOS8" confirmado como nombre fijo |
| 31 | ADD | i18n strategy explicitada (react-i18next, EN en backend, ES/EN en frontend) |
| 32 | ADD | Convenciones de API (paginación, errores, fechas) |
| 33 | ADD | Colores del dashboard mapeados a estados operacionales |
| 34 | FIX | Distinción `READY_FOR_NEXT_GUEST` vs `AWAITING_CHECKIN` clarificada |
