# Tasks: dev-hosting-provider

## 1. Investigación de mercado por modelo de despliegue <!-- panel: N/A (docs-only, sin código de producción) -->

- [x] 1.1 Investigar el modelo "VM única + docker-compose": Oracle Cloud (Always Free incluido), Hetzner Cloud, Scaleway, DigitalOcean, AWS Lightsail/EC2. Para cada uno: coste mensual (y si puede quedar en 0€ con su capa gratuita, distinguiendo always-free permanente de crédito de prueba), madurez del provider oficial de Terraform (verificada contra `registry.terraform.io` + actividad reciente del repo, no solo marketing), ajuste de migración desde las imágenes Docker de `local-environment`, soporte de Postgres/Redis, integración GitHub Actions, vendor lock-in, carga operativa. Producir una tabla intermedia (puede vivir en un fichero de trabajo o directamente en un borrador del ADR). [R1, R1.5, R2]
- [x] 1.2 Investigar el modelo "PaaS con deploy nativo de contenedores": Railway, Render, Fly.io, y Vercel (evaluando explícitamente si soporta de forma real backend+worker Celery+Postgres+Redis, no solo su propuesta de marketing). Mismos criterios y verificación de Terraform que 1.1. [R1, R1.5, R2]
- [x] 1.3 Investigar el modelo "contenedores serverless gestionados": AWS Fargate/App Runner, GCP Cloud Run. Mismos criterios y verificación de Terraform que 1.1. [R1, R1.5, R2]
- [x] 1.4 Para cada candidato descartado en una primera pasada durante 1.1-1.3 (p. ej. sin soporte Postgres/Redis, sin provider de Terraform mantenido), anotar el motivo explícito — ninguno desaparece sin rastro. [R1]

## 2. Kubernetes y síntesis comparativa

- [x] 2.1 Evaluar Kubernetes gestionado (EKS/GKE) de forma transversal frente a los tres modelos de 1.1-1.3: coste/complejidad a escala de 2 viviendas, motivo de descarte para esta fase, y criterio explícito de cuándo reconsiderarlo (umbral de tenants/tráfico). [R3]
- [x] 2.2 Aplicar el gate binario de compatibilidad (diseño D6) sobre todos los candidatos de 1.1-1.3: excluir como veredicto final cualquiera que exija reescribir la app a un modelo incompatible con los contenedores de `local-environment`, o que no permita un pipeline de GitHub Actions con `terraform plan`/`apply` directo — sin quitarlo de la tabla, solo marcándolo como no elegible con el motivo. [R2]
- [x] 2.3 Consolidar las tablas de 1.1-1.3 (ya filtradas por 2.2) en una única tabla comparativa completa (todos los candidatos, ningún descarte silencioso), aplicando la rúbrica cualitativa por niveles acordada en el diseño (Alto/Medio/Bajo; criterios de peso alto — madurez Terraform, ajuste de migración Docker, compatibilidad GitHub Actions — destacados; vendor lock-in como desempate explícito entre finalistas empatados). Redactar en prosa por qué el candidato ganador pesa más en esos criterios aunque no gane en todos (incluyendo si su factor decisivo es el coste 0€ por capa gratuita, justificando explícitamente que no sacrifica madurez de Terraform, ajuste de migración ni compatibilidad GitHub Actions). [R2]

## 3. ADR

- [x] 3.1 Crear `docs/adr/` y escribir `docs/adr/0001-dev-hosting-provider.md`: Título, Estado (Aceptado), Contexto, Decisión (proveedor + modelo únicos para dev), tabla comparativa completa de 2.3 (con los excluidos por el gate de 2.2 marcados), Alternativas consideradas (cada candidato descartado con motivo, incluyendo Kubernetes de 2.1 y los excluidos por el gate de 2.2), Consecuencias (positivas y negativas), Criterio de revisión (incluye disparador si cambian precios/capas gratuitas, no solo si escala el negocio). [R4]

## 4. Actualización de steering, specs y placeholders de infra

- [x] 4.1 Actualizar `sdd/steering/infra.md`: añadir sección "Decisión (dev)" al principio de "Criterio de decisión de proveedor cloud" con el veredicto + enlace al ADR; mantener la tabla comparativa completa debajo, ampliada con todos los candidatos investigados, como referencia histórica. Dejar explícito que staging/prod siguen sin decidir. [R5]
- [x] 4.2 Actualizar `sdd/specs/infra-scaffold.md` (sección "Herramientas confirmadas, proveedor pendiente"): reflejar que el proveedor de dev ya está decidido, enlazar al ADR, mantener staging/prod como pendientes. [R5]
- [x] 4.3 Actualizar `infra/environments/dev/README.md`: la línea "Estado" deja de decir "sin proveedor cloud elegido" y refleja el proveedor/modelo decidido, con enlace al ADR. [R5]

## 5. Verification

- [x] 5.1 Checklist cruzado: cada requisito R1-R5 del proposal tiene reflejo verificable en el ADR y en los documentos actualizados — verificado punto por punto contra `proposal.md`; único gap encontrado (R3.2, criterio de reconsideración de K8s aludido pero no detallado en el ADR) corregido añadiendo la sección "Kubernetes gestionado — evaluado y descartado" con los 5 triggers explícitos.
- [x] 5.2 Confirmado con `test -f` que `docs/adr/0001-dev-hosting-provider.md`, `sdd/steering/infra.md`, `sdd/specs/infra-scaffold.md` e `infra/environments/dev/README.md` existen en las rutas referenciadas.
- [x] 5.3 `grep -rn "pendiente de decisión" sdd/steering/infra.md sdd/specs/infra-scaffold.md infra/environments/dev/README.md` → sin resultados (exit 1): ya no aparece esa frase ni para dev ni para staging/prod (se reformuló como "pendientes de decisión propia").
- [x] 5.4 Revisión manual: el ganador (Oracle Cloud, VM+docker-compose) pasa el gate 2.2 (encaja con `local-environment` sin reescritura salvo verificación ARM64 pendiente y documentada; `terraform plan`/`apply` total desde GitHub Actions) y la ADR justifica en prosa (sección "Por qué gana...") que el factor decisivo (coste 0€ permanente) no sacrifica madurez de Terraform, ajuste de migración ni compatibilidad GitHub Actions. Vendor lock-in documentado para todos los candidatos en la tabla; no hubo empate exacto que requiriera desempate formal (el coste 0€ de Oracle fue decisivo por sí solo), documentado como tal.
