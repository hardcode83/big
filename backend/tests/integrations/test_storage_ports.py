"""The shape of the storage ports (task 1.1, R1.1).

What is asserted here is the DESIGN, not behaviour: three methods on `FileStoragePort`, a
separate `LocalFileReadPort`, and an `S3FileStorage` that does not carry a read method at all.
That last assertion is the one with teeth — it is what fails the day someone "simplifies" the
two ports into one and gives S3 a `read` that raises `NotImplementedError`, which is the Liskov
violation `steering/backend-architecture.md` names by hand (design D1).
"""

import dataclasses
import uuid

import pytest

from app.integrations.domain.storage import (
    FileStorageFactory,
    FileStoragePort,
    InvalidSignatureError,
    LocalFileReadPort,
    LocalFileReadUnsupportedError,
    ObjectLocation,
    StorageWriteError,
    UnscopedObjectLocationQuery,
)
from app.integrations.infrastructure.storage import LocalFileStorage, S3FileStorage


def test_the_write_port_has_exactly_three_methods() -> None:
    """R1.1 caps the port at four and requires a caller for each; the design settled on three.

    Checked structurally rather than with `isinstance`: the ports are plain `Protocol`s, and
    making one `runtime_checkable` to satisfy a test would change production code to fit the
    test instead of the other way round (`tests/test_unit_of_work.py` set that precedent).
    """
    surface = {name for name in vars(FileStoragePort) if not name.startswith("_")}

    assert surface == {"put", "signed_url", "delete"}


def test_reading_bytes_back_is_a_separate_port() -> None:
    surface = {name for name in vars(LocalFileReadPort) if not name.startswith("_")}

    assert surface == {"read"}


def test_the_factory_port_resolves_each_kind_separately() -> None:
    surface = {name for name in vars(FileStorageFactory) if not name.startswith("_")}

    assert surface == {"storage_for", "read_for"}


def test_the_local_adapter_implements_both_ports() -> None:
    for name in ("put", "signed_url", "delete", "read"):
        assert callable(getattr(LocalFileStorage, name))


def test_the_s3_adapter_implements_the_write_port() -> None:
    for name in ("put", "signed_url", "delete"):
        assert callable(getattr(S3FileStorage, name))


def test_the_s3_adapter_has_no_read_method_at_all() -> None:
    """Not "raises NotImplementedError" — **absent**.

    With `S3` the browser fetches the object straight from the provider with the presigned
    URL, so no code path reads bytes through the application. A `read` here could only exist
    in order to fail, and `FileStorageFactory.read_for` is what refuses instead (design D1,
    copying `PMSAdapterFactory.messaging_for`).
    """
    assert not hasattr(S3FileStorage, "read")


def test_the_errors_are_distinct_and_catchable() -> None:
    for error in (StorageWriteError, LocalFileReadUnsupportedError, InvalidSignatureError):
        assert issubclass(error, RuntimeError)

    # Not a hierarchy: `except StorageWriteError` must not swallow a signature failure, which
    # is a 403 and not a 502.
    assert not issubclass(LocalFileReadUnsupportedError, StorageWriteError)
    assert not issubclass(InvalidSignatureError, StorageWriteError)


def test_the_unscoped_location_query_has_exactly_one_method() -> None:
    """`incident-photos` R4, design D5: the shared port the anonymous serving route resolves
    through, declared once in `app/integrations/` instead of once per consuming domain.

    One method, and its name says what it does not do. A second method here would be a second
    way to read without a tenant, and the whole value of this port is that the set of such
    reads is enumerable (`tests/test_unscoped_reads.py`).
    """
    surface = {name for name in vars(UnscopedObjectLocationQuery) if not name.startswith("_")}

    assert surface == {"locate_without_tenant_scoping"}


def test_the_object_location_carries_the_key_and_the_tenant_and_nothing_else() -> None:
    """Two facts, because two is what the anonymous route needs to serve bytes.

    Not the owning entity: that would carry `uploaded_by`, the stage and the timestamps of a
    tenant nobody authenticated against into a request that returns an image.
    """
    fields = {field.name for field in dataclasses.fields(ObjectLocation)}

    assert fields == {"storage_key", "tenant_id"}


def test_the_object_location_is_frozen() -> None:
    location = ObjectLocation(storage_key="tenants/x/incidents/y/z.jpg", tenant_id=uuid.uuid4())

    with pytest.raises(dataclasses.FrozenInstanceError):
        location.storage_key = "tenants/other/incidents/y/z.jpg"  # type: ignore[misc]
