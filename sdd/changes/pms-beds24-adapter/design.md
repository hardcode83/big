# Design: pms-beds24-adapter

## Context

`pms-provider-resolution` dejó el hueco con la forma exacta que hay que rellenar. `SqlAlchemyPMSAdapterFactory._build` (`app/integrations/infrastructure/pms_factory.py:130-146`) ya resuelve la credencial de cuenta de Beds24, la descifra y la registra en el `CredentialReadLog` — y entonces lanza `PmsUnavailableError("…arrives with pms-beds24-adapter")`. Este change sustituye ese `raise` por un adapter.

El molde existe y es reciente: `infrastructure/channex/{client,adapter,mapping}.py` es una implementación real del mismo puerto, con la paranoia ya pagada (paginación que se niega a truncar, `PmsUnavailableError` como única excepción hacia fuera, `repr` redactado, razones de descarte de vocabulario cerrado). El transporte de Beds24 también existe, pero fuera de `app/`: `scripts/beds24_probe.py` (1.122 líneas) tiene el canje de token, la allowlist de host y la contabilidad de coste, medidos contra la API real — es banco de medición, no código de producto, y `specs/pms-beds24-spike.md` exige que siga fuera de la imagen.

El consumidor tampoco hay que escribirlo: `SyncReservationsFromPmsUseCase` (`application/use_cases.py:80-141`) ya agrupa por proveedor, ya asume una credencial de cuenta por grupo, y sus comentarios anticipan por nombre lo que pasa «el día que `pms-beds24-adapter` aterrice».

Lo que **no** existe: ningún `beds24_*` en `app/core/config.py`, ningún fixture de reserva modificada ni cancelada (solo `tests/integrations/fixtures/beds24/bookings.json`, una reserva confirmada creada por API), y ninguna medición del filtro por fecha de modificación.

## Decisions

### D1 — Paquete `infrastructure/beds24/` con la misma partición que `channex/`

**Chosen:** `client.py` (transporte, token, créditos, sobre), `adapter.py` (el puerto, por elemento) y `mapping.py` (el vocabulario de Beds24 muere aquí). Es la partición que ya demostró aguantar los tres paneles de revisión de `channex-staging-adapter`, y repetirla hace que un lector que conozca uno conozca el otro.

Rejected: un solo módulo — el mapeo de Channex son 239 líneas y el de Beds24 tiene 73 campos de origen; reutilizar `ChannexClient` — distinta autenticación, distinto sobre, distinta paginación y distinta contabilidad, no comparten nada salvo `httpx`.

### D2 — La URL base y el host son **constantes del módulo**, no configuración

**Chosen:** `BEDS24_BASE_URL = "https://beds24.com/api/v2"` y `ALLOWED_HOSTS = {"beds24.com"}` como constantes, con la comprobación de esquema `https` y de **hostname exacto** antes de cada petición. Es la regla que `specs/pms-beds24-spike.md` fija para el banco (*"derivar la allowlist de una constante y **no** de `BEDS24_BASE_URL`: quien controle el entorno controlaría el destino"*) y aquí aplica con más fuerza, porque el secreto ya no lo pone un operador en su terminal: sale de la base de datos.

Beds24 **no tiene entorno de staging** (medido en el spike), así que la razón por la que `channex_base_url` es configurable —que el default apunte a staging— aquí no existe: una URL base configurable sería una palanca sin caso de uso.

Sí serán ajustes con default, sin secreto: `beds24_timeout_seconds`, `beds24_max_pages`, `beds24_page_limit`.

Rejected: `beds24_base_url` en `config.py` como Channex — simetría sin motivo, y una palanca que la allowlist tendría que vigilar; allowlist derivada de la URL base — es exactamente el ataque del que protege.

### D3 — `list_reservations(since)` filtra por **fecha de modificación**, y el nombre del parámetro se mide antes de escribir el mapeo

**Chosen:** el filtro es `modifiedFrom` (documentado en el wiki del proveedor junto a `modifiedTo`), que es lo que da la ventana completa de R2.1: una reserva creada hace un mes y cancelada hace un minuto tiene `modifiedTime` de hace un minuto y **entra**. Es la diferencia estructural con Channex, cuyo `/bookings` solo filtra por `arrival_date`, `departure_date` e `inserted_at` (`channex/adapter.py:8-13`).

**El nombre está documentado pero no medido, y este proyecto no diseña contra documentación de proveedor** — la lección de `channex-staging-adapter` (cuatro reglas del mapeo contradicen sus docs) y del propio spike (`x-requestcost` adivinado no casaba con nada). Así que la **primera tarea** amplía el catálogo de `scripts/beds24_probe.py` con las formas `modifiedFrom` y mide: que el parámetro existe, qué formato de fecha acepta (el spike ya midió que `arrivalFrom` exige `YYYY-MM-DD` y rechaza duraciones ISO-8601), si devuelve las canceladas sin pedirlas y cuánto cuesta. Esa medición **es también evidencia de R6**: una forma nueva es una fila nueva del JSONL.

**Plan si la medición desmiente el filtro** (no se decide ahora, se nombra): degradar a ventana por `arrival` amplia + filtrado por `modifiedTime` en el cliente cambia el perfil de coste y de volumen, así que sería material para renegociar R2.1, no para resolverlo en silencio. Queda como riesgo, abajo.

Rejected: `bookingTimeFrom` — es el análogo exacto del `inserted_at` de Channex y reproduce su limitación; filtrar en cliente sobre una ventana amplia por defecto — paga volumen y créditos por lo que el proveedor sabe filtrar.

### D4 — Un canje de token por **instancia de adapter**, perezoso y solo en memoria

**Chosen:** el adapter recibe el refresh token ya descifrado y canjea el access token de 24 h en la primera petición que lo necesite, guardándolo en el propio objeto. R1.6 («como máximo un canje por ejecución y cuenta») se cumple **por la forma que ya tiene el sync**: `_sync_one_provider` llama a `reservations_for` una vez por grupo de proveedor y usa ese adapter para todo el grupo, así que un adapter por ejecución es un canje por ejecución. No hace falta caché.

Perezoso y no en el constructor porque construir no debe hacer E/S: `_build` se llama dentro de la resolución, y un constructor que sale a la red convierte cualquier futuro camino barato en una petición.

Rejected: caché de tokens de proceso con TTL — mantiene una credencial **de cuenta** viva en memoria más allá de la ejecución que la pidió, que es exactamente la invariante que `pms_factory.py:10-13` declara y prueba («caches no adapter … would keep a decrypted credential alive past its use»); canje ansioso en el constructor — E/S en construcción, y paga el canje aunque la llamada acabe fallando antes.

### D5 — Un refresh token rotado **falla ruidosamente**; el adapter nunca escribe credenciales

**Chosen:** si el canje devuelve un `refreshToken` distinto al enviado, el adapter lanza `PmsUnavailableError` nombrando el hecho **sin el valor**, y el operador rota por el CLI (`python -m app.integrations.cli.pms_credentials rotate`). Medido: el token **no rota** al usarse, así que esta rama es defensiva.

Escribir la credencial nueva desde el adapter sería un **segundo camino de aprovisionamiento**, y `specs/pms-provider-resolution.md` declara ese CLI *"como **única** vía"* precisamente porque cualquier otra se salta el cifrado, el guard cross-tenant o la auditoría. Además obligaría a meter repositorio, sesión y `AuditLog` de rotación dentro de un objeto de `infrastructure/` que hoy no tiene ninguno.

El coste está aceptado y es la dirección segura: si Beds24 empezara a rotar, los syncs fallan hasta que alguien rota a mano — frente a la alternativa, que es un bloqueo silencioso de la cuenta a los 30 días.

Rejected: persistir la rotación desde el adapter — segunda vía de aprovisionamiento; ignorarla y seguir — el escenario de bloqueo silencioso que el spike marcó como caro.

### D6 — El veredicto se lee del **cuerpo**, también en las lecturas

**Chosen:** el cliente valida el sobre `{"success": …, "count", "pages", "data"}` de toda respuesta y trata `success: false` como fallo **aunque el HTTP sea 2xx**. Esto no es teoría de la escritura: el fixture capturado demuestra que **las lecturas traen `success` en el cuerpo** (`fixtures/beds24/bookings.json` → `payload.success`), así que el hallazgo normativo del spike («responde `201` aunque rechace») tiene consumidor real en este change aunque no haya escrituras.

Las cuatro formas medidas se reconocen explícitamente: éxito con `new`, rechazo por elemento con `errors`/`success: false` bajo HTTP `201`, petición malformada devuelta como **objeto en vez de lista**, y el sobre de lectura de arriba. Lo que no encaje en ninguna es `PmsUnavailableError`, nunca un `data` asumido.

Los mensajes de error se componen del `code`/mensaje estructurado del proveedor, **nunca del cuerpo crudo** — el precedente es `channex/client.py:_error_detail`, y la razón es que un 4xx puede devolver eco de lo enviado.

Rejected: fiarse del código HTTP — el hallazgo normativo dice literalmente lo contrario.

### D7 — Paginación por `pages.nextPageExists`, **ignorando `nextPageLink`**

**Chosen:** se pagina incrementando nuestro propio parámetro de página y se para cuando `nextPageExists` es falso, cuando una página vuelve vacía, o —tope duro— al llegar a `max_pages`, que **lanza en vez de truncar** (el argumento de `channex/client.py:92-101`: una lista corta dentro de un sync es indistinguible de «el PMS no tenía más»).

`nextPageLink` es una URL absoluta que llega **en el cuerpo de la respuesta**: seguirla es dejar que el proveedor —o cualquiera que pueda influir en esa respuesta— elija el destino de la siguiente petición, justo lo que la allowlist de D2 existe para impedir. Se ignora por diseño, no por descuido.

Rejected: seguir `nextPageLink` — destino elegido por el cuerpo de la respuesta; inferir «última página» de nuestro propio `limit` — el modo de truncado silencioso que `channex/client.py` documenta con su medición.

### D8 — Créditos: se miden y se registran; ante `429` se para, no se reintenta

**Chosen:** el cliente lee `x-request-cost` (**con guiones**, y como **decimal**: `int("1.1")` lanza y registraría un coste fraccionario como «no medido») y las cabeceras de remanente, y emite **una línea de log estructurada por petición** con endpoint, método, coste, remanente y estado — sin payload y sin secretos. Un `429` es `PmsUnavailableError` con mensaje de cuota, sin reintento: el sync no ocurrió y el CLI ya traduce eso a código 3.

Ausente ≠ gratis: un coste que no viene se registra como desconocido y **nunca como `0`**.

El presupuesto medido se **cita** y no se reformula: vive en `docs/beds24-spike.md`, que lo genera desde el registro commiteado. El módulo sí dice explícitamente que es un techo de cuota y no una cadencia recomendada —el proveedor desaconseja el tiempo real y sugiere ~6 h—, y la cadencia es de `celery-jobs`, no de aquí.

> **Corregido el 2026-08-06**: este párrafo decía «8 créditos/ciclo» mientras predicaba citar en vez de reformular, y la cifra quedó obsoleta al medir (pasó a 10 créditos / 30 s, porque el catálogo ahora incluye la consulta que el sync hace de verdad). Se quita el número en lugar de actualizarlo — era la sexta copia de un dato con una sola casa.

Rejected: pacing propio en el cliente como el del banco — la cadencia la decide el planificador, y un `sleep` dentro de un adapter compartido esconde el coste donde nadie lo mide; freno proactivo por remanente — especulativo sin una medición de cómo se comporta el remanente con varias fuentes.

### D9 — Los datos de tarjeta mueren en un **scrubber compartido**, aplicado también a Channex

**Chosen:** un módulo nuevo, `app/integrations/infrastructure/card_data.py`, con una función que recorre el payload del proveedor y **elimina la rama entera** de toda clave que case con las agujas de dato de tarjeta o de credencial de pago (`card`, `cvv`, `cvc`, `guarantee`, `token`, `expir`…), a cualquier profundidad, aplicada **antes** de construir `raw_payload` en los dos mapeos. Cubre lo medido en los dos proveedores: el objeto `guarantee` de Channex (`card_number`, `cvv`, `expiration_date`) y los `stripeToken`/`pcibookingToken` de Beds24.

Esto convierte la regla 13 de «se cumple por omisión» a «se cumple por construcción»: hoy `channex/mapping.py:97` mete el elemento entero y un test lo fija así (`test_channex_mapping.py`), y lo único que evita la fuga es que ningún consumidor lea `raw_payload`. La regla 13(b) nombra ese campo como *la trampa*, y una omisión no es una garantía.

**Denylist y no allowlist**, y es la decisión que merece la objeción: una allowlist fail-closed —la política de `scripts/anonymise.py`— destruiría el único propósito de `raw_payload`, que es enseñar **el campo inesperado** cuando un import sale raro. La contrapartida es que una aguja no prevista pasa; se mitiga con el guard de fixtures que ya exige la spec del spike (deriva sus agujas del anonimizador y lee los ficheros en disco) y con un test que pasa los payloads reales capturados por el scrubber y afirma que ninguna aguja sobrevive.

Rejected: allowlist fail-closed sobre `raw_payload` — mata su propósito; borrar `raw_payload` del DTO — pierde el único modo de distinguir un bug del proveedor de uno nuestro, y es una decisión que pertenece a quien lo persista; dejar Channex como está — la regla 13 no es por proveedor. *(Confirmado en el gate — OQ1.)*

### D10 — Una reserva `black` no es una reserva: se excluye en la consulta

**Chosen:** Beds24 usa el mismo endpoint para bloqueos de calendario (`status: black`) que para reservas. Importarlos crearía estancias fantasma con huésped inventado y movería la `PropertyStateMachine`, así que se excluyen. El *dónde* dependía de una medición.

> **RESUELTA el 2026-08-06 a favor de la rama preferida, tras medir.** Esta decisión elegía excluirlos **en la consulta**, con el descarte en el adapter como plan B *si* el proveedor no admitía un filtro de estado. Durante `/sdd:run` se enmendó a «se entrega el plan B» porque la medición estaba bloqueada por falta de credencial; llegó la credencial, se midió, y la respuesta fue mejor que cualquiera de las dos ramas previstas.
>
> **Lo que la medición encontró no era sobre bloqueos, sino sobre cancelaciones**: el listado por defecto **omite las canceladas**, así que enumerar `status` no es una optimización, es obligatorio para que R2.1 se cumpla. Y una vez que hay que enumerar, **dejar `black` fuera de esa lista sale gratis** — la exclusión en la consulta ya no cuesta una decisión, viene de regalo con el arreglo del bug.
>
> Así que ship la rama «Chosen»: `RESERVATION_STATUSES` en `beds24/adapter.py` enumera los cinco estados que son reservas y omite `black`. `is_blocked_dates` se queda en el adapter como **defensa en profundidad**, no como el mecanismo.
>
> *(Este párrafo se reescribió dos veces. La primera enmienda describía el plan B como lo entregado y sobrevivió a la medición que la invalidó — la revisión a escala de feature la marcó como DESIGN-CONFLICT. Se registra porque es el patrón, no el descuido: el mecanismo vivía en tres artefactos y solo se actualizaron dos.)*

El descarte en el adapter, cuando actúa, **emite el recuento** en el log; lo que no se hace es descartarlos en silencio.

El mapa de estados es el del spike y el de Channex: `confirmed`/`new` → `CONFIRMED`, `request`/`inquiry` → `PENDING`, `cancelled` → `CANCELLED`. Un estado desconocido se pasa **sin traducir** para que `ReservationStatus.parse_ingested` lance y el ingestor reporte la fila — la asimetría deliberada de `channex/mapping.py:127-139`: un canal desconocido cae a `OTHER` y la reserva entra, un estado desconocido no se adivina porque conduce una máquina de estados real.

Rejected: importarlos como reservas — estancias fantasma; descartarlos sin recuento — la clase de silencio que el resto del módulo persigue.

### D11 — `property_external_id` sale de `propertyId`; la ambigüedad ya falla sola

**Chosen:** el mapeo produce `property_external_id = str(propertyId)`, el análogo directo del `property_id` de Channex, y cada propiedad de AutoHostAI guarda ese valor en `pms_external_id`. Si dos propiedades del mismo grupo lo comparten, `_index_by_external_id` lanza `AmbiguousPropertyExternalIdError` — que es exactamente el caso que `use_cases.py:120-127` anticipa por escrito como *«unreachable today only because BEDS24 still fails at the adapter first, and reachable the day `pms-beds24-adapter` lands»*. No hay que construir nada: hay que confirmar que la cuenta real no cae ahí (OQ2).

Rejected: componer `propertyId:roomId` — inventa un formato que el operador no puede deducir al rellenar la columna; adivinar según el número de rooms — comportamiento que cambia solo.

### D12 — Los tests de CI no tocan la red; lo que necesita la cuenta va al banco

**Chosen:** dos planos, como en `channex-staging-adapter`. En CI, `httpx.MockTransport` alimentado por los fixtures versionados (`test_beds24_client.py`, `test_beds24_mapping.py`, `test_beds24_end_to_end.py`) — cero red, es requisito de R2.6. Contra la cuenta real, `scripts/beds24_probe.py`: la medición de D3, la verificación de la ventana completa de R2.2 (crear → modificar → cancelar y comprobar que las tres entran) y la re-medición de R6, todo produciendo artefactos commiteados (JSONL y fixtures) que **después** alimentan los tests offline para siempre.

Ese es el orden de las tareas: medir primero, mapear contra lo medido, y no al revés.

Rejected: tests de integración contra la cuenta en CI — el trial es una cuenta con cuota compartida de 100 créditos/5 min; un CI que sincronice de verdad compite con el operador y con el propio sync.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Adapter Beds24 | `app/integrations/infrastructure/beds24/{__init__,client,adapter,mapping}.py` | **Nuevos.** D1-D8, D10, D11. |
| Regla 13 | `app/integrations/infrastructure/card_data.py` | **Nuevo.** Scrubber compartido (D9). |
| Regla 13 (Channex) | `app/integrations/infrastructure/channex/mapping.py` | Pasa `element` por el scrubber antes de `raw_payload` (D9). |
| Factory | `app/integrations/infrastructure/pms_factory.py` | La rama `BEDS24` de `_build` construye el adapter en vez de lanzar `PmsUnavailableError` (R5.1). El resto —credencial, descifrado, `read_log`— ya está. |
| Config | `app/core/config.py`, `.env.example` | `beds24_timeout_seconds`, `beds24_max_pages`, `beds24_page_limit`. **Ningún secreto**: la credencial vive en `pms_credentials` (D2). |
| Banco de medición | `backend/scripts/beds24_probe.py` | Formas `modifiedFrom` en el catálogo; verificación de ventana completa sobre `provoke` (D3, D12). |
| Fixtures | `backend/tests/integrations/fixtures/beds24/*.json` | Reserva **modificada** y **cancelada** capturadas y anonimizadas; se conserva la confirmada. |
| Evidencia | `docs/beds24-request-cost.jsonl`, `docs/beds24-spike.md` | Re-ejecución que respalda las cinco filas transcritas y tabla regenerada desde el registro (R6). |
| Tests | `backend/tests/integrations/test_beds24_{client,mapping,end_to_end}.py`, `test_card_data.py`, `test_pms_factory.py`, `test_channex_mapping.py` | Nuevos y actualizados: `BEDS24` ya no lanza; el elemento de Channex ya no viaja entero. |
| Docs | `docs/beds24-adapter.md`, `docs/README.md`, `README.md` | Runbook del adapter y su alta operativa (`steering/documentation.md`). |

## Data & interfaces

- **Esquema: ninguna migración.** `properties.pms_provider`, `pms_credentials` y sus índices los creó `pms-provider-resolution`; aquí solo se leen.
- **Puertos: sin cambios.** `PMSAdapter` sigue con `list_reservations`/`get_reservation`; `PMSMessagingPort` sigue **vacío** — la mensajería es `beds24-messaging-adapter`. `messaging_for` sigue lanzando `PmsUnavailableError` para `BEDS24`, y su mensaje debe pasar a nombrar esa entrada y no ésta.
- **Config nueva**: tres ajustes sin secreto (arriba). `BEDS24_REFRESH_TOKEN` **sigue siendo solo del banco** (`scripts/`), como fija la regla 8 de `steering/security.md`; el adapter no lo lee.
- **Contrato de operación**: cada propiedad servida por Beds24 necesita `pms_provider = BEDS24`, `pms_external_id = <propertyId de Beds24>` y una credencial de cuenta guardada con `pms_credentials set`.
- **API HTTP: sin cambios.** Ningún endpoint nuevo; el consumidor sigue siendo `python -m app.integrations.cli.pms_sync <tenant>`.

## Risks & mitigations

- **`modifiedFrom` no se comporta como dice el wiki** (D3). Es el riesgo que decide si R2.1 se puede cumplir. Mitigación: se mide en la **primera tarea**, antes de escribir el mapeo, y el resultado se lleva a la sesión — degradar a filtrado en cliente cambia coste y volumen, así que sería renegociar el requisito, no un detalle de implementación.
- **El coste medido es de una cuenta vacía.** El spike lo avisa: con reservas dentro el coste por ciclo puede subir y la holgura baja. Mitigación: la re-medición de R6 corre con reservas creadas por `provoke`, así que da la primera lectura con volumen, aunque sea pequeño.
- **La cuenta de desarrollo es un trial de pago con cuota compartida.** Medir, verificar la ventana y re-medir consumen créditos de la misma ventana de 100/300 s. Mitigación: el banco ya se limita el ritmo y **se detiene** ante cuota agotada en vez de reintentar; las tareas que tocan la cuenta se agrupan para no repetir canjes.
- **El scrubber es una denylist** (D9): una aguja no prevista pasa a `raw_payload`. Mitigación: guard de fixtures sobre los ficheros en disco, test del scrubber sobre los payloads reales, y el hecho de que hoy nada persiste ni serializa `raw_payload` — pero eso último es circunstancia, no defensa, y así está escrito en la regla 13(b).
- **Dos propiedades bajo un mismo `propertyId` de Beds24** (D11): el sync fallaría entero con `AmbiguousPropertyExternalIdError`. Mitigación: OQ2 lo resuelve antes de implementar; el fallo es ruidoso y no corrompe datos.
- **Un `429` en mitad de un grupo** deja ese proveedor sin sincronizar y el resto sí. Es el comportamiento que `_sync_one_provider` ya define y `specs/celery-jobs.md` ya fijó para tenants; el código de salida 3 lo hace visible.

## Open questions

Las tres se resolvieron en el gate del design (Jose, 2026-08-06). Quedan escritas porque la alternativa descartada explica la elegida.

**OQ1 — Alcance del scrubber de la regla 13. → Denylist compartida** (D9 se confirma tal cual). Se descarta la allowlist fail-closed porque dejaría `raw_payload` ciego justo al campo inesperado que existe para enseñar, y se descarta eliminar `raw_payload` del DTO porque esa decisión pertenece a quien lo persista, no a quien lo llena. La contrapartida —una aguja no prevista pasa— se compensa con el guard de fixtures sobre los ficheros en disco y con el test del scrubber sobre los payloads reales capturados. **Es la única elección del change que se aparta de fail-closed, y queda registrada como tal para el panel de seguridad.**

**OQ2 — Montaje de las viviendas en Beds24. → Una vivienda = una *property***, con su `propertyId` en `pms_external_id`. D11 se confirma sin cambios y el runbook lo declara como contrato de operación, no como recomendación: montar los dos pisos como *rooms* de una property haría que compartieran `pms_external_id` y el sync fallaría entero. **Tiene coste asociado y es deliberado**: Beds24 factura por propiedad, así que este contrato es también la base del ~€21/mes que ADR 0006 calculó para las dos viviendas. Se descartan mapear desde `roomId` (cambia el contrato de operación para ahorrar en un montaje que no vamos a usar) y soportar ambos (una rama que solo se ejercita si alguien la monta así).

**OQ3 — Escrituras contra la cuenta de desarrollo durante `/sdd:run`. → Sí, se corre `provoke`.** Es la única vía para R2.2 y para respaldar las cinco filas de R6, y las guardas del spike siguen vigentes y son las que lo hacen aceptable: `--confirm-writes`, verificación de que la cuenta tiene exactamente una propiedad, y aborto **antes** de modificar si la creación devuelve una forma no reconocida. Las reservas de prueba se cancelan al terminar. Se descarta diferirlo porque dejaría la ventana completa sin demostrar, que es precisamente lo que separa este change de la limitación de Channex.
