"""Resolving a tenant's storage from `TenantConfig.storage_type` (task 1.6, R1.2).

The assertion the design hangs on is the last one: `read_for` refuses an `S3` tenant **before
instantiating anything**. That is design D1's mechanism — the factory refuses, with a typed
error, instead of a port method that exists in order to fail — and it is the same shape
`PMSAdapterFactory.messaging_for` established in `domain/ports.py`.
"""

from pathlib import Path

import pytest

from app.integrations.domain.storage import (
    FileStorageFactory,
    LocalFileReadUnsupportedError,
    StorageWriteError,
    derive_signing_key,
)
from app.integrations.infrastructure.storage import (
    ConfiguredFileStorageFactory,
    LocalFileStorage,
    S3FileStorage,
)
from app.tenants.domain.enums import StorageType


class _ClientSpy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        return object()


def _factory(tmp_path: Path, *, bucket: str = "autohostai-media", spy: _ClientSpy | None = None):
    return ConfiguredFileStorageFactory(
        signing_key=derive_signing_key("s" * 64),
        local_root=tmp_path,
        s3_bucket=bucket,
        s3_client_factory=spy or _ClientSpy(),
    )


def test_it_implements_the_port_surface() -> None:
    for name in vars(FileStorageFactory):
        if not name.startswith("_"):
            assert callable(getattr(ConfiguredFileStorageFactory, name))


def test_local_resolves_to_the_disk_adapter(tmp_path: Path) -> None:
    storage = _factory(tmp_path).storage_for(StorageType.LOCAL)

    assert isinstance(storage, LocalFileStorage)


def test_s3_resolves_to_the_s3_adapter(tmp_path: Path) -> None:
    spy = _ClientSpy()

    storage = _factory(tmp_path, spy=spy).storage_for(StorageType.S3)

    assert isinstance(storage, S3FileStorage)
    assert spy.calls == 1


def test_resolving_local_never_builds_an_s3_client(tmp_path: Path) -> None:
    """Constructing a boto3 client reads the credential chain; doing it for a `LOCAL` tenant
    would be work with no consumer."""
    spy = _ClientSpy()

    _factory(tmp_path, spy=spy).storage_for(StorageType.LOCAL)

    assert spy.calls == 0


def test_s3_without_a_configured_bucket_fails_loudly(tmp_path: Path) -> None:
    """Never a silent fall back to `LOCAL`: writing this tenant's photos to a disk nobody
    serves them from would look like success until the first person opened one."""
    with pytest.raises(StorageWriteError):
        _factory(tmp_path, bucket="   ").storage_for(StorageType.S3)


def test_read_for_local_resolves_to_the_disk_adapter(tmp_path: Path) -> None:
    reader = _factory(tmp_path).read_for(StorageType.LOCAL)

    assert isinstance(reader, LocalFileStorage)


def test_read_for_s3_refuses_without_instantiating_anything(tmp_path: Path) -> None:
    """Design D1, and the point of the whole two-port split.

    The spy proves the refusal happens before construction: no boto3 client is built, so the
    error is a property of the storage type and not the outcome of a failed attempt.
    """
    spy = _ClientSpy()

    with pytest.raises(LocalFileReadUnsupportedError):
        _factory(tmp_path, spy=spy).read_for(StorageType.S3)

    assert spy.calls == 0


def test_the_refusal_is_not_a_storage_write_error(tmp_path: Path) -> None:
    """A caller catching `StorageWriteError` (which becomes a `502`) must not swallow this: an
    `S3` tenant asking for local bytes is a `404`, not a backend outage."""
    with pytest.raises(LocalFileReadUnsupportedError):
        try:
            _factory(tmp_path).read_for(StorageType.S3)
        except StorageWriteError:  # pragma: no cover - would mean the hierarchy collapsed
            raise AssertionError("LocalFileReadUnsupportedError must not be a StorageWriteError")


def test_the_factory_holds_no_adapter_between_calls(tmp_path: Path) -> None:
    """Same posture as `SqlAlchemyPMSAdapterFactory`: an object that cached adapters would be
    the object that carries one tenant's resolution into another tenant's request."""
    factory = _factory(tmp_path)

    assert factory.storage_for(StorageType.LOCAL) is not factory.storage_for(StorageType.LOCAL)
