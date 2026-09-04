# whatsapp-dev-credentials-render

[INFRA] **que el `.env` que el CD renderiza en la VM de dev lleve las cinco `WHATSAPP_*`**, y el
procedimiento de alta en Meta escrito entero.

> Hito «MVP operable» 2 — *el huésped real* (auditoría del 2026-09-04). Va detrás de
> `human-reply-outbound-delivery`: sin aquélla, lo que se demuestra es un producto que sólo
> contesta con la IA.

**El hecho medido (2026-09-04)**: `.github/workflows/deploy-dev.yml:249-278` enumera cada clave
que escribe en el `.env` de la VM y **no hay ninguna `WHATSAPP_*`**; `docker-compose.deploy.yml:181-231`
no pasa ninguna a `backend`. Por tanto `whatsapp_provider` queda en su default `"mock"`
(`backend/app/core/config.py:308`) y `whatsapp_app_secret`/`whatsapp_webhook_verify_token` en
`None` (:325, :334). Consecuencia en el código: el handshake `GET /api/v1/webhooks/whatsapp`
compara contra `""` y responde `403` a todo (`messaging/api/whatsapp_webhook_router.py:176-185`),
y toda entrega `POST` falla la firma HMAC → `403` (:243-249). La ruta **sí** es alcanzable desde
Internet: el proxy del frontend reenvía todo `/api/` a `backend:8000`
(`frontend/app/api/[...path]/route.ts:26`, `specs/ingress-https-dev.md:49-59`), y está
allowlisted como anónima (`tests/test_route_authorization.py:84`, :89).

**Alcance**:

1. Cinco secretos en OCI Vault leídos por nombre, el patrón que `deploy-dev.yml:234-239` ya usa
   para `S3_*`: `WHATSAPP_PROVIDER` (valor `meta`), `WHATSAPP_ACCESS_TOKEN`,
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`. Sus roles
   están medidos: las dos primeras son de salida, las dos últimas de entrada
   (`config.py:568-626` hace fallar el arranque bajo `meta` si falta cualquiera).
2. Render en el `.env` de la VM y paso a `backend` en `docker-compose.deploy.yml`. IaC-first
   (`steering/infra.md`): el secreto se crea con Terraform (el valor, a mano en el Vault, como
   los de S3).
3. **El runbook de Meta entero** en `docs/whatsapp-cloud-adapter.md`, que hoy sólo cubre los
   dos últimos pasos (registro del webhook, :35-46; asociación del número al tenant, :48-84) y
   nombra el «token de usuario del sistema» una vez sin procedimiento (:22). Lo que falta, en
   orden: Business Portfolio → App de tipo *Business* con producto *WhatsApp* → **número de
   test** (gratuito, hasta 5 destinatarios en allowlist, sin verificación de empresa;
   `design.md` del change lo dio por suficiente, :555-556) → **usuario de sistema** en Business
   Settings con permisos `whatsapp_business_messaging` y `whatsapp_business_management` y token
   permanente (el del dashboard caduca a las 24 h) → `WHATSAPP_APP_SECRET` de la app → verify
   token propio → URL `https://autohostai.digitalsec.work/api/v1/webhooks/whatsapp` → suscribir
   el campo `messages` → `POST /api/v1/messaging/whatsapp-phone-number` como `TENANT_OWNER`.
   El alta en sí es **operación**, no change; este change deja escrito el procedimiento y lo
   ejecuta una vez para dejar dev funcionando.

**Lo que decide y no es cosmético**:

1. **Un secreto de app para toda la plataforma**: `docs/whatsapp-cloud-adapter.md:27-33` deja
   escrito que un `WHATSAPP_APP_SECRET` filtrado permite forjar entregas para **todos** los
   tenants y que no hay rotación automática. El design dice cómo se rota (Vault + redeploy) y
   quién.
2. **El tenant demo y el tenant dev comparten VM y número**: `whatsapp_phone_numbers` admite una
   fila por tenant y `phone_number_id` es globalmente único (`alembic/.../c25fc5f449c1`), así que
   el número de test **sólo puede estar asociado a uno de los dos**. Decidir cuál (recomendación:
   `AutoHostAI Dev`, que no se resetea cada noche) y que `demo_reset` no lo pise.
3. **Lo que seguirá sin funcionar aunque esto se cierre**, y hay que decirlo en el runbook para
   que nadie lo persiga como bug: las notificaciones **proactivas** por WhatsApp
   (`CLEANING_TASK_ASSIGNED` etc.) fallan con `OUTSIDE_SESSION_WINDOW` porque exigen plantilla
   aprobada y ningún productor pasa `template_id` (`docs/whatsapp-cloud-adapter.md:86-92`). Sólo
   funciona la conversación que abre el huésped, dentro de las 24 h.
4. **Número de producción** = verificación de empresa en Meta + un número no registrado en la
   app de WhatsApp. Fuera de alcance; el runbook lo nombra como siguiente paso.

**Fuera de alcance**: plantillas de Meta y su productor; el número de producción; UI de
configuración del proveedor (rechazada por diseño en el proposal de `whatsapp-cloud-adapter`,
:240-241); local (`WHATSAPP_PROVIDER=` vacío → `mock`, y así se queda).

**Verificación**: el handshake de Meta responde `200` con el challenge; un mensaje desde uno de
los cinco números de la allowlist crea la conversación en `/conversations` y recibe la respuesta
de la IA; la respuesta del manager llega al móvil (requiere `human-reply-outbound-delivery`).
