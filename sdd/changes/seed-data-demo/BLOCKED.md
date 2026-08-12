# BLOCKED: seed-data-demo

Cola abierta por `/sdd:review` el 2026-08-12, tras dos rondas de arreglo y una re-revisión
por panel de cada arreglo. El código está sano y la suite en verde (6143 passed, 35 skipped;
el comando verificado contra el stack real, idempotente y con las fechas sin mover). Lo que
queda abierto **no es código**: son dos criterios de aceptación que contradicen a sabiendas
lo que el código hace, una decisión estructural, y tres notas de alcance ajeno.

**Por eso este change NO está marcado `LOCAL_VERIFIED`.** R3.1 y R4.6 siguen «parcialmente
cumplidos» contra su propia letra, y certificar «requisitos cumplidos» mientras el registro de
aceptación dice otra cosa es exactamente lo que la evidencia del gate no debe hacer. La
implementación sí está commiteada, así que hay un SHA que certificar en cuanto se cierren las
entradas 1 y 2.

Arreglado y re-revisado en esta sesión (no vuelve aquí): el orden de la negativa de R3.6, el
ancla de fechas en la zona del tenant, el mensaje de `SeedIngestError` sin motivos, las cuatro
afirmaciones falsas sobre mecanismos (`repositories.py`, `db.py` ×2, `config.py`, más la frase
autodesmentida de `docs/seed-demo.md`), y cuatro huecos de fuerza de test — incluido un defecto
propio: `_row_counts` comparaba un recuento global pre-bind con uno scopeado post-bind, y al
pasarlo a SQL crudo se volvió ciego a las filas pendientes sin flush.

---

## 1. R3.1 y R4.6: dos criterios que el código contradice a sabiendas, sin enmendar

- **phase**: review
- **type**: decision
- **what & why**: el precedente existe y no se aplicó de forma consistente — **R4.5 sí se
  enmendó** el 2026-08-12, con su nota fechada en `proposal.md`, cuando surgió esta misma
  situación. Estos dos no:
  - **R3.1** pide «cuatro cuentas en el tenant **con los correos de PRD §27**». El comando
    resuelve owner y manager **por rol** (`seed_demo.py:300-322`) y toma las otras dos
    direcciones de `SEED_*_EMAIL`. La divergencia es deliberada y bien argumentada (D4,
    `README.md:132-135`, `docs/seed-demo.md:37-48`): buscar por los correos de §27 crearía una
    quinta cuenta y un segundo `TENANT_OWNER` en cuanto el `.env` dijera otra cosa. Pero el
    criterio sigue pidiendo algo que el código no hace, y con un `.env` que diga
    `boss@acme.com` no existe ningún `owner@adamar.test`.
  - **R4.6** pide no duplicar «para esa propiedad y esas fechas». La clave real es de identidad
    (`SEED-DIRECT-1` / `SEED-AIRBNB-1` / `SEED-BOOKING-1`, `seed_demo.py:589-615`, `:645`),
    aceptado por D9 porque las fechas se mueven y esa clave duplicaría cada día. Una estancia
    DIRECT creada a mano en REDES11 con esas fechas y sin `external_channel_id` **sí** produce
    una segunda reserva, que es lo que la letra prohíbe. La consecuencia aceptada no tiene test
    que la fije (el de `test_seed_demo.py:810` cubre el huésped duplicado, no éste).
- **resume**: enmendar R3.1 y R4.6 en `proposal.md` al estilo fechado de R4.5, y después
  `/sdd:review seed-data-demo`

## 2. La decisión estructural: el invariante «leer antes de cualquier bind» no tiene hogar ejecutable

- **phase**: review
- **type**: decision
- **what & why**: cuatro de los doce hallazgos del panel fueron la misma especie — prosa que
  describe un mecanismo que no es el que opera — y la estrategia de documentación de este
  change es precisamente «reformular el invariante como propiedad duradera en un docstring». El
  docstring de `find_by_email_globally` **narra él mismo haber quedado obsoleto dos veces**,
  concluye que «a list nobody can be made to update is worse than no list», y estrenó dos
  afirmaciones falsas nuevas que este review tuvo que corregir. La corrección de esta sesión
  deja el texto verdadero **hoy**; no cambia que el invariante sólo vive en prosa que hay que
  mantener a mano en varios sitios (ver entrada 3: el mismo enunciado está replicado en cuatro
  ficheros). Otra ronda de reescritura no arregla eso.
  Opciones que el panel dejó sobre la mesa: un `assert` en `find_by_email_globally` que rechace
  una sesión ya marcada (convierte la condición en un fallo en rojo en vez de un párrafo), o un
  test que enumere los llamantes. Es alcance propio, no de este change.
- **resume**: decidir el enfoque y abrir entrada de roadmap; `/sdd:review seed-data-demo` no
  depende de esto

## 3. El mismo enunciado falso sobrevive en dos ficheros de `cleaning`, fuera de alcance

- **phase**: review
- **type**: deferred
- **what & why**: `backend/app/cleaning/api/dependencies.py:260` y
  `backend/app/cleaning/infrastructure/repositories.py:534` afirman los dos que
  `get_authenticated_request` es «the only place that marks» — el mismo atajo que
  `db.py:82-86` y `repositories.py:118-128` se reescribieron en esta sesión para refutar
  (`SessionTenantBinder` marca la sesión de la request en las rutas anónimas del portal, y cada
  comando CLI marca la suya). **No se tocaron a propósito**: están en un módulo que este change
  no toca, y editarlos sería alcance colado en un change que el panel acaba de certificar como
  libre de scope creep. Ningún defecto funcional hoy: los dos routes siguen correctamente
  cableados a sesiones que nunca se marcan.
  Los dos revisores discreparon y las dos posturas quedan escritas. **Seguridad**: dejarlos es
  correcto, porque ambos docstrings remiten explícitamente al de `db.py` como autoridad
  («limit 2 of that docstring»), así que la flecha de la cita apunta de la afirmación a la
  refutación. **Tenancy**: la divergencia sí engaña, porque quien consulte
  `dependencies.py:260` directamente readquiere la creencia refutada, que es justo el modo de
  fallo que la reescritura existía para cerrar en todo el sistema y no sólo para el seed.
  Ambos coincidieron en que dejarlo **sin registrar** era lo único inaceptable — es el mismo
  fallo que el recuento obsoleto que `repositories.py` documenta.
- **resume**: entrada de roadmap junto a la entrada 2 (es la misma decisión vista desde el otro
  extremo), o un cambio de `cleaning` que reemplace los dos enunciados por una remisión

## 4. Dos notas de comportamiento acotado, deliberadamente sin arreglar

- **phase**: review
- **type**: deferred
- **what & why**: las dos las levantó el panel de QA en la re-revisión y las dos las clasificó
  él mismo como notas, no como defectos. Se dejan por el límite de dos rondas de arreglo:
  - `seed_demo.py:411` — un `tenants.timezone` no parseable haría que `ZoneInfo` levantara
    `ZoneInfoNotFoundError`, que el catch-all de `main()` convierte en exit 2 con la clase y
    «details withheld», sin frase que explique nada. **No escribe nada** (ocurre antes del bind
    y antes de la primera escritura), así que R1.3 no corre riesgo. Inalcanzable por el camino
    documentado: `bootstrap.py` nunca fija `timezone` y la columna toma el default
    `Europe/Madrid` (`tenants/infrastructure/models.py:17-19`). Arreglo si se quiere: validar
    la zona en `build_plan` y sumarla al contrato de exit 1.
  - `seed_demo.py:734-741` — la rama del mensaje de `SeedIngestError` para `errors` vacío
    (`skipped > 0` sin `RowError`) **no tiene test**. No responde a ningún R#, y el código la
    documenta como inalcanzable mientras el pre-filtro de `:645` se mantenga. Probe que la
    cubriría: un `ingest` monkeypatcheado que devuelva `skipped=1, errors=()`.
- **resume**: `/sdd:review seed-data-demo`
