# Tasks: pms-provider-decision

<!-- Change retrospectivo: la investigación y la escritura ya ocurrieron antes de
     registrarse en el flujo. Las tareas pre-marcadas [x] se verificaron una a una
     contra el árbol de trabajo (grep/git), no de memoria. -->

## 1. Registro de la decisión

- [x] 1.1 Crear `docs/adr/0006-pms-channel-manager-provider.md` con las cinco secciones canónicas de los ADR 0001-0005 — Estado, Contexto, Decisión, Consecuencias, Alternativas rechazadas [R1] *(preexistente — verificado: las 5 secciones presentes)*
- [x] 1.2 Documentar en Contexto la comparativa de proveedores con coste a 2/10/50/200 unidades, cobertura de mensajería API y disponibilidad de sandbox por proveedor [R1] *(preexistente — tabla presente)*
- [x] 1.3 Nombrar el proveedor del MVP (Beds24) y el de fase SaaS (Channex) con el umbral de migración, en la sección Decisión [R1] *(preexistente)*
- [x] 1.4 Registrar cada alternativa rechazada con su razón objetiva y la cita textual de la fuente que la descarta [R1] *(preexistente — diez alternativas)*
- [x] 1.5 Documentar en Consecuencias las limitaciones asumidas del proveedor elegido, no solo sus ventajas, más la sección "Qué revertiría esta decisión" [R1] *(preexistente)*
- [x] 1.6 Identificar en el ADR cada sección del PRD de la que la decisión se aparta, y declarar en Estado la elección de no editarlo citando la convención de ADR 0005 [R1, R5] *(preexistente — §3.3, §5.4, §5.5, §13, §15, §16, §17, §22, §29 citadas)*
- [x] 1.7 Añadir al Contexto el aviso de higiene de fuentes sobre los datos de precio fabricados que circulan para estos proveedores [R1] *(preexistente)*

## 2. Coherencia del steering

- [x] 2.1 `sdd/steering/product.md` — sustituir la lista de candidatos por el proveedor elegido, con enlace al ADR [R2] *(preexistente — verificado: 0 menciones a Smoobu, enlace resuelve)*
- [x] 2.2 `sdd/steering/architecture.md` — reformular la entrada de GrinPass de decisión firme a decisión abierta, con enlace al ADR [R2] *(preexistente)*
- [x] 2.3 `sdd/steering/architecture.md` — conservar intactas las restricciones vigentes de PRD §5.6 en esa misma entrada: `OCCUPIED_ESTIMATED` sin sensor de puerta y nada puede requerir `DOOR_OPENED` [R2] *(preexistente — ambas presentes)*
- [x] 2.4 `sdd/steering/backend-architecture.md` — cambiar el ejemplo canónico de Open/Closed al adapter del proveedor elegido [R2] *(preexistente — 0 menciones a `OctorateAdapter`)*
- [x] 2.5 `sdd/steering/backend-architecture.md` — enlazar en la regla de Liskov el caso real que la motiva: la separación de `PMSMessagingPort` [R2] *(preexistente)*

## 3. Roadmap y descubribilidad

- [x] 3.1 Eliminar la entrada `access-notifications` duplicada, conservando la variante que arrastra la obligación de la regla 11 de `steering/security.md` [R3] *(preexistente — verificado: aparece una sola vez)*
- [x] 3.2 Registrar `pms-beds24-spike` antes de `celery-jobs`, justificando por qué la medición precede al diseño del scheduler [R3] *(preexistente — línea 35, antes de celery-jobs en 36)*
- [x] 3.3 Registrar `pms-beds24-adapter` antes de `messaging-ai` [R3] *(preexistente — línea 41, antes de messaging-ai en 42)*
- [x] 3.4 Registrar la entrada de este propio change con su anotación `→ changes/pms-provider-decision/` [R3] *(preexistente — línea 34)*
- [x] 3.5 Incluir en las tres entradas nuevas la nota de procedencia con el estilo del roadmap [R3] *(preexistente — verificado en las 3)*
- [x] 3.6 `docs/README.md` — describir el directorio `adr/`, su convención de nombrado y la regla de no editar el PRD [R4] *(preexistente)*

## 4. Verificación <!-- panel: omitido — sección sin código de producción (solo documentación y config); ver nota abajo -->

<!-- Este change no introduce código: no toca backend/, frontend/ ni infra/, así que
     no le aplican las suites de `steering/testing.md` ni los comandos de test de
     project.md. Lo verificable aquí es la consistencia documental y del estado SDD. -->

- [x] 4.1 Excluir del commit el artefacto `docs/adr/0006-pms-channel-manager-provider.html`, generado por un visor al abrir el `.md` y ajeno al change — borrarlo o cubrirlo con un patrón en `.gitignore`, decidiendo cuál según si se espera que vuelva a aparecer *(ambas: borrado, y `docs/adr/*.html` añadido a `.gitignore` porque el export se repetirá cada vez que se abra el preview; verificado con un fichero sonda)*
- [x] 4.2 Confirmar que `docs/AutoHostAI_PRD_v5_Claude.md` no aparece modificado: `git status --short docs/AutoHostAI_PRD_v5_Claude.md` debe salir vacío [R5] *(salida vacía)*
- [x] 4.3 Comprobar que los tres enlaces relativos al ADR desde `sdd/steering/` resuelven a un fichero existente [R2, R4] *(los 3 resuelven; verificado también el enlace interno ADR 0006 → 0005)*
- [x] 4.4 Estado SDD consistente: `/sdd:doctor` sin hallazgos nuevos atribuibles a este change (roadmap, `STATE.md`, referencias locales) *(0 errores, exit 0. El único warning —SDD008 en `specs/local-environment.md:20`, referencia a `node_modules/.lock-hash`— es preexistente y ajeno: ese spec se archivó el 2026-07-15 y no está en el diff)*
- [x] 4.5 Repaso final del diff completo (`git diff` + ficheros sin trackear) confirmando que solo contiene documentos de decisión y gobierno, y ni una línea de `backend/`, `frontend/` o `infra/` *(6 ficheros tracked, +12/-5; cero rutas bajo `backend/`, `frontend/` o `infra/`; barrido de patrones `clave=valor` de secretos sin resultados — regla 8 de `steering/security.md`)*

## 5. Correcciones del panel de `/sdd:review`

<!-- Ronda 1 de 2. Hallazgos de sdd-architect (3), sdd-security (5) y sdd-review-tenancy (1),
     deduplicados a 8. Ninguno es un requisito incumplido —los 18 criterios EARS ya estaban
     cumplidos— sino cobertura que el proposal no pidió y el panel considera necesaria. -->

- [x] 5.1 ADR decisión 7 — corregir la cita: las credenciales en base de datos las gobierna la **regla 3** (cifrado en reposo), no la 8, cuyo ámbito es el repositorio; y aclarar que la línea 838 del PRD habla de códigos de acceso, no de un contrato general [R1, R2] *(security F2 + architect F1)*
- [x] 5.2 `steering/security.md` regla 3 — ampliar la enumeración a credenciales de proveedor externo por propiedad, con sus tres obligaciones propias: solo escritura, `AuditLog` de lectura/rotación, y test de aislamiento propio [R2] *(security F2 + F3)*
- [x] 5.3 `steering/security.md` regla 8 — acotar la mención de credenciales de PMS al `PMS_API_KEY` de bootstrap/mock, remitiendo el resto a la regla 3 [R2] *(architect F1)*
- [x] 5.4 `steering/security.md` — añadir la **regla 12** para webhooks entrantes sin firma, y actualizar el trigger que la condicionaba a un "cuando el provider lo soporte" hoy siempre falso [R2] *(security F1)*
- [x] 5.5 ADR Consecuencias — expandir el bullet de credenciales con las cinco obligaciones (cifrado, aislamiento, no serialización, auditoría, marcado de sesión) y separar el acoplamiento de radio de daño de la clave Fernet única [R1] *(security F3 + tenancy F1)*
- [x] 5.6 ADR decisión 5 vía 2 — advertir que devolver el PIN a la reserva lo hace volver en payloads y aterrizar en claro en `webhook_events.payload`, contra las reglas 3, 4 y 11; exigir eliminarlo en la ingesta [R1] *(security F4)*
- [x] 5.7 ADR decisión 4 — registrar que Chekin es un nuevo sub-encargado de PII, difiriendo DPA y retención a `access-notifications` [R1] *(security F5)*
- [x] 5.8 ADR decisión 7 — dejar explícito que la composición con la decisión 3 (cómo resuelve la factory el `PMSMessagingPort` por propiedad, y el caso sin mensajería) es decisión abierta de `pms-beds24-adapter` [R1] *(architect F3)*
- [x] 5.9 Roadmap `pms-beds24-adapter` — arrastrar las cinco obligaciones heredadas más la decisión de diseño abierta [R3] *(tenancy F1 + security F3)*
- [x] 5.10 Roadmap `reservations-webhooks` — arrastrar la regla 12, explicando por qué su enunciado original quedó inerte [R3] *(security F1)*
- [x] 5.11 `docs/reservations.md:97` — retirar Smoobu, nombrar Beds24 con enlace al ADR [R2] *(architect F2)*
- [x] 5.12 `proposal.md` — declarar los ficheros que el change toca, incluido `.gitignore` [R1] *(qa, informativo)*
- [x] 5.13 Verificar por grep que ninguna redacción superada sobrevive en otro artefacto *(0 ocurrencias de las cuatro; reglas de `security.md` numeradas 1-12 sin hueco; ningún "Smoobu" fuera del PRD y del propio ADR)*

## 6. Correcciones del panel — ronda 2 (última)

<!-- 1 hallazgo residual de sdd-architect y 5 de sdd-security, de los cuales TRES son costuras
     que abrieron los arreglos de la ronda 1. Patrón de fondo, anotado a propósito: cada
     obligación vive en tres artefactos (ADR, steering/security.md, entrada de roadmap) y en
     cada ronda se escapó uno. Se cierra con una comprobación explícita de los tres portadores
     por obligación, no releyendo el pasaje recién escrito. -->

- [x] 6.1 Roadmap `pms-beds24-adapter` — la entrada citaba **regla 8** y **regla 3** para el mismo hecho en el mismo párrafo; queda la 3 con la aclaración contrastiva [R2, R3] *(architect re-review)*
- [x] 6.2 ADR — residuo de tiempo verbal: decía que `security.md` "sigue listando" credenciales de PMS, cierto al escribirlo y falso tras el arreglo; reescrito en pasado [R1] *(detectado en el barrido propio)*
- [x] 6.3 `security.md` regla 3 — acotar la regla 8 dejó sin cubrir las credenciales de **cuenta y organización** (*merchant key* de Beds24, token de organización, refresh tokens), que ni eran el `PMS_API_KEY` de bootstrap ni eran por propiedad; la regla 3 pasa a cubrir las tres granularidades, señalando que las de cuenta son las más peligrosas [R2] *(security F2-nuevo)*
- [x] 6.4 `security.md` regla 12(a) — el secreto de cabecera que la regla exige no tenía regla de almacenamiento; ahora remite a la regla 3, exige valor distinto por tenant (nunca constante global) y comparación en tiempo constante [R2] *(security F3-nuevo)*
- [x] 6.5 ADR + roadmap `reservations-webhooks` — registrar la **cuarta desviación del PRD**: §23 define `POST /api/v1/webhooks/{provider}`, globalmente adivinable, contra la regla 12(b); la forma pasa a llevar un segmento token opaco por tenant. `specs/reservations.md` documenta la forma del PRD y se corrige al archivar esa entrada, que es su dueña [R1, R3] *(security F4-nuevo)*
- [x] 6.6 Roadmap `access-notifications` — arrastrar la obligación de Chekin como sub-encargado de PII (DPA, retención, salida de `document_number` y fecha de nacimiento); estaba solo en el ADR, asimétrico con los otros dos arrastres [R3] *(security F5 residual)*
- [x] 6.7 ADR — las dos citas a `security.md:49` apuntaban a una línea que quedó en blanco al insertar la regla 12; pasan a citar la sección §"Triggers de revisión extra" [R1] *(security F5-nuevo)*
- [x] 6.8 ADR + roadmap — propagar la granularidad de cuenta/organización a los otros dos portadores, no solo a la regla [R1, R3] *(comprobación de los tres portadores)*
- [x] 6.9 Verificación cruzada: matriz obligación × portador (ADR / `security.md` / roadmap) con las cinco obligaciones presentes en los tres; cero ocurrencias de las tres redacciones superadas; reglas numeradas 1-12 sin hueco

## 7. Cierre tras agotar las rondas de panel <!-- panel: NO EJECUTADO — las 2 rondas permitidas se agotaron; estas ediciones no llevan veredicto de revisores -->

<!-- Las dos rondas de arreglo que permite el flujo están gastadas. sdd-architect declaró
     bloqueante uno de estos puntos y sdd-security lo encontró por su cuenta, así que se
     aplican por ser errores objetivos introducidos en la ronda 2, no hallazgos discutibles.
     DELIBERADAMENTE NO se lanza un tercer panel: lo que queda es decisión del owner. -->

- [x] 7.1 `roadmap.md:34` — decía "**Tres** desviaciones del PRD" cuando el ADR enumera cuatro; corregido y nombrada la de §23. **Los dos revisores lo encontraron por separado** [R1, R3]
- [x] 7.2 `roadmap.md:41` — la obligación 3 citaba "contrato de solo escritura (**regla 4**)", que la ronda 1 movió a la regla 3(a); corregido con la aclaración de qué contiene la regla 4 [R2, R3]
- [x] 7.3 `security.md` regla 3 — "Estas últimas" creaba un antecedente más cercano que el pretendido, permitiendo leer que las credenciales por propiedad solo llevan cifrado; sustituido por un sujeto inequívoco [R2]
- [x] 7.4 `security.md` regla 3(a) — la prohibición de serializar impedía la **única vía de aprovisionamiento** del secreto que exige la regla 12(a), que un operador tiene que copiar al panel del proveedor; añadida excepción acotada: se devuelve una vez al generarlo y en cada rotación, nunca en lectura posterior, y solo para secretos que generamos nosotros [R2]
- [x] 7.5 `security.md` regla 12 — se describía a sí misma como de proveedores PMS, dejando sin portador los webhooks de Chekin (`PoliceRegistration.*`); ahora declara aplicar a cualquier webhook entrante sin firma y la heredan dos entradas [R2]
- [x] 7.6 Roadmap `access-notifications` — arrastrar la regla 12 junto a la obligación de DPA ya presente [R3]
- [x] 7.7 ADR decisión 5 vía 2 — "se elimina en la ingesta" llegaba tarde: la arquitectura de la regla 12 persiste el payload crudo con `processed=FALSE` **antes** de procesarlo, así que el PIN ya estaría en la columna que la regla 11 exige limpia. Reformulado a redacción **en recepción**, antes de escribir `webhook_events` [R1]
- [x] 7.8 Verificación: las cuatro redacciones erróneas a 0 ocurrencias; las cuatro desviaciones coherentes en ADR Estado, ADR Consecuencias y las dos entradas de roadmap; reglas 1-12 sin hueco; `/sdd:doctor` 0 errores

<!-- Cobertura de requisitos:
     R1 → 1.1-1.7 · R2 → 2.1-2.5, 4.3 · R3 → 3.1-3.5
     R4 → 3.6, 4.3 · R5 → 1.6, 4.2 -->
