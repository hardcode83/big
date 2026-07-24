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

**Excepción para infra `dev` (change `app-deploy-dev`, 2026-07-24):** para maximizar "todo como código, sin cambios a mano", en el entorno **dev** los secrets de runtime (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) los **genera Terraform** (`random_*`) y los guarda en el OCI Vault; sus valores **viven en el `tfstate`**. Se acepta porque el bucket de state es privado + versionado + IAM mínima (`svc-terraform-dev`). Esto **relaja** el criterio previo de `infra-dev-terraform` ("el valor en claro no llega al tfstate", que sigue vigente para la clave SSH y la clave de la GitHub App, subidas out-of-band). **Ámbito: solo dev.** Para staging/prod se revisará (generación out-of-band o gestor de secretos dedicado) antes de reutilizar este patrón.
9. **AuditLog** para: Reservation, estados de propiedad, acceso/modificación de documentos de Guest, AccessRecord, PricingRule/PriceRecommendation, OwnerApproval, roles de User, Incident (PRD §7.25).
10. **Reglas de seguridad de la IA** (PRD §13): nunca prometer reembolsos/compensaciones, admitir responsabilidad, dar asesoría legal, revelar datos de otros huéspedes, inventar códigos/disponibilidad/precios, ni afirmar que un técnico va sin assignment real.

## Triggers de revisión extra

Endpoints nuevos, cambios de auth/RBAC, dependencias nuevas, manejo de documentos de huésped, exposición de storage, webhooks entrantes (validar firma HMAC cuando el provider lo soporte).
