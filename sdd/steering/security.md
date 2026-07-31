---
phases: [design, run]
---

# Security — AutoHostAI (PRD §22, §13, §17)

## Datos sensibles

PII de huéspedes (documento de identidad, fecha de nacimiento — requeridos por SES.Hospedajes), códigos de acceso a viviendas, contraseñas WiFi.

## Reglas duras (verificables por cambio)

1. **Tenant isolation**: toda query con `WHERE tenant_id = :tenant_id` (middleware/scoping global). Tests automáticos que demuestran que un tenant no accede a datos de otro — obligatorios en cada módulo nuevo.
2. **RBAC en backend** (FastAPI dependencies), nunca solo en frontend. Roles del PRD §6; todo endpoint nuevo declara su permiso.
3. **Cifrado en reposo con Fernet** (`ENCRYPTION_KEY`): `wifi_password`, `document_number`, códigos de acceso. Nunca en texto plano.
4. **Masked fields**: códigos de acceso siempre `****XX`; número de documento jamás en listados (solo `document_status`).
5. **Fotos por signed URL** (`StorageAdapter.get_signed_url`, expiry 3600 s). Nunca exponer paths internos.
6. **Uploads**: validar MIME, tamaño máx. configurable (default 10 MB).
7. **Auth**: rate limiting 10 intentos/min/IP y bloqueo tras 10 fallos; refresh token rotation.
8. **Secrets**: cero secretos *reales* en repo — credenciales de PMS/WhatsApp/Email/Phone/SES.Hospedajes, `ENCRYPTION_KEY`, JWT signing key: solo el nombre en `.env.example`, nunca un valor, y deben fallar rápido si faltan (`${VAR:?...}` en compose). No aplica a config puramente local sin sensibilidad real (p. ej. la contraseña del Postgres de desarrollo, que solo existe dentro de la red de docker-compose, inalcanzable desde fuera de `localhost`, sin datos reales) — esa sí puede llevar un valor por defecto funcional en `.env.example` para que `make up` arranque sin pasos manuales.

**Excepción para infra `dev`/`test` (change `app-deploy-dev`, 2026-07-24):** para maximizar "todo como código, sin cambios a mano" y poder **reutilizar el código Terraform en otro entorno sin pasos manuales**, los secrets de runtime (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) los **genera Terraform** (`random_*`) y la **clave privada de la GitHub App** se inyecta por el pipeline (UN GitHub Secret `GH_APP_PRIVATE_KEY`); todos se guardan como `oci_vault_secret` y sus valores **viven en el `tfstate`**. Se acepta porque el bucket de state es privado + versionado + IAM mínima (`svc-terraform-dev`). Esto **relaja** el criterio previo de `infra-dev-terraform` ("el valor en claro no llega al tfstate", que sigue vigente para la **clave SSH**, subida out-of-band). **Ámbito: dev/test.** Para staging/prod se revisará (gestor de secretos dedicado) antes de reutilizar este patrón.
9. **AuditLog** para: Reservation, estados de propiedad, acceso/modificación de documentos de Guest, AccessRecord, PricingRule/PriceRecommendation, OwnerApproval, roles de User, Incident (PRD §7.25).
10. **Reglas de seguridad de la IA** (PRD §13): nunca prometer reembolsos/compensaciones, admitir responsabilidad, dar asesoría legal, revelar datos de otros huéspedes, inventar códigos/disponibilidad/precios, ni afirmar que un técnico va sin assignment real.
11. **Sumideros de texto en claro** — aplicación de las reglas 3 y 4 a las columnas de texto o JSON libre que pueden acabar transportando un valor sensible sin declararlo en su nombre. Detalle abajo; **este es el único sitio donde vive el contrato**, el resto lo cita.

## Sumideros de texto en claro (regla 11)

Seis columnas del esquema son texto o JSON libre por el que puede colarse un valor de la regla 3 sin que la columna lo anuncie. Ninguna la escribe nadie todavía; el contrato lo hereda el change que primero escriba en ella, con su propio test.

**La forma estructurada es el defecto: el valor no sobrevive en absoluto**, ni siquiera enmascarado — `{"changed": true}`, o se elimina la clave.

| Columna | Forma | Quién la escribirá |
|---|---|---|
| `audit_logs.changes` | estructurada | `user-management` y quien audite documentos de huésped |
| `webhook_events.payload` | estructurada | `reservations-webhooks` |
| `webhook_events.error` | estructurada | `reservations-webhooks` |
| `notification_logs.last_error` | estructurada | `access-notifications` |
| `notification_logs.subject` / `body` | **excepción** | `access-notifications` |

**La excepción es una y solo una**: `subject`/`body` admiten la forma enmascarada `****XX` de un **código de acceso**, porque renderizan un mensaje que el huésped debe recibir.

**Lo que concede no es el propósito de la columna, es la regla 4** — y la regla 4 concede exactamente eso. Que el huésped necesite ver la contraseña WiFi no la autoriza: la regla 4 no le da forma enmascarada, así que el cuerpo persiste una plantilla o una referencia, nunca la credencial renderizada. Al `document_number` la regla 4 le exige ausencia de los listados, no una máscara.

Dos redacciones anteriores de este contrato fallaron y consta por qué: la primera dijo "cualquier valor de la regla 3", autorizando un `document_number` enmascarado; la segunda usó "¿el propósito exige enseñárselo a una persona?" como criterio autónomo, que responde *sí* para el WiFi. Origen: paneles de seguridad de `domain-foundation-financial`.

## Triggers de revisión extra

Endpoints nuevos, cambios de auth/RBAC, dependencias nuevas, manejo de documentos de huésped, exposición de storage, webhooks entrantes (validar firma HMAC cuando el provider lo soporte).
