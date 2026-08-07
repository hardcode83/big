# Blocked — pms-beds24-adapter

Actualizado el 2026-08-06 tras la revisión a escala de feature. Queda **una** entrada, y no
bloquea el Pull Request: es una verificación manual que necesita un tenant sembrado.

## 1. Verificación manual end-to-end (tarea 7.3)

- **Fase**: run
- **Tipo**: `deferred` — necesita un tenant en la base de datos de dev, que hoy está vacía
- **Qué y por qué**: el camino credencial-en-BD → factory → adapter → proveedor real es el último tramo sin ejercitar en vivo. Todo lo que hay debajo sí está verificado: el transporte contra la API real (sondeo del 2026-08-06, incluido el ciclo crear → modificar → cancelar), y adapter → ingestor → `TimelineEvent` contra Postgres real con payloads capturados. La matriz R# del panel de QA da los seis requisitos por cumplidos con implementación y test, así que esto **no es un hueco de requisito**: es la prueba de integración que solo puede hacerse a mano.
- **Qué falta exactamente**: `select count(*) from tenants` devuelve 0. Sembrar es `make bootstrap`, que exige las variables `BOOTSTRAP_*` en `.env` — nombres sin valor por la regla 8, así que las pone su dueño. No las invento.
- **Cómo desatascarlo**, una vez haya tenant:

  ```bash
  # 1. credencial — procedimiento completo en docs/pms-credentials.md.
  #    El `-e` va **desnudo**: el valor viaja por el entorno del cliente, nunca como argumento.
  #    `-e VAR="$(cat ...)"` lo mete en el argv de docker y lo publica en `ps` (medido).
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

## Resueltas

### El 2026-08-06, con la credencial ya disponible

- ~~**Ejecuciones del banco contra la cuenta**~~ — hechas. `modifiedFrom` existe, restringe de verdad y acepta las dos ortografías; el listado por defecto **oculta las canceladas** e `includeCancelled` se ignora en silencio; el vocabulario de `status` está validado en servidor y hay que enviarlo en parámetros repetidos.
- ~~**El «coste de un ciclo» deja de ser 8 créditos**~~ — decidido: se republica a **10 créditos / 30 s**. El argumento de la regla 9 del steering aguanta igual (~2.880 filas/día frente a ~3.600). La propagación a `specs/pms-beds24-spike.md` y a la cita de la regla 9 va al archivar.
- ~~**Dónde excluir los bloqueos de calendario (D10)**~~ — resuelto a favor de la rama preferida: como hay que enumerar `status` de todas formas para ver las canceladas, dejar `black` fuera sale gratis.
- ~~**Fixtures de reserva modificada y cancelada**~~ — capturados y commiteados.

### El 2026-08-06, en la revisión a escala de feature

- ~~**`special_requests` se persiste sin pasar por el scrubber**~~ — **decidido por Jose: queda fuera de la frontera de la regla 13**, registrado en D9 con su razonamiento y con lo que la decisión no concede. Se acota a un sync de solo lectura contra una cuenta propia, y **se vuelve bloqueante** en cuanto entre `reservations-webhooks` o `beds24-messaging-adapter`, que añaden una escritura no autenticada desde internet sobre la misma columna.

---

## Anotado para quien toque el andamiaje de tests (no es de este change)

`backend/tests/db_names.py` nombra la base de datos efímera `<db>_test_<pid>` y justifica el
sufijo diciendo que el pid es *«único entre procesos vivos»*. **Entre contenedores no lo es**:
cada `docker compose run` tiene su propio espacio de pids, así que dos ejecuciones concurrentes
de la suite eligen el mismo nombre y se pisan el `create_all`/`drop_all` mutuamente. Se manifiesta
como tests flaky sin relación con lo que se está tocando — durante esta revisión costó una
ejecución y un rato de sospechar del código correcto. `PYTEST_DB_SUFFIX` ya existe para fijarlo.
