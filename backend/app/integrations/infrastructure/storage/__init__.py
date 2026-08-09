"""File storage adapters, and the factory that picks one from `TenantConfig.storage_type`.

**Why the factory is here and not in `domain/storage.py`**: resolving means importing
`LocalFileStorage` and `S3FileStorage`, and `domain/` may not import `infrastructure/` —
`tests/test_layering.py` fails the build over it. So the PORT (`FileStorageFactory`) is
declared in `domain/storage.py` and this is its implementation, the same split
`PMSAdapterFactory` (port in `domain/ports.py`) and `SqlAlchemyPMSAdapterFactory`
(implementation in `infrastructure/pms_factory.py`) already use in this package.

That split is what R1.2 rests on: a use case receives this factory by constructor and never
learns which backend is active.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.integrations.domain.storage import (
    FileStoragePort,
    LocalFileReadPort,
    LocalFileReadUnsupportedError,
    StorageWriteError,
)
from app.integrations.infrastructure.storage.local import (
    DEFAULT_SIGNED_URL_PREFIX,
    MEDIA_ROOT,
    LocalFileStorage,
)
from app.integrations.infrastructure.storage.s3 import S3FileStorage, build_s3_client
from app.tenants.domain.enums import StorageType

__all__ = [
    "ConfiguredFileStorageFactory",
    "LocalFileStorage",
    "MEDIA_ROOT",
    "S3FileStorage",
    "build_s3_client",
]


class ConfiguredFileStorageFactory:
    """Implements `FileStorageFactory`, resolving from a tenant's stored `storage_type` (R1.2).

    Holds no session and caches no adapter, for the reason `SqlAlchemyPMSAdapterFactory`
    already wrote down: an object that carried one tenant's state into another tenant's
    resolution is the failure the tenant guards exist to catch.

    `signing_key` is the HKDF-derived URL key (`derive_signing_key`), passed in rather than
    derived here so that deriving stays a pure function of `domain/` with its own tests.

    `s3_client_factory` defaults to `build_s3_client` and is only ever called for an `S3`
    tenant — constructing a boto3 client reads the credential chain, and doing that for a
    `LOCAL` tenant would be work with no consumer.
    """

    def __init__(
        self,
        *,
        signing_key: bytes,
        local_root: Path = MEDIA_ROOT,
        url_prefix: str = DEFAULT_SIGNED_URL_PREFIX,
        s3_bucket: str = "",
        s3_client_factory: Callable[[], Any] = build_s3_client,
    ) -> None:
        self._signing_key = signing_key
        self._local_root = local_root
        self._url_prefix = url_prefix
        self._s3_bucket = s3_bucket
        self._s3_client_factory = s3_client_factory

    def storage_for(self, storage_type: StorageType) -> FileStoragePort:
        if storage_type is StorageType.LOCAL:
            return self._local()
        if storage_type is StorageType.S3:
            if not self._s3_bucket.strip():
                # Loud, and never a silent fall back to `LOCAL`: writing this tenant's photos
                # to a disk nobody serves them from would look like success and be discovered
                # by the first person who opened one.
                raise StorageWriteError(
                    "storage_type is S3 but no bucket is configured for this deployment"
                )
            return S3FileStorage(bucket=self._s3_bucket, client=self._s3_client_factory())
        raise StorageWriteError(f"no storage adapter implements {storage_type!r}")

    def read_for(self, storage_type: StorageType) -> LocalFileReadPort:
        """The local read adapter, or `LocalFileReadUnsupportedError` for an `S3` tenant.

        The refusal happens **before anything is instantiated** — no boto3 client, no disk
        path — because the answer is a property of the storage type alone. That is design D1's
        mechanism: the factory refuses, rather than a port method that exists in order to
        fail.
        """
        if storage_type is not StorageType.LOCAL:
            raise LocalFileReadUnsupportedError(
                f"storage_type {storage_type.value} serves objects from the provider, so there "
                "is nothing to read through the application"
            )
        return self._local()

    def _local(self) -> LocalFileStorage:
        return LocalFileStorage(
            signing_key=self._signing_key,
            root=self._local_root,
            url_prefix=self._url_prefix,
        )
