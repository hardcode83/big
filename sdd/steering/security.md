---
phases: [design, run]
---

# Security — AutoHostAI (PRD §22, §13, §17)

## Datos sensibles

PII de huéspedes (documento de identidad, fecha de nacimiento — requeridos por SES.Hospedajes), códigos de acceso a viviendas, contraseñas WiFi.

## Reglas duras (verificables por cambio)

1. **Tenant isolation**: toda query con `WHERE tenant_id = :tenant_id` (middleware/scoping global). Tests automáticos que demuestran que un tenant no accede a datos de otro — obligatorios en cada módulo nuevo.
2. **RBAC en backend** (FastAPI dependencies), nunca solo en frontend. Roles del PRD §6; todo endpoint nuevo declara su permiso.
3. **Cifrado en reposo con Fernet** (`ENCRYPTION_KEY`): `wifi_password`, `document_number`, códigos de acceso, y **toda credencial de proveedor externo que no viva en el entorno** — por propiedad, por cuenta o por organización (PMS/Channel Manager y equivalentes: claves por propiedad, pero también *merchant keys* de cuenta, tokens de organización y refresh tokens — [ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) decisión 7). Nunca en texto plano. **Las de cuenta u organización son las más peligrosas**, no las menos: una sola concede escritura sobre *todas* las propiedades de esa cuenta, no sobre una. **Todas las credenciales de proveedor** —de propiedad, de cuenta y de organización por igual— añaden tres obligaciones que el resto de la enumeración no tiene, porque una credencial robada da **escritura** en el sistema del cliente y no solo lectura de un dato: (a) contrato de **solo escritura** — no se serializan en ninguna respuesta de API, ni enmascaradas; (b) su lectura y su rotación se registran en `AuditLog` (regla 9); (c) su tabla lleva **test de aislamiento propio** (regla 1), porque un fallo de scoping aquí no filtra datos, concede control.

   **Única excepción a (a), y acotada**: un secreto que *nosotros* generamos para que un tercero nos autentique —el de la regla 12(a), que un operador debe copiar al panel del proveedor porque no hay API de suscripción— se puede devolver **una sola vez en el momento de generarlo y en cada rotación**, nunca en una lectura posterior. No aplica a las credenciales que el proveedor nos da: esas no se devuelven jamás. Sin esta excepción, (a) prohibiría la única vía de aprovisionamiento que ese secreto tiene.
4. **Masked fields**: códigos de acceso siempre `****XX`; número de documento jamás en listados (solo `document_status`).
5. **Fotos por signed URL** (`StorageAdapter.get_signed_url`, expiry 3600 s). Nunca exponer paths internos.
6. **Uploads**: validar MIME, tamaño máx. configurable (default 10 MB).
7. **Auth**: rate limiting 10 intentos/min/IP y bloqueo tras 10 fallos; refresh token rotation.
8. **Secrets**: cero secretos *reales* en repo — credenciales de WhatsApp/Email/Phone/SES.Hospedajes, el `PMS_API_KEY` de bootstrap/mock, la `CHANNEX_API_KEY` del adapter de validación (`specs/pms-channex-staging.md`) y el `BEDS24_REFRESH_TOKEN` del banco de medición (`specs/pms-beds24-spike.md`) — **esas tres y nada más**: las credenciales de PMS **por propiedad** viven en base de datos y las gobierna la regla 3, no esta. Ojo con la tercera: `BEDS24_REFRESH_TOKEN` es credencial **de cuenta**, así que su radio de daño es toda la cuenta y no una propiedad ([ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) decisión 7); vivir en el entorno la saca de la regla 3, no la hace menos peligrosa. La distinción no es cosmética: la regla 3 exige Fernet para *"toda credencial de proveedor externo **que no viva en el entorno**"*, y estas tres viven ahí, así que les aplica esta regla y no aquella. `CHANNEX_BASE_URL` **sí** lleva valor por defecto en `.env.example` a propósito — no es un secreto, y ese default apuntando a staging es lo que impide que un descuido escriba en una cuenta viva.: solo el nombre en `.env.example`, nunca un valor, y deben fallar rápido si faltan (`${VAR:?...}` en compose). No aplica a config puramente local sin sensibilidad real (p. ej. la contraseña del Postgres de desarrollo, que solo existe dentro de la red de docker-compose, inalcanzable desde fuera de `localhost`, sin datos reales) — esa sí puede llevar un valor por defecto funcional en `.env.example` para que `make up` arranque sin pasos manuales.

**Excepción para infra `dev`/`test` (change `app-deploy-dev`, 2026-07-24):** para maximizar "todo como código, sin cambios a mano" y poder **reutilizar el código Terraform en otro entorno sin pasos manuales**, los secrets de runtime (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) los **genera Terraform** (`random_*`) y la **clave privada de la GitHub App** se inyecta por el pipeline (UN GitHub Secret `GH_APP_PRIVATE_KEY`); todos se guardan como `oci_vault_secret` y sus valores **viven en el `tfstate`**. Se acepta porque el bucket de state es privado + versionado + IAM mínima (`svc-terraform-dev`). Esto **relaja** el criterio previo de `infra-dev-terraform` ("el valor en claro no llega al tfstate", que sigue vigente para la **clave SSH**, subida out-of-band). **Ámbito: dev/test.** Para staging/prod se revisará (gestor de secretos dedicado) antes de reutilizar este patrón.
9. **AuditLog** para: Reservation, estados de propiedad, acceso/modificación de documentos de Guest, AccessRecord, PricingRule/PriceRecommendation, OwnerApproval, roles de User, Incident (PRD §7.25).
10. **Reglas de seguridad de la IA** (PRD §13): nunca prometer reembolsos/compensaciones, admitir responsabilidad, dar asesoría legal, revelar datos de otros huéspedes, inventar códigos/disponibilidad/precios, ni afirmar que un técnico va sin assignment real.
11. **Sumideros de texto en claro** — aplicación de las reglas 3 y 4 a las columnas de texto o JSON libre que pueden acabar transportando un valor sensible sin declararlo en su nombre. Detalle abajo; **este es el único sitio donde vive el contrato**, el resto lo cita.
12. **Webhooks entrantes sin firma** — **aplica a cualquier webhook entrante sin firma, sea de la clase de proveedor que sea**: PMS/Channel Manager, registro policial (Chekin emite `PoliceRegistration.*`), cerraduras, pagos o cualquier futuro. La evidencia que la motiva viene del PMS, la regla no se limita a él. [ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) establece que **ninguno** de los once proveedores PMS/Channel Manager evaluados firma sus webhooks: no hay HMAC ni secreto compartido, solo una cabecera estática que define el receptor. El trigger de abajo ("validar firma HMAC cuando el provider lo soporte") es por tanto condicional sobre una condición hoy siempre falsa, y esta regla cubre el caso real. Un endpoint de webhook sin firma **es una escritura anónima desde internet**, y si su manejo dispara lecturas contra la API del proveedor (el patrón que el propio ADR prescribe: tratar el webhook como aviso no fiable y re-leer), quien adivine la ruta agota la cuota del proveedor y detiene el sync legítimo — un problema de integridad convertido en uno de disponibilidad. Exige las cuatro cosas: **(a)** autenticar la petición con la cabecera estática del proveedor — **valor distinto por tenant, nunca una constante global**, almacenado bajo la regla 3 (es una credencial que no vive en el entorno) y comparado en **tiempo constante**; **(b)** ruta no adivinable por tenant; **(c)** límite de tasa y tope de tamaño de cuerpo; **(d)** la re-lectura por API **desacoplada del volumen de peticiones** — encolada y coalescida, nunca una llamada saliente por webhook recibido. Nótese que (a) y (b) se sostienen mutuamente: si el secreto se filtra queda la ruta, y si la ruta se adivina queda el secreto; una sola de las dos no basta. La heredan `reservations-webhooks` (webhooks del PMS) y `access-notifications` (los de registro policial).

13. **Datos de titular de tarjeta: se descartan en la frontera, no se cifran.** Los PMS/Channel Manager entregan datos de tarjeta que nadie les pidió. Medido contra la API real en `channex-staging-adapter`: **toda** reserva de OTA llega con un objeto `guarantee` que contiene `card_number`, `card_type`, `cvv`, `cardholder_name` y `expiration_date` (`specs/pms-channex-staging.md`, `docs/channex-staging.md`).

    **Por qué necesita regla propia y no le basta ninguna de las anteriores**: la enumeración de la regla 3 cubre `wifi_password`, `document_number`, códigos de acceso y credenciales de proveedor — los datos de tarjeta **no aparecen**, ni aquí ni bajo "Datos sensibles". Y la regla 11 se acota a sí misma a *"un valor de la regla 3"*. Consecuencia concreta antes de esta regla: quien escribiera el cuerpo de un webhook de PMS en `webhook_events.payload` "en forma estructurada" **cumplía la regla 11 al pie de la letra mientras persistía un `cvv`**.

    Exige tres cosas, y la primera es la que la separa de todas las demás:

    **(a) No se cifran: se descartan.** PCI DSS prohíbe retener el CVV tras la autorización, así que "Fernet en reposo" —la respuesta de la regla 3 a todo lo demás— es la respuesta equivocada aquí. La obligación es **eliminarlos en el adapter o en el receptor de webhooks**, antes de que nada pueda persistirlos, loguearlos o reenviarlos. Un adapter que los traiga a memoria y los deje morir ahí cumple; uno que los guarde "cifrados" no.

    **(b) `raw_payload` es la trampa, y se nombra explícitamente.** El docstring de `ReservationDTO` invita a conservar la respuesta del proveedor sin tocar —y con razón: es la única forma de distinguir un bug del proveedor de uno nuestro—. Hoy ese campo vive **solo en memoria** y ninguna columna lo almacena. El día que un change lo persista, mete datos de tarjeta en la base de datos sin que ninguna otra regla se lo impida. Cualquier change que añada una columna para un payload de proveedor debe descartar `guarantee` y equivalentes antes de escribir.

    **(c) Ningún fixture versionado los contiene.** Los payloads capturados de un proveedor se anonimizan **en el momento de capturar** y con política fail-closed, incluida la posición de clave de diccionario y los escalares dentro de listas. Un guard automático que lea los ficheros en disco, no solo la función que los produce: en `channex-staging-adapter` un `expiration_date` llegó a commitearse porque el sufijo `_date` estaba en una allowlist y el guard solo cubría uno de los tres fixtures.

    La heredan `reservations-webhooks` (recibe los webhooks del PMS) y `pms-beds24-adapter` (segundo proveedor). **Debe aplicarse en su fase de diseño, no en la de implementación**: el hueco que cierra es una suposición de diseño, no un descuido de código.

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

Endpoints nuevos, cambios de auth/RBAC, dependencias nuevas, manejo de documentos de huésped, exposición de storage, webhooks entrantes (validar firma HMAC cuando el provider lo soporte — y si no la soporta, que es el caso de todos los evaluados hasta hoy, aplicar la **regla 12**), almacenamiento de credenciales de proveedor externo (regla 3).
