"""Provider agnosticism, made verifiable (`object-storage-provisioning` R4, design D13).

The claim these guards defend is narrow and worth stating exactly: moving the photos from OCI
Object Storage to AWS S3, Cloudflare R2 or MinIO is **configuration**, not code. Two seams carry
it — `build_s3_client` takes an arbitrary `endpoint_url`, and `S3FileStorage` *receives* the
client it uses — and both already existed before this change. What is new is that provisioning a
real bucket makes it tempting to wire the provider in below the port, so these are the tests that
fail the day someone does.

Nothing here opens the network: `boto3.client` resolves its configuration locally and issues no
request, so the endpoint it was pointed at can be read straight off the object it returns.
"""

import ast
import tomllib
from pathlib import Path

import pytest

from app.cleaning.api.dependencies import get_file_storage_factory
from app.core.config import settings
from app.integrations.domain.storage import derive_signing_key
from app.integrations.infrastructure.storage import S3FileStorage
from app.tenants.domain.enums import StorageType

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_STORAGE = BACKEND_ROOT / "app" / "integrations" / "domain" / "storage.py"

#: One endpoint per non-AWS provider of the matrix in
#: `docs/adr/0008-object-storage-provider-dev.md`. Parametrised rather than asserted once
#: because "agnostic" is a claim about the set, and a single OCI case would pass just as well
#: for an implementation that special-cased OCI.
PROVIDER_ENDPOINTS = [
    ("oci", "https://ns.compat.objectstorage.eu-frankfurt-1.oraclecloud.com", "eu-frankfurt-1"),
    ("r2", "https://acct.r2.cloudflarestorage.com", "auto"),
    ("minio", "http://minio.internal:9000", "us-east-1"),
]

#: Top-level packages that would mean a provider had been wired below the port. Checked as
#: **imports**, which is the only form of provider knowledge that can actually do anything.
PROVIDER_SDKS = ("boto3", "botocore", "oci", "azure", "google", "minio")

#: Hosts that belong to one provider and to no other. Unlike a bare provider name these cannot
#: appear by accident, so they are safe to scan for as text.
PROVIDER_HOSTS = (
    "amazonaws.com",
    "oraclecloud.com",
    "cloudflarestorage.com",
    "compat.objectstorage",
    "customer-oci.com",
)

#: Store configuration the port must not know about, checked against the module's **defined
#: symbols** rather than its text. `SIGNATURE_VERSION` — our own URL-signing version prefix —
#: is why: the vocabulary of an object store overlaps the vocabulary of a signing scheme, and a
#: text scan cannot tell a `signature_version` passed to botocore from a constant of ours that
#: happens to share the word.
PROVIDER_CONFIG_SYMBOLS = (
    "endpoint_url",
    "region_name",
    "addressing_style",
    "bucket",
    "access_key_id",
    "secret_access_key",
)


@pytest.mark.parametrize(("provider", "endpoint", "region"), PROVIDER_ENDPOINTS)
def test_the_factory_points_the_client_at_whatever_endpoint_is_configured(
    monkeypatch: pytest.MonkeyPatch, provider: str, endpoint: str, region: str
) -> None:
    """R4.4 — the test that fails the day someone wires a provider below the port.

    It goes through `get_file_storage_factory`, not through a hand-built factory, because the
    property under test is that *the deployment's own wiring* carries an arbitrary endpoint all
    the way to the client. A factory constructed here with the right arguments would prove only
    that the arguments exist.
    """
    monkeypatch.setattr(settings, "s3_bucket", f"autohostai-{provider}-media")
    monkeypatch.setattr(settings, "s3_region", region)
    monkeypatch.setattr(settings, "s3_endpoint_url", endpoint)

    storage = get_file_storage_factory(derive_signing_key("s" * 64)).storage_for(StorageType.S3)

    assert isinstance(storage, S3FileStorage)
    assert storage._client.meta.endpoint_url == endpoint
    assert storage._client.meta.region_name == region


def test_the_storage_port_imports_no_provider_sdk() -> None:
    """R4.1, first half — the form of provider knowledge that can actually do something.

    Parsed rather than grepped, so `from boto3 import client as c` is caught too, and so a
    provider named in prose does not read as a dependency. `tests/test_layering.py` enforces the
    same rule for the framework packages; this extends it to the store's own SDKs.
    """
    tree = ast.parse(DOMAIN_STORAGE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    offenders = sorted(imported & set(PROVIDER_SDKS))
    assert not offenders, f"domain/storage.py imports a provider SDK: {offenders}"


def test_the_storage_port_hardcodes_no_provider_host() -> None:
    """R4.1, second half — a provider host in the port would decide the provider for everyone.

    Scanned as text because a host string cannot appear by accident. Bare provider *names* are
    deliberately not scanned for: `S3` is the value of `StorageType` and the name of the
    protocol the port is written against (`app/tenants/domain/enums.py`), "oracle" is used here
    in its English sense ("an existence oracle over the storage keyspace"), and the file's one
    mention of Cloudflare is about the ingress tunnel, which has nothing to do with where the
    photos live. A guard over those words would fail on prose while missing real coupling.
    """
    source = DOMAIN_STORAGE.read_text(encoding="utf-8").lower()

    offenders = sorted(host for host in PROVIDER_HOSTS if host in source)
    assert not offenders, f"domain/storage.py hardcodes a provider host: {offenders}"


def test_the_storage_port_defines_no_store_configuration() -> None:
    """R4.1, third half — the port must not know a store has an endpoint, a region or a bucket.

    Checked against the module's **defined symbols**, not its text: `SIGNATURE_VERSION` here is
    our own URL-signing version prefix, and a text scan cannot tell it from botocore's
    `signature_version`. What matters is whether the port declares such a thing, not whether a
    docstring says the word.
    """
    import app.integrations.domain.storage as port

    names = {name.lower() for name in dir(port)}
    for name in dir(port):
        member = getattr(port, name)
        if isinstance(member, type) or callable(member):
            names.update(attribute.lower() for attribute in dir(member))

    offenders = sorted(symbol for symbol in PROVIDER_CONFIG_SYMBOLS if symbol in names)
    assert not offenders, f"domain/storage.py declares store configuration: {offenders}"


def test_the_backend_declares_no_oci_sdk_dependency() -> None:
    """R4.2 — boto3 pointed at an endpoint is the only client, in every environment.

    An OCI SDK in `dependencies` would make the provider a build-time fact of the deployed
    image; in the dev group it would make the suite green while the image diverged — the trap
    `boto3`, `httpx` and `cryptography` each fell into once, recorded in `pyproject.toml`.
    """
    with open(BACKEND_ROOT / "pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    declared = list(pyproject["project"]["dependencies"])
    for group in pyproject.get("dependency-groups", {}).values():
        declared.extend(item for item in group if isinstance(item, str))

    offenders = [item for item in declared if _distribution_name(item).startswith("oci")]
    assert not offenders, f"an OCI SDK is declared as a dependency: {offenders}"


def test_no_module_under_app_imports_an_oci_sdk() -> None:
    """R4.2, the other half: a dependency can also arrive transitively and be imported anyway.

    Scans the source rather than the import graph, so a module that is never imported by the
    suite is covered too.
    """
    offenders = []
    for module in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("import oci", "from oci ")) or stripped.startswith("from oci."):
                offenders.append(f"{module.relative_to(BACKEND_ROOT)}:{number}")

    assert not offenders, f"the OCI SDK is imported in production code: {offenders}"


def test_the_two_seams_that_make_agnosticism_possible_are_still_there() -> None:
    """R4.3 — asserted as signatures, because both are load-bearing and both are one edit away.

    `build_s3_client` accepting an arbitrary `endpoint_url` is what makes a provider switch
    configuration; `S3FileStorage` receiving its client is what keeps the adapter from reading
    a credential chain in its constructor — and therefore testable without a cloud account.
    """
    import inspect

    from app.integrations.infrastructure.storage import build_s3_client

    builder = inspect.signature(build_s3_client)
    assert "endpoint_url" in builder.parameters
    assert "region_name" in builder.parameters

    adapter = inspect.signature(S3FileStorage.__init__)
    assert "client" in adapter.parameters
    assert "bucket" in adapter.parameters


def _distribution_name(requirement: str) -> str:
    name = requirement.strip().lower()
    for separator in ("[", "<", ">", "=", "!", "~", ";", " "):
        name = name.split(separator, 1)[0]
    return name
