# BLOCKED — pms-provider-resolution

> **Ambos bloqueos resueltos el 2026-08-06 por Jose**: se toma la opción (a), agrupar por
> proveedor, y se implementa **en este change**. El detalle de la decisión queda abajo, tachado
> como histórico, porque el razonamiento —y sobre todo los números medidos que lo sostienen— es
> lo que hay que releer si alguien reabre la cadencia del sync. El fichero se borra al archivar.

## ~~1. ¿Cómo se abanica el sync cuando cada propiedad puede tener un proveedor distinto?~~ RESUELTO

**Decisión: (a) agrupar por proveedor, en este change.**

`SyncReservationsFromPmsUseCase.execute` llamaba **una sola vez** a `list_reservations(since)`
para todo el tenant y resolvía la propiedad de cada reserva por `pms_external_id`. Esa forma
presupone **un adapter por ejecución**, que es lo que R2.2 retira.

Lo que decidió entre las dos opciones, y conviene no volver a derivarlo:

- **(b) una llamada por propiedad escala sin cota** con el portfolio. Con 12 propiedades en
  Beds24 un solo ciclo se come el **96% de la cuota** de 100 créditos / 300 s — medido sobre una
  cuenta **vacía** (`specs/pms-beds24-spike.md` avisa de que con reservas dentro sube), y el
  proveedor desaconseja explícitamente el tiempo real.
- **(a) agrupar escala con el número de proveedores distintos** que el tenant tenga configurados
  — 2-3 hoy, acotado por definición. Y como **todos** los proveedores evaluados autentican con
  credencial de cuenta, «una llamada por proveedor» **es** «una llamada por cuenta», que es
  exactamente la forma que el spike midió y validó como sostenible.
- **Diferirlo a `pms-beds24-adapter` era la secuencia más arriesgada**: dejaría un caso de uso que
  sigue asumiendo un adapter por ejecución, así que un tenant a mitad de migración —el escenario
  que ADR 0006 y este proposal nombran como motivo principal de R2— quedaría mal servido justo
  cuando la feature debería importar.

**Lo que la implementación añade y no estaba previsto en el design**: `PropertyRepository.list_all`
y `PMSAdapterFactory.provider_for`. El segundo es necesario porque el override `--provider` vive
en la factory: agrupar por `property.pms_provider` a secas ignoraría el override al agrupar y lo
aplicaría al resolver, que es una incoherencia silenciosa.

## ~~2. Dónde se escribe la fila de auditoría por ejecución~~ RESUELTO

Se escribe en `SyncReservationsFromPmsUseCase.execute`, al cerrar el run, con `CredentialReadLog`
deduplicando. **Cuántas filas** lo dice la regla 9 de `steering/security.md` y solo ella: este
fichero enunciaba el número dos líneas antes de declarar que no lo reformulaba, que es la forma en
que empezaron las copias anteriores.

**La granularidad exacta la fija la regla 9 de `steering/security.md`, y este fichero no la
reformula** — lo intentó dos veces y las dos se quedaron obsoletas cuando la regla se corrigió.
Lo que sí aporta y es suyo: la medición de la que salió el debate, que un sync de N propiedades
servidas por una credencial de cuenta la descifra N veces, y que **hoy** solo un proveedor guarda
credencial (`BEDS24`), así que la repetición es en el tiempo y no en el portfolio.

---

# Abierto tras `/sdd:review` (2026-08-06)

Dos hallazgos del panel de seguridad sobrevivieron a la tercera ronda de arreglo. Se dejaron
abiertos a propósito —el flujo permite dos rondas— y **Jose los devolvió resueltos a mi criterio
(2026-08-06)**. Ambos quedan **CERRADOS** abajo; se conserva el enunciado original porque el valor
de esta entrada está en por qué llegaron hasta aquí, no en el parche.

## 1. La línea de resumen de `_record_credential_reads` sigue enunciando el número

- **Tipo**: `decision` · **Comando**: `/sdd:review pms-provider-resolution`
- **Dónde**: `backend/app/integrations/application/use_cases.py:241`, y el caso adyacente y más
  leve en `backend/app/integrations/domain/entities.py:73`.

La primera línea del docstring dice *"One `PMS_CREDENTIAL_READ` row per DISTINCT credential this
run decrypted"* — un número — y cuatro líneas más abajo el mismo docstring afirma que **no** dice
nada sobre eso y que la regla 9 es donde se enuncia. Se contradice consigo mismo. Hoy el número es
correcto, *que es exactamente como empezaron las cinco copias anteriores*.

**Por qué el barrido volvió a fallar, y es lo que hay que aprender de aquí**: cambié «buscar
frases» por «buscar más frases». `One \`PMS_CREDENTIAL_READ\` row per` no contiene la subcadena
`one row per` — hay dos tokens en medio. Es **el mismo fallo estructural que el primer barrido, un
nivel más arriba**: la primera vez se me escaparon las copias en inglés por buscar en español; esta
vez se me escapó por buscar una subcadena en vez de la afirmación.

**CERRADO (2026-08-06).** La línea de resumen es ahora *"Record this run's credential reads
(R4.2)"* — la acción, sin número — y `entities.py` se reduce al mecanismo: deduplica por id, y a
qué da derecho eso «es asunto de la regla, no de esta clase».

Y el barrido se hizo **de otra forma**, porque el problema era el método y no el texto: en vez de
buscar frases, **enumeré los sitios** que mencionan `PMS_CREDENTIAL_READ`, `CredentialReadLog`,
`read_log` o `credential_ids`. Una enumeración no puede fallar por la redacción de lo que busca,
que es lo que hundió los dos barridos anteriores.

**Y a la primera lo hice mal, de una forma que importa.** Declaré «32 menciones en 8 ficheros»
cuando sobre todo fichero versionado son **54 en 10**: había excluido los tests sin decirlo. Justo
la clase de artefacto que ya había fallado antes —un nombre de test es una frase con pinta
normativa que CI ejecuta, y `test_the_read_log_deduplicates_by_credential_id` hubo que renombrarlo
por eso mismo—. Un método presentado como inmune a la redacción, acotado por un filtro tácito.
Rehecho sin filtro: las 20 menciones que faltaban están limpias, son llamadas y nombres de
escenario («una credencial de cuenta, un id»), ninguna enuncia una regla general.

**El límite del método, que el panel encontró y yo no**: estos cuatro símbolos son un proxy de «los
ficheros que tocan el código del read log», y la afirmación vive además en los ficheros que
**planifican** ese código. `tasks.md` no contiene ninguno de los cuatro, y ahí seguía viva una
reformulación — la de la tarea 6.3, que juraba no reformular la regla y la reformulaba en la frase
siguiente, **y encima al revés**: decía «N propiedades producen una fila y no N», que bajo scope
`PROPERTY` son N credenciales distintas y N filas, es decir exactamente el colapso que la regla 9
prohíbe. Corregida junto con su eco en la 10.5, nombrando el escenario en vez de la regla.

**Y ese arreglo del método tampoco bastaba.** Declaré entonces que el barrido correcto eran dos
conjuntos —enumeración por símbolos sobre todo lo versionado, más lectura íntegra de los artefactos
del change— y el panel lo falsó con un miembro del segundo conjunto que el segundo conjunto no
cazó: `design.md:36` decía «una fila de auditoría por propiedad consultada», que es falso
justamente en el caso que D4 establece como el real —credencial de cuenta, que `CredentialReadLog`
deduplica— y lo decía **citando a D6 mientras contradecía su mecanismo**. Tercera instancia del
mismo error que la primera glosa: aritmética por propiedad donde el scope de cuenta colapsa.

Los dos conjuntos fallan por la misma razón, y es la lección de verdad: **los dos son temáticos**.
Uno encuentra ficheros que tocan el código del read log; el otro, párrafos *sobre* granularidad de
auditoría. `design.md:36` no es ninguno de los dos — enuncia la cifra **de pasada, dentro de un
argumento sobre otra cosa** (si `supports_messaging` puede ser impuro). Ahí es donde se esconde la
afirmación ahora, y ahí se escondía también la de `tasks.md:48`.

**El chequeo que sí cierra la clase**, porque es por propiedad y no por tema: barrido del campo
semántico sobre los 824 ficheros versionados — términos de auditoría ∩ términos de credencial,
filtrado por cualquier cuantificador. Da 54 líneas, todas leídas: las únicas que enuncian una cifra
son `security.md:39` y `:43`, que es el hogar normativo. El resto son obligaciones sin número,
mecanismo o alternativas rechazadas. Subsume los dos conjuntos anteriores.

**Aviso para el archivado**: `sdd/specs/` es el próximo sitio donde esta afirmación intentará
vivir, porque el contenido de este design se convierte en spec. Y si R4.2 de `proposal.md:63` se
copia literal a una spec sin el acotamiento al lado, se convierte en la copia huérfana de la que
trata la regla 9. Correr el barrido semántico al archivar.

## 2. El comando de credenciales no puede reparar la fila cuyo error acaba de traducirse

- **Tipo**: `decision` · **Comando**: `/sdd:run pms-provider-resolution 8`
- **Dónde**: `backend/app/integrations/cli/pms_credentials.py:139` y `:242-247`.

`store_with_session` llama a `get_for` **antes** del upsert, tanto en `set` como en `rotate`. Contra
un valor almacenado malformado —que desde el commit `63b6cb4` lanza `SecretDecryptionError`— y como
`main` solo captura `UsageError`, **ambos subcomandos mueren con un traceback**.

Consecuencia operativa real: quien tenga que rotar una credencial **comprometida** cuya fila esté
malformada (escrita a mano, restauración truncada) se queda **sin vía auditada**, y la única
alternativa es SQL crudo — que se salta el cifrado, el guard cross-tenant y la fila
`PMS_CREDENTIAL_ROTATED`, es decir justo lo que este comando existe para evitar.

**No lo introdujo este change**: el hueco es previo, y lo que hizo `63b6cb4` fue cambiar el tipo de
excepción y volverlo visible.

**CERRADO (2026-08-06), y por una vía distinta a la propuesta.** El panel proponía capturar la
excepción; lo que hay debajo es que **el comando nunca necesitó leer el secreto**. Usaba `existing`
para tres cosas —el id de la fila, si existe, y `rotated_at`— y ninguna es el valor, que además está
a punto de sobrescribir. Así que el arreglo es un método nuevo del puerto, `id_at`, que selecciona
la **columna** `id`: no hay camino de código desde ahí hasta un `EncryptedSecret`, con lo que la
garantía es estructural y no una promesa. Descifrar deja de ocurrir, en vez de fallar y ser
capturado.

Divergencia deliberada respecto del panel en un punto: **`rotate` tampoco se niega ya** ante un
valor malformado. Negarse dejaba sin vía auditada justo el caso que motiva el hallazgo. La fila
existe, así que hay algo que rotar; el guard sigue intacto para su caso real, que es que **no haya
fila** (una errata en las coordenadas). Y el `entity_id` de la fila `PMS_CREDENTIAL_ROTATED` sale
del id almacenado, no de un `uuid4()` nuevo — hay test que lo fija, porque si no la traza nombraría
una credencial que nunca existió.

`main` captura `SecretDecryptionError` de todos modos y sale 3 sin traceback y sin imprimir `USAGE`
(no es una invocación mal formada, y mandar al operador a revisar sus argumentos lo enviaría a
mirar donde no es). Hoy es código inalcanzable: es la red por si alguien añade una ruta que sí
descifre.

Los tres tests se verificaron **contra el código viejo** —reintroduje el parse y los tres fallan con
el `SecretDecryptionError` original— porque un test que pasa no prueba nada si también pasaba antes.
La corrupción de las pruebas es **texto plano**, no un ciphertext estropeado: esa distinción es la
que hizo que el test de aislamiento anterior ejercitara solo la mitad que ya funcionaba.

## Nota para el archivado, no bloqueante

Un `read_log` obligatorio garantiza **recolección**, no **persistencia**: las filas llegan a
`audit_logs` porque `SyncReservationsFromPmsUseCase` empareja el log con un `audit` obligatorio y lo
vuelca en el `finally`. Un futuro llamante iniciado por persona o API debe emparejar los dos igual.
Hoy no existe tal llamante; merece una frase en `specs/` al archivar.

