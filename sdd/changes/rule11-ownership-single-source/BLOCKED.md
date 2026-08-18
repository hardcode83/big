# BLOCKED: rule11-ownership-single-source

Review de 2026-08-18 cerró en **FAIL** tras dos rondas de arreglo. El anchor revisado es
`775ae12` (suite completa medida ahí: **7349 pasados, 39 saltados, 0 fallos**). Las tres
entradas de abajo son **la misma raíz** y se cierran de una vez; están separadas porque
tocan artefactos distintos.

`STATE.md` sigue en `ACTIVE`: no se ejecutó `mark-local-verified` ni `mark-ready`.

---

## 1. La afirmación «el censo = la clase 1» es falsa por un elemento

- **phase**: review
- **type**: `deferred`
- **qué y por qué**: R6.1 declara «las cuatro lecturas no scoped del sistema». Son
  **cinco** en esa clase: `find_by_token_hash`
  (`app/integrations/infrastructure/repositories.py:200`) resuelve el tenant a partir de la
  fila igual que las otras cuatro, y no llama al guard. D9 lo reconoce («una omisión genuina
  de la clase 1»), pero dos sitios afirman que el censo cubre la clase entera:
  - `backend/app/auth/domain/ports.py:9-12` — acota sólo contra la clase 2, así que quien lee
    concluye que la clase 1 está cubierta.
  - `sdd/specs/auth-tenancy.md:44-48` — **enumera** el conjunto de fuera como si fueran sólo
    los drenajes de cola, excluyendo `find_by_token_hash`. Contradice directamente
    `backend/app/core/db.py:208-220`, que lo llama «the SAME class as the four… a genuine
    omission».

  Los otros seis sitios acotados añaden «which also names the reads it does not cover», así
  que quien sigue el puntero llega a la verdad. Esos dos no.
- **resume**: `/sdd:review rule11-ownership-single-source`

## 2. El recuento «eran cuatro» quedó obsoleto en dos specs

- **phase**: review
- **type**: `deferred`
- **qué y por qué**: `sdd/specs/cleaning.md:306` y `sdd/specs/auth-tenancy.md:47` dicen
  «decía "tres" cuando eran cuatro», afirmando que cuatro era el número real de lecturas no
  scoped. Por el propio recuento de D9 son cinco en la clase 1 más dos en la clase 2. Es
  exactamente la patología de recuento-en-prosa que este change existe para cerrar,
  reintroducida por el arreglo de la ronda 2.
- **resume**: `/sdd:review rule11-ownership-single-source`

## 3. El motivo escrito del aplazamiento de `find_by_token_hash` ya no es cierto

- **phase**: review
- **type**: `deferred`
- **qué y por qué**: la enmienda de D9 aplaza guardar `find_by_token_hash` porque «el demonio
  de Docker estaba caído en esta fase, así que no se pudo demostrar que la suite siga verde».
  Eso era cierto en ese momento y **ya no**: el panel de arquitectura lo midió con el guard
  puesto — `tests/integrations` da **927 pasados, 0 fallos**, porque los trece sitios de test
  invocan el repositorio directamente sobre `db_session` sin capa HTTP, así que la sesión
  nunca estuvo marcada. Sólo enrojecen los dos tests del censo, y eso es su diseño.
  El motivo tiene que decir lo medido, no lo que bloqueó una ronda.
- **resume**: `/sdd:review rule11-ownership-single-source`

---

## Arreglo recomendado (cierra las tres de una pasada)

**Guardar `find_by_token_hash` en vez de documentar su ausencia.** Medido como verde y son
tres líneas:

1. `require_unmarked_session(self._session, read="find_by_token_hash")` como primera sentencia
   de `find_by_token_hash` (`app/integrations/infrastructure/repositories.py`), más su import.
2. Moverlo de `KNOWN_UNGUARDED_UNMARKED_READS` a `DECLARED_UNSCOPED_READS`
   (`backend/tests/test_unscoped_reads.py`) — reclasificación de una línea en cada set, no una
   reescritura de test.
3. Actualizar a **cinco** los recuentos de las entradas 1 y 2, y reescribir la enmienda de D9
   para que registre lo medido.

Por qué esto es mejor que seguir acotando prosa: al guardar la quinta, «el censo es la clase
1» pasa a ser **verdad**, y los sitios de la entrada 1 quedan correctos tal como están escritos
hoy. Las entradas 1 y 2 se evaporan en vez de necesitar un parche de redacción más — que es la
tercera ronda seguida en la que los hallazgos caen en el mismo sitio.

Lo que queda fuera igualmente, y consta: `select_pending` y `lease` son otra clase (drenaje de
cola sobre `tenant_id` nullable) y siguen sin guard, pinadas por
`test_tenant_filter.py::test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session`.

## Estado de los paneles sobre `775ae12`

| Panel | Veredicto | Nota |
|---|---|---|
| arquitectura | PASS | 3 hallazgos de ronda 2 cerrados; revirtió su sonda |
| QA | PASS | suite completa 7349/39/0 verificada dos veces; mutación de los dos guardianes |
| documentación | PASS | enmiendas D6b/D7/D9/D13 verificadas; barrido de numerales |
| cicd | PASS | mounts `:ro`, deploy intacto, CI resuelve la raíz |
| seguridad | FAIL | entradas 1 y 2 de arriba |
| tenancy | — | murió por límite de sesión; hecho en línea por el agente principal |
