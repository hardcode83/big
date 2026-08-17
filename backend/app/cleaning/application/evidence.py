"""The four reads the close of a cleaning task needs, and nothing else (R1.1, R2.1).

**Gathers the evidence; does not judge it.** All three clauses of PRD §11 are applied by
`CleaningTask.complete()` and nowhere else — design D8 of `cleaning-photos-storage` —, so
there is not a single comparison in this module: no set difference, no membership test, no
`if` over the evidence it assembles. Returning "what is missing" from here would split an
invariant that `cleaning` spent a whole change concentrating in one method.

Its own module rather than another class in `use_cases.py` (design D1): this is what lets the
test with fakes import four ports instead of a 1.700-line module.
"""

import uuid

from app.cleaning.domain.entities import CleaningTask
from app.cleaning.domain.exceptions import ChecklistTemplateNotFoundError
from app.cleaning.domain.ports import BlockingIncidentQuery
from app.cleaning.domain.repositories import (
    CleaningChecklistCompletionRepository,
    CleaningChecklistTemplateRepository,
    CleaningPhotoRepository,
)
from app.cleaning.domain.value_objects import (
    CleaningCompletionEvidence,
    parse_template_content,
)


class CompletionEvidenceGatherer:
    """Reads the template, the checklist completions, the uploaded photo types and the
    blocking-incident flag, and assembles one `CleaningCompletionEvidence` from them.

    Takes the task already loaded and not its id (design D3): `_load_task` is what applies the
    scoping by tenant *and* by cleaner, and it has to have run first.
    """

    def __init__(
        self,
        *,
        templates: CleaningChecklistTemplateRepository,
        completions: CleaningChecklistCompletionRepository,
        photos: CleaningPhotoRepository,
        incidents: BlockingIncidentQuery,
    ) -> None:
        self._templates = templates
        self._completions = completions
        self._photos = photos
        self._incidents = incidents

    async def gather(
        self, *, tenant_id: uuid.UUID, task: CleaningTask
    ) -> CleaningCompletionEvidence:
        template = await self._templates.get(tenant_id, task.checklist_template_id)
        if template is None:
            raise ChecklistTemplateNotFoundError(
                "The task's checklist template no longer exists"
            )
        spec = parse_template_content(
            template.items, template.required_photos, template_id=template.id
        )
        completions = await self._completions.list_for_task(tenant_id, task.id)

        return CleaningCompletionEvidence(
            required_item_ids=spec.required_item_ids(),
            completed_item_ids=frozenset(
                completion.item_id for completion in completions if completion.completed
            ),
            # PRD §11's third clause (R4.1). `required_photo_types()` filters on
            # `required: true` and `photo_types()` — the one the upload path uses — does not;
            # reading the wrong one here would make every declared type mandatory and break
            # R4.5, which is why the two accessors are named for the questions they answer.
            required_photo_types=spec.required_photo_types(),
            # Distinct types, straight from the repository. Scoped by `tenant_id` like every
            # other read here, and its contract answers with an empty set for a task that is
            # not this tenant's — which blocks a close rather than granting one (design D12).
            uploaded_photo_types=await self._photos.uploaded_photo_types(tenant_id, task.id),
            has_unresolved_critical_incident=await self._incidents.has_unresolved_critical(
                tenant_id, task.property_id
            ),
        )
