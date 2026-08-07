"""R1.1, R1.2 at the layer where the normalisation actually happens.

The HTTP tests cannot pin this: `ChecklistItemPayload` declares exactly three fields, so
`model_dump()` can never produce a fourth and reverting `spec.items_as_json()` to
`command.items` leaves every API assertion green. The security panel of sections 2-3 caught
that. `CreateChecklistTemplateUseCase` is built for non-HTTP callers too — the provisioner, a
CLI, an importer — and none of them has Pydantic in front of it, so the guarantee has to be
demonstrated here, against a fake repository.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.cleaning.application.use_cases import (
    CreateChecklistTemplateCommand,
    CreateChecklistTemplateUseCase,
)
from app.cleaning.domain.exceptions import CleaningValidationError, PropertyNotFoundError

NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
TENANT = uuid.uuid4()


class FakeTemplateRepository:
    def __init__(self) -> None:
        self.added: list = []

    async def add(self, tenant_id, template) -> None:
        assert tenant_id == template.tenant_id
        self.added.append(template)


class FakeProperties:
    def __init__(self, known: set[uuid.UUID] | None = None) -> None:
        self._known = known or set()

    async def get(self, tenant_id, property_id):
        return object() if property_id in self._known else None


class FakeUow:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _use_case(templates=None, properties=None, uow=None):
    return CreateChecklistTemplateUseCase(
        templates=templates or FakeTemplateRepository(),
        properties=properties or FakeProperties(),
        uow=uow or FakeUow(),
    )


@pytest.mark.asyncio
async def test_only_the_three_validated_keys_are_stored():
    """Rule 11 — these two JSONB columns are not in its table, so nothing unvetted lands.

    Reverting the use case to persist `command.items` makes this test fail, which is the
    whole point: the HTTP-level assertion could not.
    """
    templates = FakeTemplateRepository()

    await _use_case(templates=templates).execute(
        tenant_id=TENANT,
        command=CreateChecklistTemplateCommand(
            name="Estándar",
            items=[
                {
                    "item_id": "kitchen",
                    "label": "Cocina",
                    "required": True,
                    "wifi_password": "hunter2",
                    "notes": "código de la puerta 4821",
                }
            ],
            required_photos=[
                {"photo_type": "kitchen", "label": "Cocina", "required": True, "extra": "x"}
            ],
        ),
        now=NOW,
    )

    stored = templates.added[0]
    assert set(stored.items[0]) == {"item_id", "label", "required"}
    assert set(stored.required_photos[0]) == {"photo_type", "label", "required"}
    assert "hunter2" not in str(stored.items)
    assert "4821" not in str(stored.items)


@pytest.mark.asyncio
async def test_invalid_content_is_refused_before_anything_is_written():
    """R1.2 — "sin escribir nada", and the commit never happens either."""
    templates = FakeTemplateRepository()
    uow = FakeUow()

    with pytest.raises(CleaningValidationError):
        await _use_case(templates=templates, uow=uow).execute(
            tenant_id=TENANT,
            command=CreateChecklistTemplateCommand(
                name="Roto", items=[{"item_id": "a/b", "label": "A"}], required_photos=[]
            ),
            now=NOW,
        )

    assert templates.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_property_outside_the_tenant_is_refused_before_writing():
    """R7.3 — resolved inside the tenant; the FK alone would have accepted a neighbour's id."""
    templates = FakeTemplateRepository()
    uow = FakeUow()

    with pytest.raises(PropertyNotFoundError):
        await _use_case(templates=templates, properties=FakeProperties(), uow=uow).execute(
            tenant_id=TENANT,
            command=CreateChecklistTemplateCommand(
                name="Estándar",
                items=[{"item_id": "a", "label": "A", "required": True}],
                required_photos=[],
                property_id=uuid.uuid4(),
            ),
            now=NOW,
        )

    assert templates.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_a_known_property_is_accepted():
    known = uuid.uuid4()
    templates = FakeTemplateRepository()
    uow = FakeUow()

    await _use_case(
        templates=templates, properties=FakeProperties({known}), uow=uow
    ).execute(
        tenant_id=TENANT,
        command=CreateChecklistTemplateCommand(
            name="Estándar",
            items=[{"item_id": "a", "label": "A", "required": True}],
            required_photos=[],
            property_id=known,
        ),
        now=NOW,
    )

    assert templates.added[0].property_id == known
    assert uow.commits == 1
