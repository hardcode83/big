# 0006 — Proveedor PMS / Channel Manager

## Estado

Aceptado — 2026-08-02. Decidido por Jose tras una investigación comparativa de once proveedores. Reordena la lista de candidatos de PRD §5.4, aplaza la conclusión de PRD §5.5 sobre la capa de accesos, sustituye el selector global de PRD §22 por resolución por propiedad, y **añade un segmento no adivinable a la ruta de webhooks de PRD §23**.

**Sobre no editar el PRD**: igual que en [ADR 0005](0005-global-email-uniqueness.md), el PRD es el documento funcional de origen y su autoría es de Marta. Ni §5.4 (lista de candidatos) ni §5.5 (conclusión sobre GrinPass) se editan; la desviación se registra aquí y se propagará a las specs vivas cuando el change que integre el proveedor real se archive.

## Contexto

PRD §5.4 fija que no se construye PMS propio y lista cuatro candidatos por prioridad: **Octorate** (preferente), **Smoobu**, **Beds24**, **Hostaway**. Esa lista nunca se validó contra la documentación técnica de los proveedores: es una priorización razonable a ojo, no un resultado de evaluación.

Tres cosas obligan a revisarla ahora.

**Primera: la mensajería es el requisito discriminante, y el PRD lo deja abierto.** `PMSAdapter.get_messages()` / `send_message()` llevan un `# si soportado` (PRD §16), y la línea 1475 repite el matiz para los mensajes de Airbnb. Pero `messaging-ai` (PRD §13) es la capability que sustituye el trabajo de MAGNO — atención al huésped 24/7 con IA y escalado humano. Un proveedor sin mensajería OTA por API no es un proveedor con una carencia menor: es un proveedor con el que el producto no funciona. Ese criterio, aplicado en serio, reordena la lista entera.

**Segunda: Booking.com ha cerrado el alta de nuevos proveedores de conectividad.** Literal en `connect.booking.com`: *"we are pausing integrations with new connectivity providers until further notice"*, sin fecha. Airbnb es invite-only y sus partner managers eligen a quién invitan. Pasar por un channel manager deja de ser un atajo para ahorrarse la homologación (PRD §29) y pasa a ser **la única puerta abierta** para dos de las tres OTAs. Eso sube el peso de acertar con el proveedor.

**Tercera: la premisa de GrinPass es más blanda de lo que dice el PRD.** §5.5 declara "conclusión arquitectónica inamovible" que el flujo pasa obligatoriamente por el PMS, apoyándose en que GrinPass "no ofrece API directa salvo proyectos muy grandes". La realidad confirmada con ellos el 2026-08-02 es distinta: **la API REST aún no es pública, pero están receptivos a construir nuevas integraciones**, y su web ya lista `REST API` e `iCal` entre sus vías. Además, ningún proveedor evaluado —ninguno— lista a GrinPass o IBINTEL en su catálogo de integraciones, así que ese puente hay que construirlo en todos los escenarios. La compatibilidad PMS↔GrinPass deja de ser criterio de selección.

El desarrollo no está bloqueado por esta decisión: PRD §5.4 prevé que el MVP funcione con `MockPMSAdapter` y/o CSV, ya entregado en el change `reservations`, y el único ítem PMS pendiente del roadmap (`reservations-webhooks`) es agnóstico al proveedor. La decisión se toma ahora para no construir el adapter real contra supuestos equivocados, no porque algo esté parado.

### Lo que arrojó la comparativa

Coste mensual, unidad = apartamento, tres canales conectados (Airbnb + Booking.com + Expedia):

| Proveedor | 2 uds | 10 uds | 50 uds | 200 uds | Mensajería API | Sandbox |
|---|---:|---:|---:|---:|:---:|:---:|
| **Beds24** | **€21** | **€55** | €225¹ | €863¹ | Airbnb, Booking, Expedia, Vrbo | Cuenta real €15,50/mes |
| WuBook | €42 | €210 | €1.050 | €4.200 | Solo Airbnb | Test account |
| Smoobu | €47 | €143 | €623¹ | €2.423¹ | Airbnb; Booking **roto** | No (trial 14 d) |
| Lodgify | ~$103² | — | — | — | Airbnb, Booking, Vrbo | No |
| Channex | $131 | $135 | **$155** | **$230** | Airbnb, Booking, Expedia³ | **Gratis, self-serve** |
| ICNEA | €150 | €150 | €370 | €590 | Ninguna | Doble credencial |
| Octorate | ~€150⁴ | ~€333⁴ | — | — | 20 endpoints | Conmutable por API |
| Avantio | €295 | €295 | ~€700 | ~€2.800 | **Ninguna** | No |
| Hostaway | n/d | ~$500 | — | — | Sí | No, sin trial |
| NextPax | $350 | $350 | $350 | $890 | Sí | Tras login |
| Rentals United | — | ~€107 | — | — | Airbnb, Booking, Vrbo | Tras contrato |

¹ Extrapolación de la fórmula pública del proveedor; ocultan precio a partir de 50 unidades y ahí se negocia.
² Tier Ultimate, el único con 0% de comisión; los inferiores llevan 1,9% sobre reservas.
³ App `channex_messages`, de pago y por propiedad.
⁴ Incluye el plan de integración de API de Octorate (€1.600/año) amortizado a mensual.

La fórmula de Beds24 es literal de su calculadora, que es JavaScript público y por tanto auditable: `€/mes = 12,90 + (uds × 2,60) + (uds × canales × 0,55)`.

**Aviso de higiene de fuentes**: la cifra de €19,90/mes para Octorate que circula ampliamente es **falsa**. Procede de `comparatifchannelmanager.fr`, una página generada por máquina cuyo HTML conserva un placeholder de plantilla sin rellenar (`[AFF_OCTORATE_EN]`), que cita la tarifa estadounidense de Stripe como si fuera de Octorate y que afirma una comisión del 1–2% por reserva contradiciendo los propios términos de Octorate (0%). Está contaminando resúmenes automáticos. Lo mismo aplica a sus fichas de Smoobu y Beds24.

## Decisión

**1. El proveedor del MVP es Beds24.** ~€21/mes para las dos viviendas, prepago, sin permanencia. Es el único de la franja económica que cubre mensajería OTA por API sobre Airbnb **y** Booking.com sin condiciones, y el más barato del conjunto por un margen amplio.

**2. Se migrará a Channex cuando el portfolio se acerque a las 25–50 unidades.** Ahí se cruzan las curvas: $155 frente a €225 a 50 unidades, $230 frente a €863 a 200. El fee fijo de $130/mes que hoy hace a Channex absurdo pasa a amortizarse. Su staging es gratuito y self-serve (`staging.channex.io`, sin tarjeta ni llamada comercial) y se abrirá en paralelo desde ya, para no llegar en frío a esa migración y porque es la única forma de ejercitar el entorno de test de Booking.com.

**3. Se separa `PMSMessagingPort` de `PMSAdapter`.** El puerto único de PRD §16 mete mensajería, reservas y ARI en el mismo `Protocol`. Avantio, ICNEA y WuBook no tienen mensajería alguna; Smoobu tiene la mitad rota. Mantenerlos en un solo contrato garantiza romper la sustitución de Liskov que exige `sdd/steering/backend-architecture.md:108` en cuanto se pruebe un segundo proveedor: `MockPMSAdapter` y el real dejarían de ser intercambiables. Un proveedor sin mensajería debe poder implementar el puerto de reservas y no implementar el de mensajería, en vez de implementarlo lanzando `NotImplementedError`.

**4. SES.Hospedajes se resuelve con Chekin, no con el PMS.** ~€3,95/propiedad/mes, sandbox self-serve en `api-ng.chekintest.xyz`, REST/JSON. Es el único proveedor localizado que cubre por API **las dos patas del RD 933/2021** —el parte de viajeros y la comunicación de cada reserva en 24 h, que casi todos omiten— con webhooks `PoliceRegistration.created|complete|error|retry_error`. Encaja tal cual en el `SESHospedajesAdapter` que PRD §3.3 ya define. No cambia el alcance del MVP: PRD §17 mantiene `MockSESHospedajesAdapter` y no implementa submission real sin credenciales.

**Obligación que crea esta decisión**: Chekin es un **nuevo sub-encargado de datos personales**. Adoptarlo envía `document_number` y fecha de nacimiento —la PII que `security.md` §"Datos sensibles" señala como más sensible— a un tercero. `security.md` §"Triggers de revisión extra" lista *"dependencias nuevas, manejo de documentos de huésped"*, así que la salida de PII, el DPA y la política de retención se verifican en `access-notifications`, que es donde se integra de verdad. Hoy no aplica porque el adapter sigue siendo el mock, pero la decisión queda en acta.

**5. La capa de accesos queda como decisión abierta, deliberadamente aplazada.** Este ADR **no** elige cómo se generan los códigos de puerta. Se decidirá durante la integración del PMS, porque hay una posibilidad real de que el problema se disuelva sin necesidad de GrinPass.

El motivo del aplazamiento: Beds24 trae **22 sistemas de cerraduras nativos** —entre ellos **TTLock y Nuki**, con PIN configurable de 4 a 9 dígitos y passcode online u offline— y una **Arrivals API** diseñada exactamente para sistemas de accesos de terceros: devuelve las llegadas próximas en JSON y permite que el sistema de accesos **escriba el código de apertura de vuelta en la reserva**, con autenticación de dos niveles (*merchant key* de Beds24 más *access key* por propiedad) y control sobre si se exponen datos personales. Decidir hoy la arquitectura de accesos sería decidirla sin saber cuál de esas piezas encaja.

Las tres vías, en orden de preferencia, a evaluar durante la integración:

1. **TTLock o Nuki nativo en Beds24** — cero integración propia. Viable **si** las cerraduras IBINTEL instaladas corren sobre una de esas plataformas.
2. **Arrivals API de Beds24** — GrinPass consume las llegadas y devuelve el código a la reserva. Es el encaje que el propio producto de GrinPass pide: se describe a sí mismo como la capa que coordina entre PMS y cerradura. **Cuidado con el retorno del código**: escribirlo *de vuelta en la reserva* del proveedor significa que el PIN vuelve a nosotros en los payloads de reserva y de webhook, y aterrizaría en claro en `webhook_events.payload` —donde la regla 11 de `security.md` exige forma estructurada, "el valor no sobrevive en absoluto"— saltándose las reglas 3 y 4 sin que nadie escriba una línea que parezca una violación. Si se elige esta vía, el código se **redacta en recepción, antes de escribir `webhook_events`**, y se persiste una referencia, nunca el valor renderizado. El momento importa: la arquitectura que fija la regla 12 y `reservations-webhooks` persiste el payload crudo con `processed=FALSE` y lo procesa después de forma asíncrona, así que "eliminarlo en la ingesta" llegaría tarde — el PIN ya estaría comprometido en la columna que la regla 11 exige limpia.
3. **`.ics` publicado por AutoHostAI** — fallback si GrinPass no puede consumir la Arrivals API.

**La pregunta que resuelve cuál aplica**: sobre qué plataforma corren realmente las cerraduras IBINTEL instaladas. GrinPass declara soportar TTLock, Nuki, Tedee, SwitchBot, Aqara, Sonoff/eWeLink, KNX y Hikvision; si el hardware es TTLock —común en este tipo de cerradura— la vía 1 elimina un proveedor entero de la arquitectura. PRD §5.5 fija que las cerraduras están instaladas y no se cambian, y eso se respeta: no obliga a conservar GrinPass como capa de gestión si el hardware habla un protocolo que Beds24 ya conoce.

Tres hechos que no caducan y valen para cualquiera de las tres vías:

- **Ni GrinPass ni IBINTEL aparecen en el catálogo de integraciones de ningún proveedor evaluado** (Beds24, Avantio, ICNEA, Lodgify, Chekin, Roomonitor). Si se conserva GrinPass, ese puente lo construimos nosotros con el PMS que sea.
- **La API REST de GrinPass no es pública todavía, pero están receptivos a construir nuevas integraciones** (confirmado con ellos el 2026-08-02). Eso es más blando que el *"no ofrece API directa salvo proyectos muy grandes"* de PRD §5.5, y abre la opción de posicionarnos como partner de integración temprano.
- **Los feeds iCal de las OTAs son inservibles para esto**: Airbnb elimina desde diciembre de 2019 el nombre del huésped y el código de reserva del título del evento, dejando solo los últimos 4 dígitos del teléfono; Booking.com solo emite fechas. Si se usa la vía 3, el emisor del `.ics` tiene que ser AutoHostAI, nunca la OTA.

Nada de esto bloquea el MVP: PRD §15 y §3.3 ya prevén `ManualAccessAdapter` y `ExternalManagedAccessAdapter` detrás de `AccessProviderAdapter`, y el operador introduce el código a mano mientras tanto. La decisión de accesos tendrá su propio ADR cuando la integración del PMS aporte los datos que hoy faltan.

**6. Se retiran Smoobu y Hostaway de la lista de candidatos de PRD §5.4**, y Octorate baja de preferente a segunda opción. La lista efectiva pasa a ser: Beds24 → Octorate → Channex (fase SaaS).

**7. El proveedor se resuelve por propiedad, no por proceso.** PRD §22 define `PMS_PROVIDER` como una única variable de entorno (`'mock' | 'octorate' | 'smoobu' | 'beds24'`). Es suficiente para el MVP —un tenant, dos viviendas, un proveedor— pero es estructuralmente incapaz de soportar dos proveedores conviviendo, y eso se necesita en dos escenarios que van a ocurrir:

- **La ventana de migración a Channex** (decisión 2). Un portfolio no se migra en un día: durante semanas habrá viviendas en Beds24 y viviendas en Channex.
- **La fase SaaS.** Los clientes llegan con el PMS que ya tienen contratado. Exigirles migrar para poder usar AutoHostAI es perder la venta.

El diseño es:

- `Property` guarda su proveedor y sus credenciales.
- Una `PMSAdapterFactory` recibe una `Property` y devuelve el adapter que le corresponde. Los casos de uso nunca reciben un adapter inyectado como singleton.
- **Cómo compone esto con la decisión 3 queda abierto para `pms-beds24-adapter`**: separar `PMSMessagingPort` significa que la factory resuelve *dos* puertos por propiedad, no uno, y que un proveedor puede implementar el de reservas y no el de mensajería. Falta decidir la forma exacta —¿una factory con dos métodos, o resolución de puerto opcional que devuelve `None`?— y qué hace `messaging-ai` ante una propiedad cuyo proveedor no soporta mensajería. Hoy no muerde, porque los tres candidatos vivos (Beds24, Octorate, Channex) la soportan; muerde el día que entre un cliente SaaS con Avantio o ICNEA, que no la tienen.
- `PMS_PROVIDER` sobrevive como valor por defecto para el bootstrap y el modo mock, no como selector global.

Hoy la factory devuelve siempre `Beds24Adapter` o `MockPMSAdapter` y todas las filas dicen `beds24`. Se hace ahora igualmente porque **retrofitearlo es caro y hacerlo desde el principio no lo es**: si la capa de aplicación se escribe contra un adapter inyectado, resolver por propiedad más tarde obliga a tocar todos los casos de uso; si se escribe recibiendo la propiedad, no hay nada que tocar.

**No todas las credenciales son por propiedad**, y conviene decirlo porque cambia el radio de daño: Beds24 usa una *merchant key* de **cuenta** para la Arrivals API, su modelo de organización da **un token para N cuentas de cliente**, y los refresh tokens son de cuenta. Una credencial de cuenta comprometida concede escritura sobre *todas* las propiedades de esa cuenta, no sobre una. Por eso la regla 3 ampliada cubre las tres granularidades —propiedad, cuenta y organización— y no solo la primera.

Las credenciales por propiedad son secretos **en base de datos**, y eso cambia qué regla las gobierna. La **regla 8** de `sdd/steering/security.md` no sirve: su ámbito es el repositorio (*"cero secretos reales **en repo**… solo el nombre en `.env.example`"*), un modelo pensado para un secreto único por proveedor en el entorno. La regla aplicable es la **3** (cifrado en reposo con Fernet), cuya enumeración este ADR amplía para incluirlas — igual que la línea 838 del PRD hace con los códigos de acceso, que es de lo que esa línea habla y no de un contrato general de credenciales.

Antes de este change, la regla 8 listaba *"credenciales de PMS"* entre los secretos de `.env.example`, un modelo de secreto único por proveedor incompatible con la decisión 7. Este change corrige ambas reglas: la 8 queda acotada al `PMS_API_KEY` de bootstrap y modo mock, y la 3 amplía su enumeración a las credenciales por propiedad, con tres obligaciones que el resto de esa enumeración no tiene —solo escritura, `AuditLog` de lectura y rotación, y test de aislamiento propio— porque una credencial robada concede **escritura** en el sistema del cliente, no solo lectura de un dato.

**Lo que esta decisión NO habilita**: dos proveedores sobre la **misma** vivienda. Es imposible por dos motivos independientes — Airbnb admite un solo channel manager por cuenta (*"If there is already another channel manager or PMS connected to Airbnb the connection will not complete"*), y aunque lo permitiera, dos sistemas empujando ARI al mismo anuncio sin coordinación producen overbookings. El ARI exige una única fuente de verdad por unidad; eso no es una limitación de proveedor sino la naturaleza del problema.

## Consecuencias

**A favor:**

- El puerto §16 se implementa sin inventar nada. Beds24 tiene CRUD completo de reservas incluido `DELETE`, y bloqueo de fechas de primera clase vía `POST /inventory/rooms/calendar` con `override: blackout | noCheckIn | noCheckOut | noCheckInOrCheckOut`. Con Smoobu, `block_dates()` habría tenido que crear reservas fantasma con `channelId: 11` y todo consumidor filtrar `is-blocked-booking`.
- `messaging-ai` deja de depender de un `si soportado`. `GET/POST/PATCH /bookings/messages` con `source: host | guest | internalNote | system` y adjuntos en base64 cubre Airbnb, Booking.com, Expedia y el grupo Vrbo por la misma interfaz.
- API REST con OpenAPI 3.0 y scopes granulares (`read:` / `write:` / `all:` sobre `bookings`, `inventory`, `properties`), tokens de 24 h con refresh y whitelist de IP. Frente al SOAP de Avantio e ICNEA o el XML-RPC permanente de WuBook.
- Entorno de desarrollo permanente por ~€15,50/mes: el trial de 14 días abre una cuenta completa que después se convierte en cuenta normal conservando la configuración.
- El camino a SaaS existe: el modelo de organización de Beds24 da un token para N cuentas de cliente, con la cuota de créditos separada por cuenta, lo que favorece el fan-out.
- Coste de equivocarse bajo: prepago, sin permanencia, y el trabajo real está detrás del puerto.
- La resolución por propiedad (decisión 7) deja abiertos a coste casi nulo tanto la ventana de migración como el alta de clientes SaaS que llegan con su propio PMS. Hoy son una factory y dos columnas.

**En contra, y asumido:**

- **El mapeo de Booking.com no se puede hacer por API.** Literal: *"Mapping to booking.com cannot be done via our API."* Cada alta en Booking.com exige un humano en el panel de Beds24. Con dos viviendas es un paso puntual; a escala de SaaS es fricción real, y es uno de los motivos por los que la migración a Channex tiene fecha aproximada en el punto 2.
- **No hay subida de fotos en V2**, una regresión respecto a V1, que sí tenía `setPropertyContent`. No afecta al MVP porque PRD §29 lista el posting automático en OTAs como non-goal, pero cierra la puerta a que eso entre en alcance sin cambiar de proveedor.
- **El coste por request es dinámico y no está publicado.** 100 créditos por 5 minutos y por cuenta, con coste calculado según la complejidad de la llamada. Hay que medir `X-RequestCost` empíricamente antes de diseñar el polling; duplicar el límite cuesta €10/mes por ticket de soporte. Beds24 además desaconseja explícitamente el uso en tiempo real y recomienda sincronización completa cada ~6 horas.
- **Los webhooks no van firmados.** Ni HMAC ni secreto compartido; el único mecanismo es una cabecera estática que pones tú. PRD §16 dice "valida firma HMAC si el provider lo soporta", y aquí no lo soporta: todo webhook se trata como aviso no fiable y se re-lee por API. Esto no es específico de Beds24 — **ninguno** de los once proveedores evaluados firma sus webhooks, y Channex documenta además que llegan desordenados.

  **Y eso deja una regla vacía, no cumplida.** `security.md` §"Triggers de revisión extra" listaba *"validar firma HMAC **cuando el provider lo soporte**"*: al ser la condición falsa para los once, el trigger queda permanentemente inerte y **nada gobernaba el caso sin firma**. Con la mitigación de re-leer por API, un `POST /api/v1/webhooks/{provider}` sin autenticar convierte a cualquiera que adivine la ruta en un amplificador: inserta filas en `webhook_events` y fuerza lecturas contra una cuota de 100 créditos por 5 minutos y por cuenta, matando el sync legítimo. Es un problema de disponibilidad nacido de uno de integridad. Este change añade la **regla 12** a `security.md` para cubrirlo, y `reservations-webhooks` la hereda.

  **Cuarta desviación del PRD, y aquí queda registrada.** PRD §23 (línea 2020) define la ruta como `POST /api/v1/webhooks/{provider}`, que es globalmente adivinable: `{provider}` es un nombre público y corto. La regla 12(b) exige una ruta no adivinable por tenant, así que la forma pasa a llevar un **segmento token opaco por tenant** — `POST /api/v1/webhooks/{provider}/{webhook_token}`, con el token generado en el alta, rotable y distinto del secreto de cabecera de 12(a). No es cosmética: sin ella el endpoint queda expuesto a cualquiera que conozca el nombre del proveedor, y el secreto de cabecera pasa a ser la única defensa. `sdd/specs/reservations.md` documenta hoy la forma del PRD; se corregirá al archivar `reservations-webhooks`, que es su change dueño.
- **Los webhooks se configuran por propiedad desde la UI**, sin API de suscripción. A escala de SaaS son N configuraciones manuales.
- **Parte de la superficie está en Alpha/Beta**, incluido `GET /organizations/users` —el endpoint de descubrimiento del modelo partner— todavía en "Coming soon". Es una dependencia del camino multi-tenant, no del MVP.
- **Cobertura nula de portales españoles nativos.** Beds24 no lleva Rentalia, Niumba, Escapada Rural ni equivalentes. Para vivienda turística en Madrid, Airbnb y Booking.com concentran la demanda, así que hoy es irrelevante; si algún día pesa el canal español nativo, WuBook (Casas Rurales, Niumba, Atrápalo, Esquiades, Mirai, Fincahotels, Spotahome) y Avantio (Muchosol, Rentalia, Iberimo, Plusholidays) son los que lo tienen.
- **Credenciales de PMS por propiedad son secretos en base de datos**, no en el entorno. Es superficie de ataque nueva y una obligación de rotación que `PMS_PROVIDER` como env var no tenía. Se acepta porque la alternativa —un proveedor global— cierra la fase SaaS, pero arrastra **cinco obligaciones que hereda `pms-beds24-adapter`** y que ninguna regla vigente cubría antes de este change:
  1. **Cifrado (regla 3, ampliada aquí)** — aplicado desde la primera migración que cree esas columnas, no después. Hoy no existe la primitiva: `git grep -i fernet` en `backend/` no devuelve nada.
  2. **Aislamiento (regla 1)** — con credenciales en `Property`, un fallo de scoping deja de ser divulgación cross-tenant y pasa a ser **escritura** en el calendario, el pricing y la mensajería de otro cliente. Cambia la clase de impacto, así que esas columnas necesitan su propio test de aislamiento, no el genérico del módulo.
  3. **No serialización (regla 4)** — la regla 4 enumera códigos de acceso y `document_number`; nada prohíbe hoy que una respuesta de detalle de propiedad serialice la credencial descifrada a cualquiera con permiso de lectura. La columna necesita contrato de solo escritura, nunca en respuesta.
  4. **Auditoría (regla 9)** — la enumeración de `AuditLog` no incluye leer ni rotar una credencial de proveedor, así que hoy ese acceso sería invisible.
  5. **Marcado de sesión** — un job que resuelve adapter por propiedad tiende a iterar propiedades de varios tenants en un proceso. Si reutiliza una sesión cambiando solo el adapter, choca con el guard de `bind_session_to_tenant` que impide re-marcar; si corre sin marcar, pierde el filtro global y depende de que **toda** lectura y escritura lleve `tenant_id` explícito. El precedente vigente (`specs/reservations.md`) es `pms_sync <tenant>`: un tenant por invocación, sesión marcada a ese tenant. Cualquier diseño por lotes debe abrir una sesión marcada por tenant, nunca re-marcada, o filtrar explícitamente — el mismo patrón que ya se fijó para `webhook_events`.
- **Reutilizar una sola `ENCRYPTION_KEY`** para PII de huésped y credenciales de proveedor acopla su radio de daño y su rotación. Se acepta para el MVP; si la fase SaaS lo hace insostenible, la salida es `MultiFernet` con claves separadas, que hoy no existe en el repo.
- **No existe sandbox de OTA en ningún proveedor.** Se asume una propiedad real con cuentas OTA reales como activo permanente de staging. Las dos viviendas de Madrid lo cubren. Y Airbnb admite **un solo channel manager por cuenta**, así que evaluar un segundo proveedor sobre el mismo anuncio exige desconectar el primero: no hay pruebas en paralelo y la migración futura es una ventana de corte, no un solapamiento.

### Qué revertiría esta decisión

- Que el coste real de créditos de Beds24 haga inviable la cadencia que necesita `messaging-ai`. Se mide en la primera semana de la cuenta de desarrollo.
- Que Octorate confirme por escrito la mensajería de Booking.com y negocie el plan de API a la baja. Octorate es mejor producto en casi todo lo demás —sandbox conmutable por API, push de contenido documentado end-to-end para Airbnb, SES.Hospedajes y Verifactu nativos, servidor MCP propio— y lo único que lo descarta hoy es el fee de €1.600/año sobre una base de €15–20/unidad/mes.
La capa de accesos **no** está en esta lista: al quedar aplazada (decisión 5) ya no puede revertir la elección de proveedor. Beds24 cubre las tres vías posibles, así que ninguna resolución de ese frente obliga a cambiar de PMS.

## Alternativas rechazadas

- **Smoobu** (€47/mes a 2 uds) — era la opción con mejor pinta inicial y cae por un detalle documentado en su propio help center: *"it is necessary to go to the booking details page in Smoobu to have the new message imported from Booking.com into Smoobu conversation history."* Un humano tiene que abrir la ficha en la UI para que entre un mensaje de Booking.com; una integración headless los pierde en silencio. Para un producto cuyo núcleo es la atención al huésped 24/7 con IA, eso es descalificante. Se suma que no sincroniza contenido por decisión de producto declarada (*"No, it doesn't… Synchronizing content would make Smoobu very complicated and expensive"*), que la disponibilidad no es escribible, y que su plan barato Flex lleva 0,9% de comisión sobre el bruto de canales conectados — su propio ejemplo da €97/mes de comisión para ahorrar €6.

- **Octorate** (~€150/mes efectivos a 2 uds) — segunda opción, y descartada solo por precio. Su API es la más completa evaluada: 158 rutas, `Chat` con 20 endpoints incluyendo traducción a 14 idiomas, ofertas especiales de Airbnb y un toggle de su propia IA por hilo; sandbox real conmutable con `environment: SANDBOX`; 54 operaciones de contenido con showcase completo de publicación en Airbnb; SES.Hospedajes automático y Verifactu/TicketBAI vía Fiskaly. Lo hunde el plan de integración de API: **€1.600/año o €2.800 por dos años**, sobre una base realista de €15–20/unidad/mes (no los €8 publicados). Siete a ocho veces Beds24 en la escala actual. Queda como la alternativa a reconsiderar si el fee se negocia.

- **Channex** ($131/mes a 2 uds) — la elección correcta *más adelante*, no ahora. Su lista pública de "mal encaje" incluye *"You run one hotel and want to connect it to OTAs — buy a channel manager directly instead"*, y la de buen encaje *"You build the software a property runs on"*: AutoHostAI califica como vendor de software, así que la elegibilidad no es el problema — lo es que a 2 unidades sales a $65,50/unidad frente a $10–25 de un CM retail. Además no publica contenido a ninguna OTA salvo Google Hotel Ads (*porque Google no tiene extranet*), su API de canales es solo para cuentas whitelabel y está sin documentar, y su app de mensajería es de pago por propiedad.

- **Hostaway** (~$125–175/mes a 1–4 uds) — sin trial, sin tier gratuito, sin on-ramp self-serve a ningún tamaño de portfolio; contratos de plazo fijo con cargos por cancelación anticipada. Factura **por listing incluyendo los no conectados y los parent/child**, así que un edificio listado como propiedad entera más 4 apartamentos son 5 listings facturables. Y al cancelar *"reservation data will be lost, as we don't keep reservation data after an account is deactivated"* — un proveedor que destruye tu histórico a los 30 días no puede ser fuente de verdad.

- **Avantio** (€295/mes a 2 uds) — mejor estatus de partner del conjunto (Airbnb Preferred, Booking.com Premier, Vrbo Elite), la mejor cobertura de portales españoles y push de contenido completo con `TouristicRegistrationNumber` y referencia catastral. Pero **no tiene ninguna API de mensajería**: sus dos WSDL públicos exponen cero operaciones de conversación, y el "Unified Inbox incluido en la API" que promete su web es una pantalla de su aplicación, no una superficie programable. Tampoco tiene webhooks —solo `GetBookingNotifications`, una cola de sondeo— ni creación de reservas en la API de entrada. Suelo de €295/mes, que a 2 unidades son €147,50/unidad.

- **ICNEA** (€150/mes a 2 uds) — la mejor relación precio/escala en la franja media española (€590 a 200 unidades frente a €2.800 de Avantio), con sandbox de doble credencial y Modelo 179 e INE nativos. Sin mensajería, SOAP de 2021, changelog sin entradas desde diciembre de 2021 y documentación ahora tras login.

- **WuBook** (€42/mes a 2 uds) — mensajería solo Airbnb, e imposible modificar reservas originadas en OTA (*"it's not possible to modify reservations originated by OTAs"*). Factura por par (propiedad, canal), lo que a 200 unidades da €4.200/mes. Conserva dos cosas que nadie más tiene: mapeo totalmente programático de Booking.com y Expedia, y provisioning de clientes sin intervención humana con `corporate_new_account_and_property()`.

- **Lodgify** (~$103/mes en el tier sin comisión) — API pública self-serve con 79 endpoints, mensajería de lectura y envío con webhook `guest_message_received`, y SES.Hospedajes nativo. Cae porque la API está limitada a Professional o superior, los tiers inferiores llevan 1,9% de comisión sobre reservas, no tiene push de contenido y su registro de viajeros no aparece en el índice OpenAPI, así que probablemente sea solo de UI.

- **NextPax** ($350/mes mínimo, incluye 50 unidades) — único que anuncia automatización de contratación con OTAs (*"creating Airbnb Host Accounts, requesting Booking.com agreements"*), pero la evidencia pública respalda el *takeover* de anuncios existentes mucho más que la creación neta, y su sandbox está tras login. A 2 unidades son $175/unidad.

- **Rentals United** (~€107/mes a 10–19 uds) — el push de contenido más completo del mercado (100 imágenes, diccionario de amenities, números de licencia con variante española) y mensajería en Airbnb, Booking.com y Vrbo. Fuera por XML puro contra un único endpoint `.ashx`, sandbox solo tras contrato firmado, suelo declarado de 10 propiedades, activación de canal solo por UI y facturación por **máximo histórico de propiedades** — provisionar unidades de prueba las deja facturadas para siempre.

- **Integración directa con las OTAs** — ya era non-goal en PRD §29 y ahora además es impracticable: Booking.com tiene pausada el alta de proveedores de conectividad sin fecha, Airbnb es invite-only, y Expedia está moviendo su documentación de supply detrás de login.

- **Amenitiz, Noray, Roomonitor, Rentalwise, Hospedium, Bookiply** — descartados en la primera criba: API de solo lectura, ámbito hotelero/enterprise, feed unidireccional, o inexistencia de documentación pública y de API.
