# Resolución de proveedor PMS y credenciales por propiedad

## Purpose

Cada propiedad declara con qué proveedor PMS habla, y sus credenciales viven cifradas en base de
datos en lugar de en el entorno. Una `PMSAdapterFactory` resuelve, a partir de la propiedad, el
puerto de reservas y —cuando el proveedor la soporta— el de mensajería.

Es la fundación que [ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) exige **antes**
de escribir el adapter real de Beds24 (decisiones 3 y 7): sin ella, un segundo proveedor obligaría a
elegir globalmente para todo el sistema, y varios tenants no podrían tener cada uno su cuenta.
Operación y runbook: [`docs/pms-credentials.md`](../../docs/pms-credentials.md).

## Requirements

### Los dos puertos

- THE SYSTEM SHALL declarar `PMSAdapter` (reservas) y `PMSMessagingPort` (mensajería) como puertos
  **separados** en el dominio, de modo que un proveedor sin API de mensajería pueda implementar el
  primero sin quedar obligado a fingir el segundo.
- WHEN se pide el puerto de mensajería de una propiedad cuyo proveedor no la soporta, THE SYSTEM
  SHALL lanzar `PMSMessagingUnsupportedError` nombrando el proveedor, y no SHALL devolver `None`.
  CI no ejecuta ningún comprobador de tipos, así que un `PMSMessagingPort | None` no lo verificaría
  nada y el fallo aparecería como `AttributeError` en tiempo de ejecución.
- THE SYSTEM SHALL ofrecer `supports_messaging(property)` como predicado **puro**: depende solo del
  proveedor, no lee credenciales y no audita nada. Preguntar por una capacidad no puede convertirse
  en un descifrado auditado.
- THE SYSTEM SHALL verificar la conformidad de los puertos por test y no por anotaciones de tipo:
  el idioma del repo es `vars(Port)` + `callable(getattr(...))`, y una anotación desnuda no la ve
  `vars()`.

### Resolución por propiedad

- THE SYSTEM SHALL almacenar en `properties.pms_provider` el proveedor de cada propiedad, como tipo
  `ENUM` nativo de Postgres con nombre explícito, nullable.
- WHEN una propiedad no declara proveedor, THE SYSTEM SHALL resolverla al proveedor por defecto
  (`MOCK`), de modo que el arranque local y la suite no dependan de configuración alguna.
- WHEN se sincroniza un tenant, THE SYSTEM SHALL agrupar sus propiedades **por proveedor** y hacer
  una llamada por proveedor distinto, no una por propiedad. La cuota de Beds24 es de 100 créditos
  por 300 s **por cuenta**, así que con una docena de propiedades una llamada por propiedad agota
  la ventana en una pasada, mientras que agrupar escala con el número de proveedores distintos
  (2-3). El coste por ciclo no se reproduce aquí: vive medido en
  `sdd/specs/pms-beds24-spike.md`.
- THE SYSTEM SHALL restringir el emparejamiento de reservas al grupo de su proveedor, porque un
  `pms_external_id` solo es único dentro de un proveedor.
- IF un proveedor del grupo falla, THEN THE SYSTEM SHALL registrarlo en el informe y continuar con
  los demás, y el comando SHALL salir con código 3 — un proveedor que no respondió no es un
  proveedor sin datos.

### Credenciales cifradas, en su propia tabla

- THE SYSTEM SHALL guardar las credenciales de proveedor en la tabla `pms_credentials`, con un
  `scope` de tres granularidades: `PROPERTY`, `ACCOUNT` y `ORGANIZATION`.
- THE SYSTEM SHALL cifrarlas con Fernet en reposo desde la primera migración, sin ningún camino que
  las persista en claro.
- THE SYSTEM SHALL exigir que `property_id` esté presente si y solo si el `scope` es `PROPERTY`,
  con una `CHECK` a nivel de esquema, y SHALL impedir con un índice único parcial una segunda
  credencial de cuenta u organización para el mismo tenant y proveedor.
- THE SYSTEM SHALL representar el secreto como un `EncryptedSecret` que **no tiene atributo del que
  leer texto plano**: serializar la entidad —el accidente que la regla 3(a) de
  `steering/security.md` prohíbe— no puede exponer una credencial.
- WHEN se construye un `EncryptedSecret` a partir de algo que no es un token Fernet, THE SYSTEM
  SHALL rechazarlo, y el repositorio SHALL traducirlo a `SecretDecryptionError`, que es el
  vocabulario que el puerto declara.
- THE SYSTEM SHALL concentrar el descifrado en **una única llamada explícita** en la factory, y no
  SHALL descifrar como efecto colateral de cargar una fila: un `TypeDecorator` que se descifra solo
  en cada `SELECT` no deja punto donde auditar y es el camino directo a la fuga por serialización.
- IF una propiedad declara un proveedor cuyas credenciales no están guardadas, THEN THE SYSTEM
  SHALL lanzar `MissingPmsCredentialError` y no SHALL caer al mock: un fallback silencioso
  informaría «created 0» y sería indistinguible de un PMS vacío.
- WHEN la propiedad declara `BEDS24` y su credencial está guardada y descifra, THE SYSTEM SHALL
  devolver el **adapter real** (`sdd/specs/pms-beds24-adapter.md`). Hasta que ese adapter existió,
  esta misma rama recorría la cadena entera —búsqueda, scope, descifrado y auditoría— y terminaba
  en `PmsUnavailableError` porque no había nada que construir; ese hueco es el que llenó
  `pms-beds24-adapter`. El error sigue vivo para un proveedor del enum sin adapter, que es lo que
  el propio enum advierte cuando dice que un miembro no es una promesa de implementación.
- THE SYSTEM SHALL componer el mensaje de ese error a partir de escalares y SHALL rechazar en
  tiempo de ejecución cualquier otro tipo, porque pasar la fila de credencial donde se espera su
  `scope` renderizaría el refresh token entero.

### Auditoría y aislamiento

- WHEN se rota una credencial, THE SYSTEM SHALL registrar su fila de `AuditLog` con el diff
  `{"changed": true}` y nunca con el valor, porque el nombre de la columna está en el denylist de
  la regla 11 y `diff()` sobre él lanza por construcción.
- WHEN una resolución automática descifra credenciales, THE SYSTEM SHALL registrarlas con la
  granularidad que fija la **entrada nombrada de la regla 9 de `steering/security.md`**, que es su
  único enunciado normativo. Esta spec la cita y no la reformula.
- THE SYSTEM SHALL recolectar las credenciales descifradas en un `CredentialReadLog` que pertenece
  al **llamante** y no a la factory, y cuyo paso es obligatorio y no opcional: expresarlo como
  argumento por defecto convertiría la obligación en una sugerencia que ningún test nota que se
  ignora. La obligatoriedad garantiza **recolección**; la **persistencia** la aporta el llamante,
  que empareja el log con un `audit` obligatorio y lo vuelca al cerrar la ejecución.
- IF se intenta escribir una credencial para un tenant distinto del de la sesión, THEN THE SYSTEM
  SHALL rechazar la escritura con `CrossTenantWriteError`.
- THE SYSTEM SHALL verificar además que la propiedad a la que se ancla una credencial pertenece al
  tenant que escribe. La FK de `property_id` nombra `properties.id` y **no lleva tenant**, así que
  sin esta comprobación una credencial del tenant A podía anclarse a una propiedad del tenant B, y
  B borrando su propio piso destruía la credencial de A por `ON DELETE CASCADE`.
- THE SYSTEM SHALL traer su propio test de aislamiento para esta tabla, porque un fallo de scoping
  aquí no filtra datos: concede escritura sobre el sistema del cliente.

### Vía de entrada de operador

- THE SYSTEM SHALL ofrecer el comando `python -m app.integrations.cli.pms_credentials` con los
  subcomandos `set`, `rotate` y `show-providers`, como **única** vía de aprovisionamiento: no hay
  endpoint de credenciales por diseño, y SQL a mano se salta el cifrado, el guard cross-tenant y la
  auditoría de golpe.
- THE SYSTEM SHALL leer el secreto de la variable de entorno `PMS_CREDENTIAL_SECRET` y no SHALL
  aceptarlo como argumento, que sobrevive en el historial del shell y es visible en `ps`.
- THE SYSTEM SHALL rechazar unas coordenadas `(proveedor, scope)` que el resolutor nunca leería —
  guardar ahí sería teatro: el comando informaría «ok» mientras cada sync sigue usando otra cosa.
- IF se pide rotar unas coordenadas donde no hay ninguna fila, THEN THE SYSTEM SHALL negarse: casi
  siempre es una errata, y crearla en silencio haría creer al operador que sustituyó una credencial
  filtrada que sigue viva en otro sitio.
- WHEN el valor almacenado no se puede descifrar, THE SYSTEM SHALL permitir igualmente `set` y
  `rotate` sobre esas coordenadas. El comando necesita la **identidad** de la fila, no su valor, y
  está a punto de sobrescribirlo; negarse dejaría sin vía auditada justo el caso de una credencial
  filtrada **y** corrupta, empujando al operador al SQL a mano que este comando existe para evitar.
- THE SYSTEM SHALL confirmar solo las coordenadas por salida estándar, nunca el secreto ni una
  forma enmascarada suya: la regla 4 concede enmascaramiento a los códigos de acceso, y la regla
  3(a) no concede nada equivalente a las credenciales de proveedor.

### Configuración

- THE SYSTEM SHALL exigir `ENCRYPTION_KEY` al arrancar, validada como base64 de 32 bytes, y SHALL
  abortar nombrando el problema si falta o está mal formada.
- THE SYSTEM SHALL construir el error de configuración **sin el valor de entrada**, y SHALL
  lanzarlo fuera del bloque `except` para que la excepción encadenada no arrastre el diccionario de
  ajustes: `raise ... from None` solo marca `__suppress_context__` y no vacía `__context__`.

## Key files

- `backend/app/integrations/domain/ports.py` — `PMSAdapter`, `PMSMessagingPort` y
  `PMSAdapterFactory`, con el conjunto de errores que declara.
- `backend/app/integrations/domain/enums.py` — `PMSProvider`, `PmsCredentialScope` y los mapas de
  soporte de mensajería y de scope por proveedor.
- `backend/app/integrations/domain/entities.py` — `PmsCredential` y `CredentialReadLog`.
- `backend/app/integrations/domain/repositories.py` — `PmsCredentialRepository`, con `get_for`
  (devuelve la credencial) e `id_at` (solo la identidad, sin descifrar).
- `backend/app/integrations/infrastructure/pms_factory.py` — la resolución y el **único** punto de
  llamada a `decrypt` en producción.
- `backend/app/integrations/infrastructure/repositories.py` — persistencia y los dos ejes de guard
  cross-tenant.
- `backend/app/integrations/application/use_cases.py` — el agrupado por proveedor y el volcado de
  las filas de auditoría en el `finally`.
- `backend/app/integrations/cli/pms_credentials.py` — la vía de entrada de operador.
- `backend/app/core/crypto.py` y `backend/app/core/encrypted_secret.py` — la primitiva Fernet y el
  tipo que impide leer texto plano.
