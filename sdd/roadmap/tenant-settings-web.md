# tenant-settings-web

[FE] **`/settings`, hoy `RoutePlaceholder`: usuarios del tenant y configuración**. Separada de
`hardening-release` el 2026-09-04.

> Hito «MVP operable» 3 — *autoservicio del tenant* (auditoría del 2026-09-04).

**El hecho medido (2026-09-04)**: `frontend/app/(workspace)/settings/page.tsx:11` y
`settings/integrations/page.tsx:11` son `RoutePlaceholder`; ningún fichero de `frontend/features`
llama a `/api/v1/tenants/*` ni a `/api/v1/users` (fuera de un test del proxy), y
`features/shell/navigation/route-registry.ts` no tiene ruta `users`. El `TENANT_OWNER` tiene
`MANAGE_USERS` y `MANAGE_TENANT_SETTINGS` (`auth/domain/policy.py:343-383`) y ningún sitio donde
ejercerlos. El backend está completo: seis rutas en `auth/api/users_router.py` —lista (:73), alta
con contraseña temporal devuelta una vez y `Cache-Control: no-store` (:92-126), detalle (:139),
`PATCH` (:162), desactivar (:191), reset de contraseña (:220)— y `GET`/`PATCH /tenants/{id}`
(`tenants/api/router.py:47`, :60-72) con `TenantConfig` entera en `tenants/api/schemas.py:75-89`:
`owner_approval_threshold_eur`, los minutos de SLA, `auto_create_cleaning_task`,
`notification_email_enabled`, `notification_whatsapp_enabled`, idioma por defecto.

**Por qué no es cosmético**: hoy **un owner no puede dar de alta a su propia limpiadora**. Sólo
el `SUPER_ADMIN` lo hace, desde `/platform` (`features/platform/components/create-user-form.tsx`).
Para el MVP de dos viviendas eso es que Jose crea el personal de la propietaria; para cualquier
segundo tenant es un onboarding a mano. Y el umbral de aprobación, los SLA y los canales de
notificación —las tres decisiones de operación que PRD §7.2 pone en manos del owner— sólo se
tocan con `curl`.

**Alcance**: `/settings` con dos secciones. **Usuarios**: lista, alta (rol entre los cuatro
concedibles, `GRANTABLE_ROLES`), edición, desactivar, reset de contraseña con la revelación única
de la temporal — reutilizando `create-user-form.tsx` y `temporary-password-reveal.tsx` de
`features/platform`, que ya resolvieron el patrón. **Tenant**: formulario sobre `PATCH /tenants/{id}`
con los campos de `TenantConfig`. Gateado por permiso: el manager tiene sólo lectura sobre usuarios
y tenant (`policy.py:384-421`) y ve la pantalla sin controles.

**Lo que decide y no es cosmético**:

1. **`/settings/integrations` queda fuera del MVP.** La conexión al PMS por UI no existe y no
   debe existir tal cual: las credenciales son CLI (`integrations/cli/pms_credentials.py:1-17`)
   porque la regla 3(a) prohíbe serializar una credencial de proveedor por API, y `pms_provider`
   es create-only (`properties/api/schemas.py:134-144`). La ruta del sidebar se retira o se deja
   como placeholder declarado; el design decide. Lo que sí podría ir ahí algún día es la
   provisión de webhook-endpoints (`integrations/api/router.py:116-174`, sin consumidor).
2. **Cambiar el idioma por defecto del tenant** no cambia el de los usuarios existentes
   (`preferred_language` es por usuario); decirlo en la UI.
3. **Cambiar el umbral** no reevalúa aprobaciones ya generadas; decirlo.
4. **Desactivar a la única limpiadora activa** rompe la autoasignación del checkout
   (`cleaning/domain/assignment.py`); la UI avisa, no bloquea.
5. **Regla 9**: los cambios de rol ya escriben `AuditLog` (`user-management`); la pantalla no
   añade nada, pero el design lo cita para que el panel no lo pida dos veces.

**Por qué sale de `hardening-release`**: aquella entrada retenía «la pantalla de settings/
integraciones» junto a la suite E2E, docker/README y la firma del DoD. Es el mismo criterio que
sacó el seed (`seed-data-demo`, 2026-08-07) y el SMTP (`smtp-delivery-adapter`, 2026-08-28) de
esa bolsa: lo que hace falta para operar no espera al endurecimiento de release.

**Fuera de alcance**: `/settings/integrations` funcional; plantillas de checklist (candidata
`cleaning-templates-web`); segundo `SUPER_ADMIN` (`super-admin-identity` lo dejó abierto);
`saas-cross-tenant`.
