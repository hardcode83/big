# Blocked — pms-beds24-adapter

Actualizado el 2026-08-06 tras recibir la credencial y ejecutar las mediciones. Quedan **dos**
entradas: una decisión de diseño que es de Jose, y una verificación que necesita un tenant sembrado.

## 1. Decisión de diseño: `special_requests` se persiste sin pasar por el scrubber

- **Fase**: run (panel de seguridad de la sección 2, hallazgo 3)
- **Tipo**: `decision` — amplía o acota D9, y no debe decidirse en silencio
- **Qué y por qué**: el scrubber protege `raw_payload`, que **no se persiste** (vive en memoria y ninguna columna lo almacena), y no toca `special_requests`, que **sí**: los dos mapeos lo llenan con texto libre del proveedor (`notes` en Channex, `comments` en Beds24) y de ahí va a `ingest.py` → columna `reservations.special_requests` → respuesta de la API. La regla 13(a) dice «eliminarlos en el adapter… antes de que nada pueda **persistirlos**, loguearlos o reenviarlos», así que el texto alcanza literalmente el verbo que la regla nombra. La regla 11 no lo cubre: ella misma se acota a «un valor de la regla 3», y los datos de tarjeta no están en la regla 3 — eso es justo lo que motivó que la 13 existiera.
- **Lo que NO está medido, y conviene decirlo**: no hay ninguna observación en este repositorio de dígitos de tarjeta dentro de `notes`/`comments`. Es texto que teclea un huésped o un agente, así que es plausible, no demostrado. El hallazgo medido (`raw_message`) ya está corregido.
- **Las dos salidas, y ninguna es gratis**:
  1. **Filtrar por valor** el texto libre que se promueve a un campo del DTO: exige detectar un PAN dentro de una cadena (Luhn + rachas de dígitos), con falsos positivos reales — una referencia de reserva de 16 dígitos — sobre un campo que el personal de limpieza lee.
  2. **Declarar en D9** que el texto libre persistido queda fuera de la frontera de la regla 13, y por qué. Es la opción barata, y deja constancia en vez de dejarlo por omisión, que es como estaba.
- **Cómo desatascarlo**: decidir con Jose. Si es la 1, es trabajo de esta sección; si es la 2, es un párrafo en `design.md` y una nota en la spec al archivar.
- **Comando de reanudación**: `/sdd:review pms-beds24-adapter`

## 2. Verificación manual end-to-end (tarea 7.3)

- **Fase**: run
- **Tipo**: `deferred` — necesita un tenant en la base de datos de dev, que hoy está vacía
- **Qué y por qué**: el camino credencial-en-BD → factory → adapter → proveedor real es el último tramo sin probar en vivo. Todo lo que hay debajo sí está verificado: el transporte contra la API real (sondeo del 2026-08-06), y el encadenado adapter → ingestor → `TimelineEvent` contra Postgres real con payloads capturados.
- **Qué falta exactamente**: `select count(*) from tenants` devuelve 0. Sembrar es `make bootstrap`, que exige las variables `BOOTSTRAP_*` en `.env` — nombres sin valor por la regla 8, así que las pone su dueño. No las invento.
- **Cómo desatascarlo**, una vez haya tenant:

  ```bash
  # 1. credencial — procedimiento completo en docs/pms-credentials.md.
  #    El `-e` va **desnudo**: el valor viaja por el entorno del cliente, nunca como argumento.
  #    `-e VAR="$(cat ...)"` lo mete en el argv de docker y lo publica en `ps` (medido).
  #    Argumentos posicionales, no flags.
  PMS_CREDENTIAL_SECRET="$(cat backend/.env.beds24)" \
    docker compose exec -T -e PMS_CREDENTIAL_SECRET backend \
    python -m app.integrations.cli.pms_credentials set <uuid> beds24 account

  # 2. una propiedad apuntando a la del banco de medición
  #    pms_provider = BEDS24, pms_external_id = 345754

  # 3. el sync de verdad
  docker compose exec -T backend python -m app.integrations.cli.pms_sync <uuid>
  ```

  Qué comprobar: que importa las reservas de prueba de la cuenta, que el `AuditLog` registra **una** fila de lectura de credencial, y que un segundo sync es idempotente.
- **Comando de reanudación**: `/sdd:review pms-beds24-adapter`

---

## Resueltas el 2026-08-06

- ~~**Ejecuciones del banco contra la cuenta**~~ — hechas. `modifiedFrom` existe, restringe de verdad y acepta las dos ortografías; el listado por defecto **oculta las canceladas** e `includeCancelled` se ignora en silencio; el vocabulario de `status` está validado en servidor y hay que enviarlo en parámetros repetidos.
- ~~**El «coste de un ciclo» deja de ser 8 créditos**~~ — decidido: se republica a **10 créditos / 30 s**, porque el catálogo ahora mide la consulta que el sync hace de verdad. El argumento de la regla 9 del steering aguanta igual (~2.880 filas/día frente a ~3.600). `docs/beds24-spike.md` ya lo dice; la propagación a `specs/pms-beds24-spike.md` y a la cita de la regla 9 va al archivar.
- ~~**Dónde excluir los bloqueos de calendario (D10)**~~ — resuelto a favor de la rama preferida del diseño: como hay que enumerar `status` de todas formas para ver las canceladas, dejar `black` fuera de esa lista sale gratis. `is_blocked_dates` se queda en el adapter como defensa en profundidad.
- ~~**Fixtures de reserva modificada y cancelada**~~ — capturados y commiteados. Los tests ya no derivan esos estados a mano.
