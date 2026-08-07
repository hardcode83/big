# Blocked — pms-beds24-adapter

**Vacío.** Todas las entradas quedaron resueltas el 2026-08-06.

---

## Resueltas

### El 2026-08-06, con la credencial ya disponible

- ~~**Ejecuciones del banco contra la cuenta**~~ — hechas. `modifiedFrom` existe, restringe de verdad y acepta las dos ortografías; el listado por defecto **oculta las canceladas** e `includeCancelled` se ignora en silencio; el vocabulario de `status` está validado en servidor y hay que enviarlo en parámetros repetidos.
- ~~**El «coste de un ciclo» deja de ser 8 créditos**~~ — decidido: se republica a **10 créditos / 30 s**. El argumento de la regla 9 del steering aguanta igual (~2.880 filas/día frente a ~3.600). La propagación a `specs/pms-beds24-spike.md` y a la cita de la regla 9 va al archivar.
- ~~**Dónde excluir los bloqueos de calendario (D10)**~~ — resuelto a favor de la rama preferida: como hay que enumerar `status` de todas formas para ver las canceladas, dejar `black` fuera sale gratis.
- ~~**Fixtures de reserva modificada y cancelada**~~ — capturados y commiteados.

### El 2026-08-06, al cerrar el flujo

- ~~**Verificación manual end-to-end (7.3)**~~ — hecha. La premisa de que hacía falta `make bootstrap` era falsa: `pms_sync` no toca autenticación. Sync real contra la cuenta: `created 4`, las cuatro `CANCELLED`, una fila de auditoría por ejecución, segundo sync idempotente.

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
