# BLOCKED — properties-crud

## B1 — El panel de las secciones 5, 6 y 7 no llegó a emitir veredicto

- **phase**: run
- **type**: deferred

**Qué y por qué.** Se lanzaron cuatro revisores en paralelo sobre el diff de `8f98ba5`
(`git diff aaad941..8f98ba5`): arquitectura, seguridad, QA y tenancy. **Los cuatro murieron por
límite de sesión de la API** antes de emitir hallazgos. No hay veredicto: **esto no es un PASS
silencioso**, y ninguna sección lleva anotación `panel:`.

El de arquitectura alcanzó a confirmar una sola cosa antes de caer, y conviene no repetirla: el
precedente de `auth` que justifica partir `use_cases.py` / `property_admin.py` **es real**.

**Lo que sí está verificado**, para que quien lo retome no lo rehaga:

- Suite completa **3511 passed, 35 skipped, 0 failed**; `alembic check` limpio; migración
  reversible hasta `base` y de vuelta.
- **Recorrido manual de extremo a extremo contra el stack real** (tarea 10.4): login → `POST
  /properties` `201` → `POST /reservations` sobre ella **`201`**, donde antes había `404` en toda
  petición. Más: la reserva sobre una propiedad retirada da `409 CONFLICT`, el alta como
  `TENANT_OWNER` da `403` y su listado `200`.
- **Comprobado a mano y no por confianza en quien lo implementó**: lo almacenado en
  `wifi_password_encrypted` es ciphertext Fernet real (100 chars, prefijo `gAAAA`), el cuerpo del
  `GET` no contiene el valor ni el campo, y ni `wifi_password_encrypted` ni `secret_encrypted` ni
  ruta de credenciales alguna aparecen en `backend/openapi.json`.

**Lo que ese panel habría mirado y nadie ha mirado.** Es lo que hay que exigirle al que se
reanude, porque `steering/security.md:92` dispara aquí su trigger de revisión extra **dos veces**:

1. Si el secreto puede salir por una vía que no se haya probado — cuerpo de error, mensaje de
   validación, log. El esquema de respuesta y el contrato **sí** están comprobados.
2. Si el aislamiento por tenant está probado **por rol y con el tenant B realmente sembrado**, y
   si la autorización se decide **antes** de leer el recurso.
3. Si hay aserciones vacuas. Quien implementó reportó haber escrito un `assert ... or True` y
   haberlo cazado antes de correr; nadie ha barrido el resto en busca de la misma forma.
4. Si `app/audit/domain/value_objects.py` —módulo que este change **no posee**— quedó tocado de
   forma mínima y justificada. Ahí se arregló un bug real: `_storable` no cubría `time`, así que
   un `PATCH` de `default_check_in_time` salía como **500**.
5. Si `has_wifi_password` en la entidad es coherente con D2 o es una grieta en ella.

**Comando de reanudación**: `/sdd:review properties-crud` — cubre el change a escala de feature,
que es la forma prescrita de recuperar un panel de sección interrumpido, y ahora además puede
incluir al revisor de documentación (ver B2).

## B2 — RESUELTA: el revisor de documentación ya puede correr

**Resuelta el 2026-08-08** al cerrar la sección 9. Se había aplazado a propósito porque
`sdd-review-documentation` verifica `.env.example`, el README raíz, `docs/<capability>.md` y el
contrato regenerado — exactamente lo que esa sección entrega. Ya están: `openapi.json` y los tipos
del frontend regenerados, `README.md` corregido (afirmaba que `properties` no tenía capa `api/`) y
`docs/properties.md` creada. Entra en el panel de `/sdd:review`.
