"""The storage key schemes (design D3/R1.4 for cleaning, `incident-photos` D4/R1 for incidents).

Two properties are pinned for each: the exact format, and that the client's file name reaches
none of it.

Since `incident-photos` there are **two** public key functions over one shared private body
(`_photo_storage_key`), so a third property matters and is pinned too: the extraction did not
change the cleaning key, and the guard on `extension` still refuses through **both** doors.
That last one is the whole reason the body is shared — one home for the check.
"""

import uuid

import pytest

from app.integrations.domain.storage import (
    ACCEPTED_IMAGE_TYPES,
    detect_image_type,
    storage_key_for_incident_photo,
    storage_key_for_photo,
)

TENANT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
TASK = uuid.UUID("33333333-3333-3333-3333-333333333333")
PHOTO = uuid.UUID("44444444-4444-4444-4444-444444444444")
INCIDENT = uuid.UUID("55555555-5555-5555-5555-555555555555")


def test_the_format_is_fixed() -> None:
    key = storage_key_for_photo(
        tenant_id=TENANT_A, task_id=TASK, photo_id=PHOTO, extension="jpg"
    )

    assert key == (
        "tenants/11111111-1111-1111-1111-111111111111/"
        "cleaning-tasks/33333333-3333-3333-3333-333333333333/"
        "44444444-4444-4444-4444-444444444444.jpg"
    )


def test_the_tenant_comes_first_so_an_s3_prefix_is_scopeable() -> None:
    key = storage_key_for_photo(
        tenant_id=TENANT_A, task_id=TASK, photo_id=PHOTO, extension="png"
    )

    assert key.startswith(f"tenants/{TENANT_A}/")


def test_two_tenants_cannot_collide_even_on_the_same_task_and_photo_ids() -> None:
    """R1.4: not through a UUID collision on the task, and not through a repeated
    `photo_type` — the key contains neither the type nor anything a caller chooses."""
    a = storage_key_for_photo(tenant_id=TENANT_A, task_id=TASK, photo_id=PHOTO, extension="jpg")
    b = storage_key_for_photo(tenant_id=TENANT_B, task_id=TASK, photo_id=PHOTO, extension="jpg")

    assert a != b
    assert not a.startswith(f"tenants/{TENANT_B}/")
    assert not b.startswith(f"tenants/{TENANT_A}/")


def test_the_extension_comes_from_the_detected_content() -> None:
    detected = detect_image_type(b"\x89PNG\r\n\x1a\n\x00")
    assert detected is not None

    key = storage_key_for_photo(
        tenant_id=TENANT_A, task_id=TASK, photo_id=PHOTO, extension=detected.extension
    )

    assert key.endswith(".png")


@pytest.mark.parametrize("extension", sorted(image.extension for image in ACCEPTED_IMAGE_TYPES))
def test_every_accepted_format_has_a_usable_extension(extension: str) -> None:
    key = storage_key_for_photo(
        tenant_id=TENANT_A, task_id=TASK, photo_id=PHOTO, extension=extension
    )

    assert key.endswith(f".{extension}")


@pytest.mark.parametrize(
    "extension", ["exe", "php", "", "jpg/../../etc/passwd", "JPG", "jpeg"]
)
def test_an_extension_that_did_not_come_from_detection_is_refused(extension: str) -> None:
    """The only legitimate source of the extension is `detect_image_type` (D3/D5). Anything
    else means a caller invented one, and `jpg/../../etc/passwd` is what that looks like when
    it is hostile."""
    with pytest.raises(ValueError):
        storage_key_for_photo(
            tenant_id=TENANT_A, task_id=TASK, photo_id=PHOTO, extension=extension
        )


def test_the_signature_has_no_place_for_a_client_file_name() -> None:
    """Design D3 rejects "sanitised" client names outright: sanitising is a blacklist, and
    blacklists of path fragments fail. The enforcement is that there is no parameter to pass
    one through — checked here so nobody adds one quietly.
    """
    import inspect

    parameters = set(inspect.signature(storage_key_for_photo).parameters)

    assert parameters == {"tenant_id", "task_id", "photo_id", "extension"}


# --- the incident photo key (`incident-photos` D4, R1) --------------------------------


def test_the_incident_format_is_fixed() -> None:
    key = storage_key_for_incident_photo(
        tenant_id=TENANT_A, incident_id=INCIDENT, photo_id=PHOTO, extension="jpg"
    )

    assert key == (
        "tenants/11111111-1111-1111-1111-111111111111/"
        "incidents/55555555-5555-5555-5555-555555555555/"
        "44444444-4444-4444-4444-444444444444.jpg"
    )


def test_the_incident_key_puts_the_tenant_first_too() -> None:
    """The signature covers the whole key, so the tenant leading it is what makes a valid
    signature unpivotable onto another tenant's object."""
    key = storage_key_for_incident_photo(
        tenant_id=TENANT_A, incident_id=INCIDENT, photo_id=PHOTO, extension="png"
    )

    assert key.startswith(f"tenants/{TENANT_A}/")


def test_two_tenants_cannot_collide_on_the_same_incident_and_photo_ids() -> None:
    a = storage_key_for_incident_photo(
        tenant_id=TENANT_A, incident_id=INCIDENT, photo_id=PHOTO, extension="jpg"
    )
    b = storage_key_for_incident_photo(
        tenant_id=TENANT_B, incident_id=INCIDENT, photo_id=PHOTO, extension="jpg"
    )

    assert a != b
    assert not a.startswith(f"tenants/{TENANT_B}/")
    assert not b.startswith(f"tenants/{TENANT_A}/")


def test_the_incident_and_cleaning_collections_cannot_collide() -> None:
    """The distinguishing segment is what keeps two consumers' keyspaces apart.

    Pinned because the two functions now share a body: a `collection` argument passed wrongly
    — or defaulted — would silently file incident photos under `cleaning-tasks/`, where the
    cleaning route's own unscoped lookup would never find them and nothing would fail loudly.
    """
    incident_key = storage_key_for_incident_photo(
        tenant_id=TENANT_A, incident_id=INCIDENT, photo_id=PHOTO, extension="jpg"
    )
    cleaning_key = storage_key_for_photo(
        tenant_id=TENANT_A, task_id=INCIDENT, photo_id=PHOTO, extension="jpg"
    )

    assert "/incidents/" in incident_key
    assert "/cleaning-tasks/" in cleaning_key
    assert incident_key != cleaning_key


@pytest.mark.parametrize("extension", sorted(image.extension for image in ACCEPTED_IMAGE_TYPES))
def test_every_accepted_format_works_for_an_incident_photo(extension: str) -> None:
    key = storage_key_for_incident_photo(
        tenant_id=TENANT_A, incident_id=INCIDENT, photo_id=PHOTO, extension=extension
    )

    assert key.endswith(f".{extension}")


@pytest.mark.parametrize(
    "extension", ["exe", "php", "", "jpg/../../etc/passwd", "JPG", "jpeg"]
)
def test_the_extension_guard_refuses_through_the_incident_door_too(extension: str) -> None:
    """R1: the guard lives in the shared body, so it cannot hold for one consumer only.

    This is the assertion that would fail if someone re-copied the body instead of sharing it
    and then dropped the check in the copy — the exact failure `_photo_storage_key` exists to
    make impossible.
    """
    with pytest.raises(ValueError):
        storage_key_for_incident_photo(
            tenant_id=TENANT_A, incident_id=INCIDENT, photo_id=PHOTO, extension=extension
        )


def test_the_incident_signature_has_no_place_for_a_client_file_name() -> None:
    """Same enforcement as the cleaning key: there is no parameter to pass one through."""
    import inspect

    parameters = set(inspect.signature(storage_key_for_incident_photo).parameters)

    assert parameters == {"tenant_id", "incident_id", "photo_id", "extension"}
