# reviews-web

[FE] **`/reviews`, hoy `RoutePlaceholder` sobre un backend entregado**.

> Hito «MVP operable» 3 — *autoservicio del tenant* (auditoría del 2026-09-04).

**El hecho medido (2026-09-04)**: `frontend/app/(workspace)/reviews/page.tsx:11` es un
`RoutePlaceholder`. `revenue-reviews` (archivado 2026-09-02, `sdd/specs/revenue-reviews.md`)
entregó seis rutas en `backend/app/reviews/api/router.py` —alta de reseña, análisis, borrador de
respuesta, aprobar / ignorar / marcar-como-publicada— y el job `classify_reviews` corre cada 5 min
(`scheduler/schedule.py:75`). **Ningún fichero del frontend las llama.** El reparto de permisos
ya está decidido en `auth/domain/policy.py`: el owner aprueba, ignora y marca como publicada; el
manager crea (`CREATE_REVIEW`). Ni `revenue-reviews` ni el roadmap registraron la mitad `[FE]`.

**Por qué no es cosmético**: PRD §18 pone la gestión de reseñas como parte del trabajo de MAGNO
que el producto sustituye, y el flujo es humano en su segunda mitad —la IA propone el borrador,
una persona lo aprueba y **lo publica a mano en la OTA**, porque el posting automático es
non-goal (PRD §29)—. Sin pantalla, la mitad humana no existe: hay borradores que nadie lee.

**Alcance**: `/reviews` con la misma forma que `pricing-web` —una cola de borradores con
decisión— y una pestaña de reseñas: alta a mano (manager, porque no hay ingesta de OTA), texto
original, análisis (sentimiento, problemas recurrentes), borrador con aprobar / ignorar /
marcar-como-publicada (owner). Gateado por permiso con `useHasPermission`. Sin backend.

**Lo que decide y no es cosmético**:

1. **«Marcar como publicada» es una afirmación humana** sobre algo que pasó fuera del sistema,
   como `APPLIED_EXTERNAL` en pricing (`features/pricing/lib/decision-moves.ts:28-31`). La UI lo
   dice así («ya la he publicado en Airbnb»), no «publicar».
2. **El texto de la reseña y del borrador** son texto libre: la reseña es prosa de un tercero
   (el huésped) copiada por el manager, el borrador lo genera el mock. Comprobar en el spec qué
   fila del censo de la regla 11 tienen y no inventar otra; el `MockAIAdapter` de reviews no
   cita el input (misma disciplina que `messaging/infrastructure/ai.py:16-18`) — la UI tampoco
   debe recombinar.
3. **Editar el borrador antes de aprobar**: si la API lo admite, es la operación con más valor
   de la pantalla; si no, aprobar/ignorar y punto, y una candidata `[BE]`.
4. **Sin IA real** (`revenue-reviews` hereda el mock de `messaging-ai`): el análisis que se
   pinta es por palabras clave. La UI no lo vende como más de lo que es (`ASSUMPTION` visible en
   la doc, no en la pantalla).

**Fuera de alcance**: ingesta de reseñas desde OTAs (no hay API ni la habrá en el MVP); posting
automático; IA real; notificar al owner de un borrador nuevo más allá de lo que
`notification-writers-gap` ya cubra.
