# BLOCKED — demo-user

Cola de lo que queda sin resolver. `/sdd:status` la muestra primero y `/sdd:archive` se niega a
cerrar el change mientras tenga entradas. Resolver una es borrarla; cuando quede vacío, borrar el
fichero.

---

## 1. La verificación del riesgo de cabecera del design necesita OCI (tarea 8.3)

- **Fase**: run
- **Tipo**: `decision` — necesita a una persona, y **no se puede hacer todavía**.
- **CUÁNDO: después de mergear, no ahora.** Dos razones independientes y las dos duras:
  1. `infra-dev.yml` acota `plan` **y** `apply` a `refs/heads/main`
     (`github.ref == 'refs/heads/main'`), y su propio comentario dice por qué no es un descuido:
     ese job recibe `CLOUDFLARE_API_TOKEN`, que controla el DNS y el TLS de **toda** la zona
     `digitalsec.work`, y un `workflow_dispatch` sobre una rama cualquiera ejecutaría la definición
     del workflow **de esa rama** con el secret en su entorno — `sensitive = true` no impide
     desredactarlo desde código sin revisar. Su conclusión textual: «no se puede planificar desde
     una rama de feature; el plan de un change se ejecuta tras mergear a `main`».
  2. Antes del `apply` el secreto **no existe**, así que un `plan` mostraría una *creación* y no
     diría nada sobre si `ignore_changes` aguanta sobre un recurso ya creado. La comprobación sólo
     significa algo cuando hay un recurso con el valor definitivo dentro.

  **Secuencia** (10 y 11 ya cerradas): `/sdd:review` → `/sdd:ship` → merge → `apply` (el secreto nace
  con el valor de `random_password`, inerte a propósito) → fijar el valor out-of-band → `plan` para
  verificar → **sólo entonces** publicar las credenciales. Eso deja 8.3 en la ventana entre el
  merge y `/sdd:archive`, que es exactamente donde tiene que estar.

  **Hecho ya, y por eso esto es lo único que queda de la sección 11**: la verificación local (11.4)
  no necesitaba el Vault —toma `DEMO_ACCOUNT_PASSWORD` del `.env` local— y se cerró el 2026-08-24
  con las dos ejecuciones, la convergencia probada con el 401 del visitante delante y el tenant de
  trabajo idéntico. Lo que sigue pendiente aquí es **sólo** el `plan` contra OCI.
- **Qué y por qué**: `oci_vault_secret.demo_account_password` lleva
  `lifecycle { ignore_changes = [secret_content] }`, y **todo el diseño de la contraseña depende de
  que el provider de OCI lo respete**. Si no lo respeta, cada `terraform apply` devuelve el secreto
  al valor de `random_password`, el reset siguiente lo propaga a las cuatro cuentas y las
  credenciales publicadas dejan de funcionar **en silencio**, sin que nada se ponga en rojo.

  Hay que comprobarlo **con el valor definitivo ya puesto out-of-band y antes de publicar las
  credenciales a nadie**:

  1. Poner el valor (forma acordada en el gate de `/sdd:design`: frase corta y dictable, ~15
     caracteres con guiones, **por encima de `PASSWORD_MIN_LENGTH` = 12**):

     ```bash
     oci vault secret list --compartment-id <compartment-ocid> --auth instance_principal \
       --query "data[?\"secret-name\"=='autohostai-dev-demo-account-password'].id | [0]" --raw-output

     oci vault secret update-base64 --secret-id <ocid> \
       --secret-content-content "$(printf '%s' 'tu-frase-con-guiones' | base64)"
     ```

     `printf` y no `echo`: `echo` añade un salto de línea que se codifica dentro de la contraseña y
     produce una credencial que no coincide con lo que se escribió.

  2. `cd infra/environments/dev && terraform plan`
     - **No propone cambios en `demo_account_password`** → `ignore_changes` aguanta. Marcar 8.3 y
       borrar esta entrada.
     - **Propone reescribir `secret_content`** → no aplicar. La salida está escrita en Risks: la
       contraseña publicada pasa a ser la que genera `random_password` (leída del Vault) y la
       rotación es `terraform apply -replace`. Hay que **corregir `docs/demo-tenant.md`** (tarea
       10.1) para que documente ese procedimiento y no el otro.
- **Comando para reanudar**: `/sdd:run demo-user 8`

---

## 2. Dos secciones sin panel de revisión completo

- **Fase**: run
- **Tipo**: `deferred` — lo cubre `/sdd:review` a escala de feature, que es su trabajo.
- **Qué y por qué**:
  - **Sección 5**: agotó sus dos rondas de arreglos (el máximo que fija el skill). Los arreglos de
    la **ronda 2** —resolver el almacén antes de bootstrap, las fases `prepare`/`scope`, converger
    `country`, la nota que ya no miente— quedaron **sin revisar**. Cada ronda de esta sección
    encontró defectos reales en los arreglos de la anterior, así que el riesgo residual no es
    teórico.
  - **Sección 9**: el workflow programado se implementó **sin lanzar panel**. Lo que más conviene
    que alguien mire: la costura CLI↔workflow (el enlace del portal llega al resumen del job por un
    `grep` de stdout, y sólo la sostiene la constante `PORTAL_LINE_PREFIX` y su test), y que
    `sdd-review-cicd` lea el fichero contra las reglas de `specs/app-deploy-dev.md`.
- **Comando para reanudar**: `/sdd:review demo-user`

---

## 3. Nada está commiteado

- **Fase**: run
- **Tipo**: `deferred`
- **Qué y por qué**: el change entero vive en el árbol de trabajo (13 ficheros modificados y 2
  nuevos). Es lo normal al salir de `run`, pero **la implementación tiene que estar commiteada
  antes de `mark-ready`**: ese paso graba `implementation_sha` como evidencia para la puerta de
  merge, y un commit no puede contener su propio SHA. Orden: commitear la implementación →
  `/sdd:review` → `mark-ready` → `/sdd:ship`.
- **Comando para reanudar**: `/sdd:review demo-user`
