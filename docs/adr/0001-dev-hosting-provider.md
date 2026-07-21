# 0001 — Proveedor de hosting/cloud para el entorno de dev remoto

## Estado

Aceptado — 2026-07-19.

## Contexto

`sdd/steering/infra.md` (change `infra-scaffold`) confirmó Terraform + GitHub Actions como herramientas de despliegue remoto y dejó el proveedor cloud **pendiente de decisión**, con una tabla inicial de solo 4 candidatos (AWS, Google Cloud, Vercel, Railway) sin veredicto. Este ADR cierra esa decisión **solo para el entorno `dev`** (`infra/environments/dev/`) — staging y prod tendrán su propio ADR cuando el negocio lo requiera, sin heredar esta elección.

Stack a desplegar (hoy en `docker-compose.yml` de la raíz del repo): `postgres:16`, `redis:7`, `migrate` (Alembic, job), `backend` (FastAPI), `worker` (Celery), `frontend` (Next.js) — imágenes construidas desde `backend/devops/Dockerfile` y `frontend/devops/Dockerfile`. Producto en fase muy temprana: 2 viviendas turísticas, equipo pequeño, sin tráfico productivo real en dev.

Criterios de decisión (`sdd/changes/dev-hosting-provider/proposal.md`, R2): por encima del coste puro se pondera la madurez del provider oficial de Terraform, el ajuste de migración desde las imágenes Docker actuales, y la compatibilidad con un pipeline de GitHub Actions que ejecute `terraform plan`/`apply` de forma directa (R2.2). Cualquier candidato que exija reescribir la app o que no permita ese pipeline queda excluido como veredicto, aunque siga documentado (R2.4, gate de compatibilidad). El vendor lock-in se usa como desempate entre finalistas (R2.5). Las capas gratuitas se documentan distinguiendo *always-free permanente* de *crédito de prueba con caducidad* (R1.5).

Investigación realizada 2026-07-19 con verificación directa contra `registry.terraform.io`, actividad reciente en GitHub de cada provider, y páginas de precios oficiales — no solo documentación de marketing. Fuentes citadas en cada sección.

## Decisión

**Modelo: VM única + docker-compose. Proveedor: Oracle Cloud Infrastructure, shape Ampere A1 (Always Free).**

`infra/environments/dev/` aprovisiona con Terraform (`oracle/oci`, provider partner-tier, v8.23.0 al 2026-07-19, activamente mantenido) una única VM Ampere A1 dentro del cupo Always Free (2 OCPU / 12 GB tras el recorte de cupo del 15-jun-2026), que ejecuta el mismo `docker-compose.yml` del repo sin modificar su topología. Terraform provisiona red/VCN/security list y la instancia; el despliegue de la app (`docker compose pull && up -d`) se orquesta desde GitHub Actions vía SSH — patrón estándar del modelo VM, no distinto del que tendría cualquier otro candidato de este grupo.

**Por qué gana pese a no ser la opción con el Terraform provider más "oficial" (ese honor es de AWS/GCP, con Lightsail/EC2 como candidatos que sí lo tienen) ni la de mejor arquitectura sin matices (ARM introduce un riesgo real, ver Consecuencias):**

1. **Coste: es el único candidato de los 11 evaluados con coste 0€/mes de forma permanente** para el stack completo (backend+worker+frontend+Postgres+Redis en la misma VM) — no crédito de prueba con caducidad, sino cupo always-free contractual (aunque revisable por Oracle, ver riesgos). El resto de opciones de pago del modelo VM rondan €5,49-30/mes; los modelos PaaS/serverless rondan $35-106/mes en escenarios realistas; Kubernetes gestionado ronda $95-220/mes.
2. **Ajuste de migración: el modelo VM es, en abstracto, el único que reutiliza `docker-compose.yml` tal cual**, sin decomponer en servicios separados (a diferencia de Render/Fargate/Cloud Run) ni reescribir código (a diferencia de Vercel). El caso concreto de Oracle añade un matiz real — arquitectura ARM64 — que se documenta explícitamente como riesgo gestionable, no como equivalencia perfecta con Hetzner/AWS Lightsail/EC2 (que no tienen ese matiz). Se acepta porque las imágenes base del proyecto (`python:3.12-slim`, `node:22-slim`, `postgres:16`, `redis:7`, y el binario de `astral-sh/uv` usado en el Dockerfile de backend) publican manifiestos `linux/arm64` verificados hoy — el trabajo pendiente es validar/añadir build multi-arch en CI antes de escribir el `.tf` real, no resolver una incompatibilidad fundamental.
3. **GitHub Actions/Terraform: pasa el gate sin matices** — provisión de infraestructura 100% vía `terraform plan`/`apply` con provider maduro y activo, igual que el resto del modelo VM.
4. **Vendor lock-in (desempate, R2.5): bajo-medio** — la VM y las imágenes Docker son portables a cualquier otro proveedor sin reescritura; el único lock-in real es que la cuenta Always Free queda atada a la *home region* elegida al crear la tenancy (no cambiable sin borrar y recrear la cuenta) — no afecta a la portabilidad de la infraestructura en sí, solo a la flexibilidad de mover esa cuenta gratuita concreta de región.

No se sacrifica madurez de Terraform (partner tier, activo, cobertura completa de compute/red) ni ajuste de migración (alto, con un riesgo puntual documentado) ni compatibilidad GitHub Actions (total) para conseguir el coste 0€ — es una decisión defendible en los tres criterios de peso alto, no solo barata.

**Sobre el desempate de lock-in (R2.5): no hubo empate exacto que requiriera aplicarlo de forma decisiva.** El coste 0€ permanente de Oracle ya rompe por sí solo cualquier posible equivalencia con Hetzner o AWS Lightsail/EC2 en los tres criterios de peso alto — el lock-in se evaluó y documentó para los 16 candidatos (ver tabla), pero no fue necesario como criterio de desempate porque ningún otro candidato quedó realmente igualado con Oracle antes de mirar el lock-in.

**Respaldo operativo si Oracle deja de ser viable** (ver Consecuencias y Criterio de revisión): **Hetzner Cloud** como fallback primario (más barato, mismo modelo, sin riesgo de arquitectura) y **AWS Lightsail** como fallback secundario (provider Terraform en el tier más maduro posible — el mismo `hashicorp/aws` que EC2/Fargate — sin riesgo ARM, útil si se prefiere consolidar en el ecosistema AWS o priorizar el tier "oficial" por encima del ahorro marginal frente a Hetzner). Razonamiento completo de ambos en "Alternativas consideradas" abajo.

## Red y dimensionamiento (verificado contra documentación oficial de Oracle)

Verificación específica para descartar gastos escondidos de red, más allá del cómputo:

- **Topología**: la VM se crea en una **subred pública** con **1 IP pública incluida** (efímera por defecto). El Always Free también incluye **1 IP pública reservada** (persistente, no cambia al parar/reiniciar la instancia) sin coste — de hecho, **Oracle no cobra por IPs públicas reservadas en absoluto, estén o no asignadas a una instancia**, a diferencia de AWS (~$7,5/mes por una Elastic IP no asociada) o GCP (~$3/mes por una IP externa sin uso). No hace falta Load Balancer ni NAT Gateway para este caso de uso (VM única, tráfico bajo) — evita justo los gastos escondidos (~$18-35/mes) que sí aparecían en los modelos serverless investigados (Fargate/Cloud Run).
- **Ancho de banda**: hasta 50 Mbps por VNIC para tráfico a internet — de sobra para 2 viviendas con tráfico bajo.
- **Egress incluido**: **10 TB/mes** para toda la tenancy (tráfico a IPs privadas en la misma región no cuenta contra la cuota) — a esta escala, prácticamente imposible de agotar con tráfico legítimo.
- **Almacenamiento**: 200 GB de block storage incluidos (boot + block volume combinados) — más que suficiente para los volúmenes de Postgres/Redis a esta escala.
- **Dimensionamiento del stack**: 2 OCPU/12 GB (cuota actual) es suficiente para correr backend+worker Celery+frontend+Postgres+Redis simultáneamente a este tráfico — la comunidad reporta buen rendimiento de Postgres/Redis en Ampere A1, con un reparto conservador razonable (p. ej. 4-6 GB Postgres, 2-4 GB Redis, resto para backend/frontend/worker/SO) dejando margen holgado.
- **Riesgo real sobre el "0€ garantizado" — depende del tipo de tenancy**: en una tenancy **"Always Free" pura** (sin tarjeta de pago añadida), exceder cualquier cuota (cómputo, egress, storage) **suspende la instancia, no genera factura**. En una tenancy que se haya actualizado a **"Pay As You Go"** (p. ej. para desbloquear otros servicios), exceder esas mismas cuotas **sí puede facturarse** — y Oracle ha dado respuestas contradictorias sobre si el recorte de cómputo de jun-2026 aplica igual a cuentas PAYG. Mitigación: mantener la tenancy como Always Free pura mientras sea posible, y en cualquier caso configurar alertas de presupuesto (budget alerts) en la tenancy desde el primer día — se añade como tarea explícita al futuro change que escriba el Terraform real.

## Alternativas consideradas

Cada candidato no ganador, con su motivo de rechazo — ninguno desaparece sin rastro (R1.4).

### Excluidos por el gate de compatibilidad (R2.4)

- **Vercel** — falla por los dos motivos que el gate existe para prevenir: (a) el worker Celery persistente no tiene equivalente viable (Vercel Functions hacen scale-to-zero a los 5 min y tienen `maxDuration` fijo; Celery beat no está soportado por requerir un proceso de larga duración — la propia documentación de Vercel lo admite), forzando una reescritura arquitectónica real, no solo de configuración; (b) su provider de Terraform (`vercel/vercel`, partner tier, muy activo) solo gestiona configuración de proyecto (env vars, dominios, deployments) — no hay recurso para desplegar el backend/worker como infraestructura vía `apply`. Postgres/Redis tampoco son productos propios (van vía Marketplace a Neon/Upstash), cambiando también el proveedor de datos.
- **Fly.io** — falla específicamente por el criterio de Terraform/GitHub Actions: su provider oficial está **archivado desde marzo de 2024**, y Fly.io ha declarado públicamente que la ausencia es intencional (su Machines API es imperativa, no encaja con el modelo declarativo de Terraform). El pipeline real depende de `flyctl`/`superfly/flyctl-actions`, no de `terraform plan`/`apply` contra su infraestructura. Nótese que aquí el Docker fit es, de hecho, el mejor de los PaaS evaluados (Fly Machines son VMs long-running reales, sin problema con el worker) — el descarte es puramente por el criterio de IaC, que el proposal prioriza explícitamente por encima de otros factores.

### Kubernetes gestionado (EKS/GKE) — rechazado para esta fase

Se evaluó formalmente frente a los tres modelos priorizados, no se omitió (R3):

- **Coste**: EKS ~$150-220/mes (control plane $0,10/h sin exención + nodos + ALB/NAT); GKE ~$95-140/mes (control plane exento por el crédito de $74,40/mes de GCP para un cluster zonal, pero cómputo Autopilot/Standard + LB sí se paga). Ambos muy por encima de los ~$0-25/mes del modelo VM o los ~$20-90/mes de PaaS/serverless.
- **Complejidad operativa añadida** (no existe en VM/PaaS/serverless): ingress controller, cert-manager, gestión de nodos o Autopilot/Fargate profiles, autoscaling de cluster, monitorización propia, triple capa de RBAC (IAM + Kubernetes + app), gestión de secretos más allá de `.env`.
- **No es un problema de Terraform** — `hashicorp/aws`, `hashicorp/google`, `hashicorp/kubernetes` y `hashicorp/helm` son providers oficiales excelentes; el motivo de descarte es puramente operativo/de coste a esta escala.
- **Esfuerzo de migración**: traducir el `docker-compose.yml` actual (6 servicios) a manifiestos K8s exige ~18-22 objetos (Deployments, Services, ConfigMaps/Secrets, PVCs, Ingress, cert-manager) y reimplementar a mano la lógica de `depends_on`/healthchecks que Kubernetes no da gratis — estimado en 2-4 días de ingeniería, frente a 0 en el modelo VM.

**Criterio explícito de reconsideración** — Kubernetes vuelve a la mesa si ocurre cualquiera de:
1. El producto entra en su fase SaaS multi-tenant con tracción real (varios clientes gestores, no solo MAGNO) — el punto que el propio PRD marca como salto de complejidad.
2. El número de tenants/viviendas gestionadas cruza un umbral donde el aislamiento por namespace/autoscaling horizontal por tenant deja de ser opcional (orden de magnitud: decenas de propiedades, no unidades).
3. Aparece una necesidad real de autoscaling multi-servicio que un PaaS ya no pueda absorber con sus límites de plan.
4. El equipo incorpora capacidad operativa dedicada a plataforma/infra capaz de absorber RBAC, cert-manager y observabilidad sin restar horas a producto.
5. El gasto mensual de infraestructura ya ronda varias veces el suelo actual — momento en que la eficiencia de bin-packing/autoscaling de K8s empieza a compensar su propio coste de complejidad.

### Resto del modelo VM — pasan el gate, pierden solo por criterios ponderados frente a Oracle

- **Oracle Cloud (AMD micro, Always Free)** — descartado por tamaño, no por arquitectura: sin riesgo ARM (x86), pero solo 1 OCPU/1GB por instancia (máx. 2 instancias), insuficiente para alojar los 5 servicios del stack simultáneamente en una única VM.
- **AWS Lightsail — candidato muy sólido, fallback secundario documentado.** Es, junto con EC2, el único candidato del modelo VM con provider de Terraform en tier **oficial** (`hashicorp/aws`, el mismo que EC2/Fargate/App Runner) — el estándar de madurez más alto posible de todos los evaluados. Sin riesgo de arquitectura (x86 estándar). Precio empaquetado y predecible (~$24/mes, incluye transfer y storage, superficie de configuración más simple que EC2 puro). **No gana porque**: (a) no tiene capa gratuita permanente — el "AWS Free Tier" vigente desde jul-2025 es un crédito de bienvenida de $200 con caducidad para cuentas nuevas, no un always-free indefinido a este tamaño de instancia (distinción exigida por R1.5); (b) a igualdad del resto de criterios de peso alto con Hetzner, su coste (~$24/mes) es notablemente mayor que Hetzner (~€5,49/mes) sin una ventaja de migración/Terraform suficiente para justificar la diferencia frente a Oracle (0€). Queda documentado como el respaldo a elegir si se prefiere el tier "oficial" de Terraform o consolidar en el ecosistema AWS por encima del ahorro de Hetzner.
- **AWS EC2** — mismo provider oficial y mismo AWS Free Tier basado en créditos con caducidad (no permanente) que Lightsail. Máxima flexibilidad de tamaño/arquitectura, pero mayor carga de configuración (VPC, security groups, EBS, IP elástica) que Lightsail para el mismo resultado; si se elige una instancia Graviton (`t4g.*`) para abaratar, hereda el mismo riesgo de arquitectura ARM que Oracle, sin la ventaja de coste 0€. No aporta nada que Lightsail no cubra ya mejor para este caso de uso.
- **Hetzner Cloud — fallback primario documentado.** Sin riesgo de arquitectura (x86), provider Terraform partner-tier igual de maduro y activo que el resto del grupo (`hetznercloud/hcloud`; único gap conocido: sin recursos DNS nativos, solucionable con el provider community `timohirt/hetznerdns` si hiciera falta DNS-as-code), y el más barato de las opciones de pago (~€5,49/mes). No gana solo porque Oracle ofrece el mismo perfil de riesgo aceptable a coste 0€ en vez de €5,49/mes — si el riesgo ARM de Oracle se materializa, Hetzner es el fallback más directo.
- **Scaleway** (~€16,79/mes) y **DigitalOcean** ($24/mes) — mismo perfil que Hetzner (partner-tier maduro, sin riesgo de arquitectura, gate superado), pero más caros sin una ventaja diferencial de Terraform o migración que lo compense; Scaleway aporta DNS nativo (partner-premier) y DigitalOcean una superficie de recursos algo más amplia, pero ninguno de los dos justifica el sobrecoste frente a Hetzner como fallback.

### Candidatos PaaS — pasan el gate, pierden por criterios ponderados

- **Render** — el mejor posicionado de los PaaS: provider Terraform **oficial** (`render-oss/render`), con cobertura completa de servicios (web service, background worker como tipo de primera clase — buen fit para Celery —, Postgres, Key Value/Valkey). No gana porque (a) el ajuste de migración exige decomponer el `docker-compose.yml` en un blueprint (`render.yaml`), no reutilizarlo tal cual; (b) su coste realista (~$35-45/mes) es notablemente mayor que el modelo VM, ya que el Postgres gratuito caduca a los 30 días y no es sostenible como entorno permanente sin pasar a plan de pago.
- **Railway** — pasa el gate técnicamente (deploy real vía CLI/auto-deploy, no bloquea CI) pero con el riesgo de Terraform más alto de los candidatos no excluidos: provider **community**, cobertura parcial (sin recurso de "deployment"). Sin free tier permanente utilizable (solo crédito de prueba de $5 con caducidad). Coste ~$5-20+/mes.

### Candidatos serverless gestionados — pasan el gate, pierden por criterios ponderados

- **AWS Fargate (ECS)** — provider Terraform oficial con cobertura total, y es el único de los serverless que aloja las 3 piezas de cómputo (backend, frontend, worker Celery) sin fragmentar la topología. No gana porque el coste realista (~$68-106/mes, con RDS+ElastiCache+ALB/NAT) es el más alto de los candidatos que sí pasan el gate, y el ajuste de migración exige decomponer el compose en task definitions separadas.
- **AWS App Runner** — pasa el gate técnico de IaC, pero **no cubre el stack por sí solo**: el worker Celery no es viable en su modelo (estrangula CPU sin tráfico HTTP entrante), obligando a correr igualmente Fargate en paralelo solo para el worker — duplicando plataforma sin un ahorro claro frente a usar Fargate para las 3 piezas directamente.
- **GCP Cloud Run (+ Worker Pools)** — provider oficial (`hashicorp/google`), y sí cubre las 3 piezas de cómputo gracias a Worker Pools (GA abr-2026), con parte del cómputo backend/frontend potencialmente a 0€ por su Always Free permanente. No gana porque (a) el recurso de Terraform para Worker Pools es tan reciente que su cobertura no está confirmada — riesgo real de IaC a verificar antes de comprometerse; (b) Cloud SQL + Memorystore (este último especialmente caro, ~$36/mes mínimo sin tier más pequeño) elevan el coste realista a ~$62-70/mes.

## Tabla comparativa completa (todos los candidatos investigados)

Escala cualitativa: 🟢 Alto/favorable · 🟡 Medio/riesgo gestionable · 🔴 Bajo/desfavorable. Los tres criterios de peso alto (R2.2) llevan **negrita** en la cabecera.

| Modelo | Candidato | Coste (2 viviendas, 0€ perm.?) | **Terraform** | **Migración Docker** | **GitHub Actions/IaC** | Postgres/Redis | Lock-in (desempate) | Carga operativa | Gate |
|---|---|---|---|---|---|---|---|---|---|
| VM | **Oracle Cloud (Ampere A1, Always Free) — GANADOR** | 🟢 0€/mes permanente | 🟢 Partner, activo, cobertura completa | 🟡 Alto en abstracto; riesgo ARM64 real a verificar | 🟢 Total | 🟢 Autoalojado en contenedor | 🟡 Bajo-medio (home region fija) | 🔴 Alta + riesgo capacidad | ✅ Pasa |
| VM | Oracle Cloud (AMD micro, Always Free) | 🟢 0€/mes | 🟢 igual | 🟢 Sin riesgo arch. | 🟢 Total | 🟢 Autoalojado | 🟡 igual | 🔴 Alta | Descartado por tamaño (1 OCPU/1GB insuficiente) |
| VM | **Hetzner Cloud — fallback primario** | 🟡 ~€5,49/mes | 🟢 Partner, activo | 🟢 Alto, sin riesgo | 🟢 Total | 🟢 Autoalojado | 🟢 Bajo | 🔴 Alta | ✅ Pasa |
| VM | Scaleway | 🟡 ~€16,79/mes | 🟢 Partner-premier, DNS nativo | 🟢 Alto, sin riesgo | 🟢 Total | 🟢 Autoalojado | 🟢 Bajo | 🔴 Alta | ✅ Pasa |
| VM | DigitalOcean | 🟡 $24/mes | 🟢 Partner, maduro | 🟢 Alto, sin riesgo | 🟢 Total | 🟢 Autoalojado | 🟢 Bajo | 🔴 Alta | ✅ Pasa |
| VM | **AWS Lightsail — fallback secundario** | 🟡 $24/mes (sin free tier perm.; crédito $200 con caducidad desde jul-2025) | 🟢 **Oficial** (`hashicorp/aws`) | 🟢 Alto, sin riesgo | 🟢 Total | 🟢 Autoalojado | 🟡 Bajo-medio (ecosistema AWS) | 🔴 Alta (algo menor que EC2) | ✅ Pasa |
| VM | AWS EC2 | 🟡 $12-30/mes (mismo crédito con caducidad que Lightsail, no perm.) | 🟢 **Oficial** | 🟢 Alto (x86) / 🟡 riesgo ARM si Graviton | 🟢 Total | 🟢 Autoalojado | 🟡 Bajo-medio | 🔴 Alta (mayor config.) | ✅ Pasa |
| PaaS | Render | 🟡 ~$35-45/mes (Postgres gratis caduca a 30 días) | 🟢 **Oficial** (`render-oss/render`) | 🟡 Medio (decomposición vía blueprint, worker de 1ª clase) | 🟢 Total | 🟢 Nativo (Postgres+Valkey) | 🟡 Medio (networking/DB propios) | 🟢 Baja | ✅ Pasa |
| PaaS | Railway | 🟡 ~$5-20+/mes (sin free tier perm.) | 🔴 Community, cobertura parcial | 🟡 Medio (sin `depends_on`) | 🟡 Parcial (deploy real vía CLI, no Terraform) | 🟡 Parcial (contenedor propio en el proyecto) | 🟡 Medio | 🟢 Baja-media | ✅ Pasa (con riesgo Terraform señalado) |
| PaaS | Fly.io | 🔴 ~$50-70/mes (MPG) | 🔴 Provider archivado 2024, sin soporte oficial | 🟢 Alto (mejor Docker fit del grupo) | 🔴 Sin Terraform viable | 🟡 MPG gestionado ($38+/mes) o Upstash Redis (3º) | 🟡 Medio | 🟡 Media-alta | ❌ Excluido (gate) |
| PaaS | Vercel | N/A (modelo distinto) | 🟡 Partner, activo pero solo config. proyecto | 🔴 Requiere reescritura (Celery, DBs) | 🔴 No cubre despliegue de infra | 🔴 Vía Marketplace (Neon/Upstash, 3º) | 🔴 Alto | N/A | ❌ Excluido (gate) |
| Serverless | AWS Fargate (ECS) | 🔴 ~$68-106/mes (RDS+ElastiCache+ALB) | 🟢 **Oficial**, cobertura total | 🟡 Medio (decomposición en tasks) | 🟢 Total (OIDC) | 🟡 Gestionado obligatorio (RDS+ElastiCache) | 🟡 Medio | 🟡 Media | ✅ Pasa |
| Serverless | AWS App Runner | 🟡 ~$37-40/mes (+ Fargate obligatorio para el worker) | 🟢 Oficial, algo menos superficie | 🔴 No cubre el worker solo | 🟢 Total | 🟡 Gestionado obligatorio (RDS+ElastiCache) | 🟡 Medio-alto | 🟡 Media (duplica plataforma) | ✅ Pasa técnicamente, pero no cubre el stack sin Fargate |
| Serverless | GCP Cloud Run (+ Worker Pools) | 🟡 ~$62-70/mes (Cloud SQL+Memorystore; cómputo backend/frontend puede ser 0€) | 🟡 Oficial, pero recurso Worker Pool en Terraform sin confirmar (GA abr-2026) | 🟡 Medio (decomposición, sin rewrite) | 🟢 Total (Workload Identity) | 🟡 Gestionado obligatorio (Cloud SQL+Memorystore, este último caro) | 🟢 Bajo (base Knative) | 🟢 Baja | ✅ Pasa (con riesgo IaC de Worker Pools a verificar) |
| Kubernetes | AWS EKS | 🔴 ~$150-220/mes | 🟢 Oficial, excelente (no es el problema) | 🔴 Alto esfuerzo (~18-22 manifiestos vs. 1 compose) | 🟢 Total | 🟡 Gestionado o autoalojado con PVC | 🟡 Medio | 🔴 Muy alta | Rechazado (R3, complejidad/coste prematuros) |
| Kubernetes | GCP GKE | 🔴 ~$95-140/mes | 🟢 Oficial, excelente | 🔴 Alto esfuerzo | 🟢 Total | 🟡 Gestionado o autoalojado con PVC | 🟡 Medio | 🔴 Muy alta | Rechazado (R3, complejidad/coste prematuros) |

## Consecuencias

**Positivas:**
- Coste de infraestructura de dev: 0€/mes de forma sostenida, sin necesidad de gestionar presupuesto para este entorno, siempre que la tenancy se mantenga como Always Free pura (ver riesgo de facturación abajo).
- IP pública (efímera o reservada) y 10 TB/mes de egress incluidos sin coste — sin necesidad de Load Balancer ni NAT Gateway, evitando los gastos escondidos de red que sí aparecen en los modelos serverless investigados.
- Cero reescritura de la aplicación — el mismo `docker-compose.yml` que hoy corre en local se reutiliza en remoto.
- Terraform y GitHub Actions, ya confirmados como herramientas del proyecto, se usan tal como estaban previstos, sin adaptar el flujo a un modelo propietario.

**Negativas / riesgos aceptados (con mitigación):**
- **Riesgo de arquitectura ARM64**: antes de escribir el `.tf` real de este entorno, hay que verificar/añadir build multi-arch en CI para las imágenes de `backend/devops/Dockerfile` y `frontend/devops/Dockerfile` (los binarios base lo soportan, pero no hay pipeline multi-arch probado hoy en el repo). Se documenta como tarea de seguimiento explícita para el change que escriba el Terraform real.
- **Historial de recortes silenciosos del free tier**: Oracle redujo el cupo Always Free de 4 OCPU/24GB a 2 OCPU/12GB el 15-jun-2026 sin anuncio oficial previo. No hay garantía contractual de que el cupo actual (2 OCPU/12GB) se mantenga indefinidamente. Mitigación: Hetzner (fallback primario) o AWS Lightsail (fallback secundario) quedan documentados como respaldo operativo inmediato, sin necesidad de reabrir este ADR si esto ocurre.
- **"Out of host capacity"**: aprovisionar instancias Ampere A1 gratuitas puede fallar por falta de capacidad en regiones de alta demanda (persistente en 2026). Mitigación: elegir Frankfurt o Singapur como home region al crear la tenancy (decisión irreversible sin borrar la cuenta).
- **Home region fija**: la cuenta Always Free queda atada a la región elegida al crearla; no se puede migrar de región sin recrear la cuenta desde cero.
- **Facturación condicionada al tipo de tenancy**: el 0€/mes solo está garantizado sin excepciones en una tenancy **Always Free pura** (exceder cuota suspende la instancia, no factura). Si la tenancy se actualiza a **Pay As You Go** (p. ej. para desbloquear otro servicio), exceder las cuotas de cómputo/egress/storage sí puede facturarse, con respuestas contradictorias de Oracle sobre el trato exacto a cuentas PAYG tras el recorte de jun-2026. Mitigación: mantener la tenancy como Always Free pura mientras sea posible, y configurar alertas de presupuesto desde el primer día como tarea del futuro change de Terraform real.
- **Carga operativa manual**: al ser una VM autoadministrada, el parcheo de SO, backups de volúmenes, TLS y monitorización corren por cuenta del proyecto — igual que en cualquier otro candidato del modelo VM, pero a diferencia de los modelos PaaS/serverless.

## Criterio de revisión

Reabrir esta decisión (no solo para dev, evaluar también si el patrón debería informar staging/prod) si ocurre cualquiera de:

1. Oracle recorta de nuevo el cupo Always Free, lo elimina, o "out of host capacity" se vuelve un bloqueo recurrente incluso en Frankfurt/Singapur → migrar al fallback documentado (Hetzner como primera opción, AWS Lightsail como segunda) sin reabrir el ADR salvo que también dejen de cumplir criterios.
2. La verificación de multi-arch ARM64 revela una dependencia real sin soporte `arm64` (wheel de Python o binario nativo) que no tenga alternativa viable → mismo fallback.
3. El negocio entra en su fase SaaS multi-tenant con tracción real (criterio detallado en "Kubernetes gestionado" arriba) → posible reconsideración de modelo completo (VM → K8s), no solo de proveedor.
4. Cambian materialmente los precios o condiciones de free tier de cualquier candidato de esta tabla de forma que altere el ranking (revisar esta tabla, no solo la decisión).
5. La tenancy de Oracle se actualiza a Pay As You Go por cualquier motivo (p. ej. para desbloquear otro servicio) → revisar de inmediato si eso reintroduce riesgo de facturación por exceso de cuota (ver Consecuencias) y si sigue siendo preferible a los fallbacks documentados.
