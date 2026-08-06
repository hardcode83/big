# Proposal: pms-provider-resolution

## Why

[ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md) elige Beds24 como proveedor PMS del MVP, y sus decisiones 3 y 7 imponen dos cambios de forma **antes** de que exista un adapter real: separar la mensajería del puerto de reservas, y resolver proveedor y credenciales **por propiedad** en lugar del selector global de PRD §22. El argumento de la decisión 7 es de coste y es literal: *"retrofitearlo es caro y hacerlo desde el principio no lo es"* — si la capa de aplicación se escribe contra un adapter inyectado como singleton, resolver por propiedad más tarde obliga a tocar todos los casos de uso.

Se separa de `pms-beds24-adapter` porque aquel entry no cabía en un change (≈10 requisitos y tres relojes distintos), y porque **esta parte se puede verificar entera hoy**: ya existen dos implementaciones reales del puerto —`MockPMSAdapter` y `ChannexAdapter`— entre las que la factory tiene que elegir de verdad, sin cuenta de Beds24 y sin depender de ningún evento externo.

Y arrastra una deuda que hasta ahora era teórica: **la regla 3 de `steering/security.md` no tiene ninguna implementación**. `git grep -in fernet -- backend/` y `git grep -in cryptography -- backend/` devuelven cero. Las columnas `_encrypted` que ya existen son `Text` pelado, un diferimiento explícito de `domain-foundation-core` (`specs/domain-foundation-core.md:31`). Terraform sí provisiona la clave (`infra/environments/dev/main.tf:318-324`, `encryption_key_fernet`, guardada en OCI Vault) pero **ningún código Python la lee**. Este change es el primero que crea columnas para las que el cifrado no es diferible: ADR 0006 exige Fernet **desde la migración que las cree**, porque una credencial de proveedor robada concede **escritura** en el calendario, el pricing y la mensajería del cliente, no solo lectura de un dato.

## What changes

Después de este change, una propiedad declara con qué proveedor PMS habla y guarda sus credenciales cifradas con Fernet; una `PMSAdapterFactory` resuelve a partir de esa propiedad el puerto de reservas y, cuando el proveedor la soporta, el de mensajería, que pasa a ser un `Protocol` propio en lugar de vivir dentro de `PMSAdapter`. Existe por primera vez una primitiva de cifrado en reposo en `backend/`, consumiendo la clave que Terraform ya provisiona. Las credenciales quedan cubiertas por las tres obligaciones que ADR 0006 les añade —contrato de solo escritura, `AuditLog` de lectura y rotación, y test de aislamiento propio— y el patrón de marcado de sesión queda fijado para cualquier proceso que itere propiedades de varios tenants. El flag `--provider` de `pms_sync`, declarado stopgap por `channex-staging-adapter`, deja de ser el mecanismo de selección.

**Precisión que cambia el coste respecto a lo que el roadmap daba por hecho**: no hay ningún puerto sobrecargado que separar. `PMSAdapter` (`backend/app/integrations/domain/ports.py:26`) declara hoy **solo** `list_reservations` y `get_reservation`; las otras seis operaciones de PRD §16 —incluidas `get_messages` y `send_message`— no existen todavía, porque el módulo declara a propósito que llegan con los changes que las consumen. Esto es fijar la frontera **antes** de que los métodos aterricen, no un refactor.

## Requirements

### R1 — `PMSMessagingPort` como puerto propio

**Como** arquitecto del backend, **quiero** que la mensajería del PMS viva en un puerto separado del de reservas, **para que** dar de alta un proveedor sin mensajería no rompa la sustituibilidad de Liskov que exige `steering/backend-architecture.md:108`.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar `PMSMessagingPort` como `Protocol` independiente de `PMSAdapter`, y no SHALL declarar ninguna operación de conversación dentro de `PMSAdapter`.
2. WHEN un proveedor no soporta mensajería, THE SYSTEM SHALL permitir que su adapter satisfaga `PMSAdapter` sin satisfacer `PMSMessagingPort`, y no SHALL exigirle un método que lance `NotImplementedError`.
3. THE SYSTEM SHALL mantener `MockPMSAdapter` y `ChannexAdapter` como implementaciones válidas de `PMSAdapter` sin añadirles mensajería.
4. THE SYSTEM SHALL demostrar **con un test estructural en tiempo de ejecución** que un adapter sin mensajería es aceptado donde se requiere `PMSAdapter`, derivando la superficie del propio puerto en vez de enumerarla a mano.

   *(Reescrito tras el panel de las secciones 2-3, a petición de QA. La redacción original añadía "y que la comprobación estática de tipos pasa sin excepciones", un criterio **inalcanzable en este repositorio**: `backend/pyproject.toml` declara solo pytest, CI no ejecuta mypy ni pyright, y `sdd/project.md` lista `pyright-lsp` como LSP de editor pendiente de instalar. No es que estuviera sin cumplir: no había ninguna ejecución, manual o automática, capaz de cumplirlo. D12 ya razonaba la sustitución por un test estructural; esto alinea el requisito con la decisión en lugar de dejar un criterio que nadie podía verificar.)*

### R2 — Resolución de proveedor y credenciales por propiedad

**Como** operador multi-tenant, **quiero** que cada propiedad declare su proveedor PMS y sus credenciales, **para que** puedan convivir dos proveedores durante la ventana de migración a Channex y para que un cliente SaaS pueda llegar con el PMS que ya tiene contratado.

Criterios de aceptación:

1. THE SYSTEM SHALL persistir en `Property` el proveedor PMS y sus credenciales, en columnas que hoy no existen (`backend/app/properties/infrastructure/models.py:21` solo tiene `pms_external_id`).
2. WHEN un caso de uso necesita hablar con el PMS de una propiedad, THE SYSTEM SHALL obtener el adapter resolviéndolo desde esa propiedad mediante `PMSAdapterFactory`, y no SHALL recibir un adapter inyectado como singleton.
3. WHERE una propiedad declara un proveedor que no soporta mensajería, THE SYSTEM SHALL resolver el puerto de reservas y señalar la ausencia del de mensajería de forma explícita y comprobable por el llamante.
4. IF el proveedor declarado en una propiedad es desconocido, THEN THE SYSTEM SHALL fallar nombrando el proveedor y no SHALL degradar a `mock` en silencio.
5. THE SYSTEM SHALL conservar una selección global únicamente para el bootstrap y el modo mock, y no SHALL mantener el flag `--provider` de `pms_sync` como mecanismo de resolución para propiedades que ya declaran el suyo.

### R3 — Cifrado Fernet de las credenciales, desde la primera migración

**Como** responsable de seguridad, **quiero** que las credenciales de proveedor nazcan cifradas, **para que** no exista ninguna versión del esquema en la que una credencial que concede escritura en el sistema del cliente esté en claro.

Criterios de aceptación:

1. THE SYSTEM SHALL cifrar con Fernet toda credencial de proveedor en la **misma migración** que crea su columna, y no SHALL existir un estado intermedio del esquema en el que esa columna acepte texto plano.
2. THE SYSTEM SHALL cubrir las **tres granularidades** que ADR 0006 nombra —propiedad, cuenta y organización—, porque una credencial de cuenta comprometida concede escritura sobre todas las propiedades de esa cuenta.
3. THE SYSTEM SHALL consumir la clave que Terraform ya provisiona (`encryption_key_fernet`) leyéndola del entorno, y no SHALL introducir una segunda clave ni un segundo nombre de variable.
4. IF la clave falta, está vacía o no es una clave Fernet válida, THEN THE SYSTEM SHALL fallar rápido nombrando la variable y no SHALL imprimir su valor.
5. THE SYSTEM SHALL no incluir el valor descifrado de una credencial en ningún `repr`, log, mensaje de error o traceback, **incluida su forma escapada**.

### R4 — Solo escritura, auditoría y aislamiento propio de las credenciales

**Como** responsable de seguridad, **quiero** las tres obligaciones que ADR 0006 añade a estas columnas, **para que** un fallo de scoping o una respuesta demasiado generosa no concedan control del sistema de otro cliente.

Criterios de aceptación:

1. THE SYSTEM SHALL no serializar una credencial descifrada en ninguna respuesta de API, **ni enmascarada** (regla 3(a) de `steering/security.md`).
2. WHEN se lee o se rota una credencial de proveedor, THE SYSTEM SHALL registrar una fila de `AuditLog` con una acción del vocabulario cerrado de `backend/app/audit/domain/actions.py`, construida por `AuditLogFactory.build`, que es el único constructor legal.
3. THE SYSTEM SHALL incluir un test de aislamiento **propio de estas columnas** que demuestre que un tenant no puede leerlas ni escribirlas para otro, distinto del test genérico del módulo.
4. IF se intenta escribir una credencial para un tenant distinto del de la sesión, THEN THE SYSTEM SHALL rechazar la escritura, siguiendo el precedente de `CrossTenantWriteError` del repositorio de auditoría.

### R5 — Marcado de sesión en la resolución por propiedad

**Como** desarrollador de jobs, **quiero** un patrón fijado para iterar propiedades de varios tenants, **para que** resolver adapter por propiedad no acabe corriendo con el filtro global desactivado ni chocando con el guard que impide re-marcar.

Criterios de aceptación:

1. WHEN un proceso resuelve adapters para propiedades de más de un tenant, THE SYSTEM SHALL abrir una sesión marcada **por tenant** y no SHALL re-marcar una sesión ya marcada.
2. IF se intenta re-marcar una sesión a otro tenant, THEN THE SYSTEM SHALL fallar, conservando el comportamiento vigente de `bind_session_to_tenant` (`backend/app/core/db.py:157-161`).
3. WHERE un proceso opere con una sesión sin marcar, THE SYSTEM SHALL filtrar `tenant_id` explícitamente en toda lectura y escritura, y THE SYSTEM SHALL documentar esa decisión en el código.
4. THE SYSTEM SHALL seguir el precedente vigente de un tenant por invocación (`pms_sync`, `backend/app/integrations/cli/pms_sync.py:127`) y de una sesión marcada por tenant y por run (`backend/app/scheduler/runner.py:136`).

### R6 — Retirar el stopgap de `unmappable_rows`

**Como** mantenedor del puerto, **quiero** que las filas no mapeables viajen en el valor de retorno, **para que** el contrato del puerto deje de depender de un atributo mutable que el propio módulo declara provisional.

Criterios de aceptación:

1. THE SYSTEM SHALL reportar las filas que un adapter no pudo convertir en `ReservationDTO` en el **valor de retorno** de `list_reservations`, siguiendo la forma que ya usa `ParseResult`.
2. THE SYSTEM SHALL eliminar `unmappable_rows` del `Protocol` `PMSAdapter` y de sus dos implementaciones.
3. THE SYSTEM SHALL preservar el comportamiento observable de `pms_sync`: los mismos códigos de salida y el mismo reporte de filas descartadas.
4. THE SYSTEM SHALL no incluir en ese reporte ningún dato del payload del proveedor más allá del identificador y la clase de error, conservando la higiene que `ports.py:46-47` ya documenta.

## Out of scope

- **El `Beds24Adapter` y todo lo específico de Beds24** → `pms-beds24-adapter`, que es el primer implementador real de `PMSMessagingPort`.
- **La medición de webhooks de la ventana de corte** → `beds24-webhook-cutover-measurement` (aplazada: requiere canales OTA reales conectados).
- **El endpoint de recepción de webhooks y la regla 12** → `reservations-webhooks`.
- **Las seis operaciones restantes de PRD §16** (`update_price`, `block_dates`, `get_availability`, `list_properties`, `get_messages`, `send_message`): llegan con los changes que las consumen (`revenue`, `messaging-ai`, `pms-beds24-adapter`). Aquí se fija **dónde** vivirá cada una, no se implementa ninguna.
- **Retrofitar el cifrado de las columnas `_encrypted` que ya existen en claro** — `properties.wifi_password_encrypted` y `guests.document_number_encrypted`. Este change construye la primitiva; cerrar ese hueco es trabajo propio y merece su entrada, porque toca datos ya persistidos y necesita migración de datos, no solo de esquema.
- **`MultiFernet` con claves separadas** para desacoplar el radio de daño de PII y credenciales: ADR 0006 lo acepta como deuda del MVP y lo nombra como salida futura.
- **La capa de accesos**, aplazada a propósito en la decisión 5 de ADR 0006.
- **La corrección de la estrategia de validación con Channex** → `channex-validation-limits`.

## Affected specs

- `sdd/specs/pms-provider-resolution.md` — *(no existe aún — se creará al archivar)*: el puerto doble, la factory, y el contrato de las columnas de credencial.
- `sdd/specs/reservations.md` — modificar: la forma del puerto `PMSAdapter`, la retirada de `unmappable_rows`, y el paso de `pms_sync` de `--provider` a resolución por propiedad.
- `sdd/specs/pms-channex-staging.md` — modificar: `ChannexAdapter` pasa a resolverse por la factory, y el flag `--provider` deja de ser el mecanismo (hoy la spec lo documenta como stopgap en su lista de *Key files*).
- `sdd/specs/domain-foundation-core.md` — modificar: la línea 31 dice que el cifrado Fernet real *"es responsabilidad de un change posterior"*; tras este change la primitiva existe, y hay que precisar que `wifi_password_encrypted` y `document_number_encrypted` siguen en claro a propósito.
- `sdd/specs/auth-tenancy.md` — modificar: el patrón de marcado de sesión gana el caso de la iteración por propiedades de varios tenants (hoy documenta el filtro global y el enumerado de tenants en las líneas 175-180).

`steering/security.md` regla 3 no cambia de texto —ADR 0006 ya la amplió—, pero este change es el primero que la implementa; conviene que el design lo haga explícito.
