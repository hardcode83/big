# cleaning-completion-evidence-gatherer

[TECH] **extraer la orquestación de lectura del cierre de limpieza**, que hoy hace de
`CompleteCleaningTaskUseCase` un caso de uso con **11 colaboradores**. Separada de
`cleaning-photos-storage` el 2026-08-09 al cerrar su `/sdd:review` (entrada §6(a) de su
`BLOCKED.md`).

**El recuento, que lo hizo el arquitecto del panel**: `_TaskLifecycleBase` aporta 7 (`tasks`,
`properties`, `transitions`, `timeline`, `reservations`, `audit`, `uow`) y el cierre añade 4 más
(`completions`, `templates`, `photos`, `incidents`). Salió al evaluar **por qué la tarea 5.4 no se
testeó con fakes como pedía**: el implementador justificó la desviación diciendo que no había
precedente de fakes en el repositorio, y eso era **falso** —`test_photo_upload_use_case.py` testea
`UploadCleaningPhotoUseCase` íntegramente con fakes y lo había escrito él mismo—, pero QA afinó mejor:
no existe ningún test con fakes para el camino positivo de **ningún** caso de uso del ciclo de vida
(Accept/Start/Reject/Complete), y el precedente para *cerrar* siempre fue integración vía
`test_tasks_api.py`. La desviación se arbitró como aceptada, porque los tres escenarios estaban
cubiertos y la mutación de QA los demostró no-vacíos; lo que se perdía era aislamiento y velocidad,
no cobertura semántica, y forzar los fakes eran ~150 líneas de maquinaria nueva.

**La lectura del arquitecto es la que importa y no ha caducado**: que un caso de uso **no se pueda
testear con fakes a coste razonable no es una propiedad del dominio, es una señal**. Once
colaboradores es la señal.

**La salida propuesta no toca D8, y esto es lo que hay que entender antes de tocarlo**: D8 de
`cleaning-photos-storage` prohíbe mover la **decisión** fuera de la entidad —las tres cláusulas de
PRD §11 se aplican dentro de `CleaningTask.complete()`, y ahí siguen— pero no prohíbe mover la
**lectura**. Así que la orquestación que reúne la evidencia (plantilla + completions + fotos +
incidencia) puede extraerse a un `CompletionEvidenceGatherer` propio sin romper ninguna invariante:
la entidad seguiría recibiendo un `CleaningCompletionEvidence` ya poblado, exactamente como hoy.
Con eso, los fakes del camino positivo pasan a ser baratos y la desviación de la tarea 5.4 deja de
tener motivo.

completes: cleaning-photos-storage · size: S · kind: tech
