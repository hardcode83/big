# BLOCKED — properties-crud

## B1 — El panel de las secciones 5, 6 y 7 no llegó a emitir veredicto

- **phase**: run
- **type**: deferred

**Qué y por qué.** Se lanzaron cuatro revisores en paralelo sobre el diff de `8f98ba5`
(`git diff aaad941..8f98ba5`): arquitectura, seguridad, QA y tenancy. **Los cuatro murieron por
límite de sesión de la API** antes de emitir hallazgos (se restablece a las 04:10, Europe/Madrid).
No hay veredicto: **esto no es un PASS silencioso**, y ninguna sección lleva anotación `panel:`.

El de arquitectura alcanzó a confirmar una sola cosa antes de caer, y conviene no repetirla: el
precedente de `auth` que justifica partir `use_cases.py` / `property_admin.py` **es real**.

**Lo que sí está verificado de esas tres secciones**, para que quien lo retome no lo rehaga:

- Suite completa: **3506 passed, 35 skipped, 1 failed**. El único fallo es
  `tests/test_openapi_contract.py::test_the_committed_contract_matches_the_code`, y es
  **esperado**: `backend/openapi.json` se regenera en la tarea 9.1, que no ha corrido.
- `alembic check` limpio.
- Comprobado a mano, no por confianza en el agente que lo implementó:
  `has_wifi_password` se deriva de `model.wifi_password_encrypted is not None` —una presencia, no
  el valor—, `PropertyResponse` **carece estructuralmente** del campo, y el fix de `time` está en
  `_storable` (`app/audit/domain/value_objects.py:283`).

**Lo que ese panel habría mirado y nadie ha mirado.** Es lo que hay que exigirle al que se
reanude, porque `steering/security.md:92` dispara su trigger de revisión extra **dos veces** aquí
(«endpoints nuevos» y «cambios de auth/RBAC»):

1. Si una contraseña de wifi puede salir por **alguna** vía —cuerpo de error, mensaje de
   validación, log, ejemplo del esquema OpenAPI—, no solo por el esquema de respuesta declarado.
2. Si el aislamiento por tenant está probado **por rol y con el tenant B realmente sembrado**, y
   si la autorización se decide **antes** de leer el recurso.
3. Si hay aserciones vacuas. El propio implementador reportó haber escrito un `assert ... or True`
   y haberlo cazado antes de correr; nadie ha barrido el resto en busca de la misma forma.
4. Si `app/audit/domain/value_objects.py` —módulo que este change **no posee**— quedó tocado de
   forma mínima y justificada.
5. Si `has_wifi_password` en la entidad es coherente con D2 o es una grieta en ella.

**Comando de reanudación**: `/sdd:review properties-crud` — cubre el change a escala de feature,
que es la forma prescrita de recuperar un panel de sección interrumpido.

## B2 — El revisor de documentación se aplazó a propósito

- **phase**: run
- **type**: deferred

No es un fallo: `sdd-review-documentation` verifica `.env.example`, el README raíz,
`docs/<capability>.md` y el contrato regenerado — que es **exactamente lo que entrega la sección
9**, aún sin correr. Lanzarlo antes solo habría reportado trabajo no hecho. Entra en el panel de
`/sdd:review` una vez cerrada esa sección.

**Comando de reanudación**: `/sdd:review properties-crud`

## B3 — Quedan las secciones 8, 9 y 10 sin implementar

- **phase**: run
- **type**: deferred

32 tareas pendientes de 48. El detalle vive en `tasks.md`, que es su único hogar; se anota aquí
solo porque la 8 es la que **cruza a `reservations`**, un change archivado, y quien la retome debe
leer D11 antes de tocarla: la guarda de `status = INACTIVE` tiene que cubrir **las tres vías** de
entrada (API manual, import CSV y `pms_sync`), no solo la primera.

**Comando de reanudación**: `/sdd:run properties-crud 8`
