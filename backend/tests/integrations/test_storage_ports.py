"""The shape of the storage ports (task 1.1, R1.1).

What is asserted here is the DESIGN, not behaviour: three methods on `FileStoragePort`, a
separate `LocalFileReadPort`, and an `S3FileStorage` that does not carry a read method at all.
That last assertion is the one with teeth — it is what fails the day someone "simplifies" the
two ports into one and gives S3 a `read` that raises `NotImplementedError`, which is the Liskov
violation `steering/backend-architecture.md` names by hand (design D1).
"""

from app.integrations.domain.storage import (
    FileStorageFactory,
    FileStoragePort,
    InvalidSignatureError,
    LocalFileReadPort,
    LocalFileReadUnsupportedError,
    StorageWriteError,
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
