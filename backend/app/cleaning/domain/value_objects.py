"""Value objects of the cleaning domain (R4, R5, design D4).

Immutable and without identity, per `steering/backend-architecture.md` §DDD. They exist so
`CleaningTask.complete()` can protect PRD §11's validation rule without reaching for a
repository: the entity receives the evidence it needs to decide, and the use case is what
gathers it.
"""

import re
import uuid
from dataclasses import dataclass, field

from app.cleaning.domain.exceptions import CleaningValidationError

# `cleaning_checklist_completions.item_id` and `cleaning_photos.photo_type` are
# `String(100)` (`app/cleaning/infrastructure/models.py:75,90`). Without this cap a
# template validates fine and then blows up at completion time with
# `StringDataRightTruncationError` — a 500 where R1.2 promises a 422 "sin escribir nada".
# Measured by the QA reviewer of section 1 against the real Postgres.
MAX_KEY_LENGTH = 100
MAX_LABEL_LENGTH = 200
# The template's two JSONB columns have no width limit of their own, so the bound is here.
MAX_ITEMS = 200
MAX_REQUIRED_PHOTOS = 50

# `item_id` travels as a **path segment** — `POST /cleaning-tasks/{id}/checklist/{item_id}/complete`
# (PRD §23) — so a value containing `/`, a space or a percent produces an item that can be
# created and never completed. Restricting the charset at the point of creation is what makes
# R1.2's "deja de poder ser texto libre" true for the whole life of the key.
#
# `\Z` and not `$`: in Python `$` also matches **immediately before a trailing newline**, so
# `^[A-Za-z0-9._-]+$` accepts `"kitchen\n"`. That defeats R1.2's uniqueness promise —
# `"kitchen"` and `"kitchen\n"` render identically and the duplicate check treats them as two
# — and puts a control character into a URL segment and into every log line that later
# interpolates it. Measured and reported by the security reviewer of section 1.
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\Z")


@dataclass(frozen=True)
class ChecklistItemSpec:
    """One item of a checklist template, already validated.

    `item_id` is the key `cleaning_checklist_completions.item_id` stores, so it is a
    string and not a UUID: the template author writes it.
    """

    item_id: str
    label: str
    required: bool = False


@dataclass(frozen=True)
class RequiredPhotoSpec:
    """One entry of `cleaning_checklist_templates.required_photos`.

    `required` is what PRD §11's third clause is asked about at completion time, and since
    `cleaning-photos-storage` (R4) it is enforced: `ChecklistTemplateSpec.required_photo_types()`
    reads it, `CleaningCompletionEvidence` carries it and `CleaningTask.complete()` refuses
    without it. `cleaning` parsed this spec and deliberately did not enforce it, which is why
    that change added the parser and this one added only the enforcement.

    The column's name says `required_photos` while the entries in it may perfectly well be
    optional; that is the schema `domain-foundation-ops` created and it is not being renamed
    for a docstring. The flag is what decides, not the column.
    """

    photo_type: str
    label: str
    required: bool = False


@dataclass(frozen=True)
class CleaningCompletionEvidence:
    """Everything `CleaningTask.complete()` needs to apply PRD §11's rule — **all three
    clauses** of it, since `cleaning-photos-storage` (design D8).

    Passed in rather than fetched: the entity stays pure Python and the use case owns the
    reads. `has_unresolved_critical_incident` is a boolean and not a list of incidents on
    purpose — `cleaning` only *reads* incidents for this precondition (proposal §Out of
    scope), so importing the maintenance aggregate here would couple the two domains for
    a yes/no answer.

    The two photo fields are the **exact mirror** of the two item fields, down to the shape of
    the accessor, and that symmetry is the design (D8): one rule, expressed twice in the same
    words, so a reader who has understood the checklist clause has already understood the photo
    one. They are sets of `photo_type` and not of photos because the question is membership —
    R4.1 asks for *at least one* photo per required type, so counts and order carry nothing.

    **Both photo fields default to empty, and the defaults are not symmetric in effect.** An
    evidence built without them requires no photo and so permits the close, which is the same
    direction the item fields already default in and the only safe one for a value object that
    a future caller may build partially: a default that *blocked* would turn every unrelated
    construction into a refusal nobody asked for. What makes the rule enforced is the use case
    populating both fields, which is where R4.3 puts the reading and where its test lives.
    """

    required_item_ids: frozenset[str] = field(default_factory=frozenset)
    completed_item_ids: frozenset[str] = field(default_factory=frozenset)
    has_unresolved_critical_incident: bool = False
    required_photo_types: frozenset[str] = field(default_factory=frozenset)
    uploaded_photo_types: frozenset[str] = field(default_factory=frozenset)

    def missing_required_item_ids(self) -> tuple[str, ...]:
        """Sorted so the 409 body is stable across runs and diffable in tests."""
        return tuple(sorted(self.required_item_ids - self.completed_item_ids))

    def missing_required_photo_types(self) -> tuple[str, ...]:
        """The third clause of PRD §11, in the same line as the first (R4.1, R4.4).

        Sorted for the same reason: `frozenset` iteration order is unspecified and varies with
        the hash seed, so a 409 body built straight from the difference would be a different
        body between two processes serving the same request.

        A **difference**, never a truth test on `uploaded_photo_types`: R4.5 says the rule is
        "the required ones", not "some", so a template declaring only optional photos yields an
        empty `required_photo_types` and this returns `()` — the close proceeds with no photos
        at all, exactly as it does for a checklist with no required item.
        """
        return tuple(sorted(self.required_photo_types - self.uploaded_photo_types))


@dataclass(frozen=True)
class ChecklistTemplateSpec:
    """The parsed, validated content of a template's two JSONB columns.

    `domain-foundation-ops` persists `items`/`required_photos` **without validating their
    structure** (`specs/domain-foundation-ops.md` §Esquema DB). From this change on the
    `item_id` is the key the checklist is completed by, so it stops being free text
    (R1.2).
    """

    items: tuple[ChecklistItemSpec, ...] = ()
    required_photos: tuple[RequiredPhotoSpec, ...] = ()

    def required_item_ids(self) -> frozenset[str]:
        return frozenset(item.item_id for item in self.items if item.required)

    def item_ids(self) -> frozenset[str]:
        return frozenset(item.item_id for item in self.items)

    def photo_types(self) -> frozenset[str]:
        """Every `photo_type` the template declares, required or not (R2.2).

        The photo counterpart of `item_ids()`, and it deliberately does **not** filter on
        `required`: a template that asks for an optional "before" shot still declares a type
        the cleaner may upload. What `required: true` governs is the completion rule of
        PRD §11's third clause, which is a different question asked at a different moment.
        """
        return frozenset(photo.photo_type for photo in self.required_photos)

    def required_photo_types(self) -> frozenset[str]:
        """The types PRD §11's third clause demands at completion (R4.1) — mirror of
        `required_item_ids()`.

        The two photo accessors answer different questions and both have exactly one caller:
        `photo_types()` gates the **upload** (R2.2 — may this type be uploaded at all?), this
        one gates the **close** (R4.1 — is this type there?). Collapsing them would make every
        declared type mandatory, which is R4.5's failure exactly.
        """
        return frozenset(
            photo.photo_type for photo in self.required_photos if photo.required
        )

    def items_as_json(self) -> list[dict[str, object]]:
        """What goes into `cleaning_checklist_templates.items`.

        **The parsed spec, never the caller's dicts.** Those two columns are free JSONB and
        rule 11 of `steering/security.md` does not enumerate them, so a key the parser never
        inspected would survive into the column and back out of `GET` unchanged. Over HTTP
        `extra="forbid"` closes it, but this use case is built for non-HTTP callers too — the
        provisioner, a CLI, an importer — and they have no such gate. Raised by the security
        panel of sections 2-3.
        """
        return [
            {"item_id": item.item_id, "label": item.label, "required": item.required}
            for item in self.items
        ]

    def required_photos_as_json(self) -> list[dict[str, object]]:
        return [
            {"photo_type": photo.photo_type, "label": photo.label, "required": photo.required}
            for photo in self.required_photos
        ]


def _require_str(raw: object, key: str, where: str, *, max_length: int) -> str:
    value = raw if isinstance(raw, str) else None
    if value is None or not value.strip():
        raise CleaningValidationError(f"{where}: '{key}' must be a non-empty string")
    if len(value) > max_length:
        raise CleaningValidationError(
            f"{where}: '{key}' is longer than {max_length} characters"
        )
    return value


def _require_key(raw: object, key: str, where: str) -> str:
    """A string that will live in a `String(100)` column *and* in a URL path segment."""
    value = _require_str(raw, key, where, max_length=MAX_KEY_LENGTH)
    if not KEY_PATTERN.match(value):
        raise CleaningValidationError(
            f"{where}: '{key}' may only contain letters, digits, '.', '_' and '-'"
        )
    return value


def _require_bool(raw: object, key: str, where: str) -> bool:
    # `isinstance(True, int)` is True in Python, so an explicit type check is the only way
    # to reject `required: 1` — which would otherwise silently become `True`.
    if not isinstance(raw, bool):
        raise CleaningValidationError(f"{where}: '{key}' must be a boolean")
    return raw


def parse_template_content(
    items: object, required_photos: object, *, template_id: uuid.UUID | None = None
) -> ChecklistTemplateSpec:
    """Validate and parse the two JSONB columns of a template (R1.2).

    Raises `CleaningValidationError` — answered 422 on the create endpoint — for anything
    that is not a list of objects with a non-empty `item_id`/`photo_type` and a boolean
    `required`, and for a duplicated `item_id`, which would make
    `uq_cleaning_checklist_completions_cleaning_task_id_item_id` ambiguous about which
    item was ticked.
    """
    where = f"template {template_id}" if template_id else "template"

    if not isinstance(items, list) or not items:
        raise CleaningValidationError(f"{where}: 'items' must be a non-empty list")
    if len(items) > MAX_ITEMS:
        raise CleaningValidationError(f"{where}: 'items' holds more than {MAX_ITEMS} entries")
    if not isinstance(required_photos, list):
        raise CleaningValidationError(f"{where}: 'required_photos' must be a list")
    if len(required_photos) > MAX_REQUIRED_PHOTOS:
        raise CleaningValidationError(
            f"{where}: 'required_photos' holds more than {MAX_REQUIRED_PHOTOS} entries"
        )

    parsed_items: list[ChecklistItemSpec] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise CleaningValidationError(f"{where}: every item must be an object")
        item_id = _require_key(raw.get("item_id"), "item_id", where)
        if item_id in seen:
            raise CleaningValidationError(f"{where}: duplicated item_id {item_id!r}")
        seen.add(item_id)
        parsed_items.append(
            ChecklistItemSpec(
                item_id=item_id,
                label=_require_str(
                    raw.get("label"), "label", where, max_length=MAX_LABEL_LENGTH
                ),
                required=_require_bool(raw.get("required", False), "required", where),
            )
        )

    parsed_photos: list[RequiredPhotoSpec] = []
    seen_photos: set[str] = set()
    for raw in required_photos:
        if not isinstance(raw, dict):
            raise CleaningValidationError(f"{where}: every required photo must be an object")
        photo_type = _require_key(raw.get("photo_type"), "photo_type", where)
        if photo_type in seen_photos:
            raise CleaningValidationError(f"{where}: duplicated photo_type {photo_type!r}")
        seen_photos.add(photo_type)
        parsed_photos.append(
            RequiredPhotoSpec(
                photo_type=photo_type,
                label=_require_str(
                    raw.get("label"), "label", where, max_length=MAX_LABEL_LENGTH
                ),
                required=_require_bool(raw.get("required", False), "required", where),
            )
        )

    return ChecklistTemplateSpec(items=tuple(parsed_items), required_photos=tuple(parsed_photos))
