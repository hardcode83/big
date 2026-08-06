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

Dos hallazgos del panel de seguridad sobrevivieron a la tercera ronda de arreglo. **Se dejan
abiertos a propósito**: el flujo permite dos rondas, se tomó una tercera porque aquellos eran
defectos funcionales, y estos dos no lo justifican. Decide antes del PR.

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

Arreglo: quitar la cardinalidad de la línea de resumen (nombrar la acción, no cuántas filas) y
reducir `entities.py:73` al mecanismo. Dos líneas.

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

Arreglo propuesto por el panel: capturar `SecretDecryptionError` en `main` y salir con código
propio; permitir que `set` **sobrescriba** unas coordenadas cuyo valor no se puede leer (no hace
falta el claro anterior para reemplazarlo), y que `rotate` siga negándose.

## Nota para el archivado, no bloqueante

Un `read_log` obligatorio garantiza **recolección**, no **persistencia**: las filas llegan a
`audit_logs` porque `SyncReservationsFromPmsUseCase` empareja el log con un `audit` obligatorio y lo
vuelca en el `finally`. Un futuro llamante iniciado por persona o API debe emparejar los dos igual.
Hoy no existe tal llamante; merece una frase en `specs/` al archivar.

