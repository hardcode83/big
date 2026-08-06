"""The `--provider` flag of `pms_sync` (R3, design D3, tasks 5.1-5.4).

No database and no network: these exercise argument parsing and adapter construction, which is
where the flag's whole contract lives.
"""

import pytest

from app.core.config import settings
from app.integrations.cli import pms_sync
from app.integrations.domain.errors import PmsUnavailableError
from app.integrations.domain.enums import PMSProvider
from app.integrations.domain.ports import PMSAdapter, PMSAdapterFactory, PMSMessagingPort
from app.integrations.infrastructure.channex.client import ChannexClient
from app.integrations.infrastructure.pms_factory import SqlAlchemyPMSAdapterFactory
from app.integrations.infrastructure.channex.adapter import ChannexAdapter
from app.integrations.infrastructure.mock_pms import MockPMSAdapter


# --- Default (R3.1) ---


_A_CLIENT = ChannexClient(
    api_key="a-real-looking-key",
    base_url="https://staging.channex.io/api/v1",
    max_pages=1,
    page_limit=1,
)


def test_no_flag_means_each_property_resolves_its_own_provider():
    """R2.5. The flag's DEFAULT is `mock`, and that is deliberately NOT an override.

    Treating the default as one would pin the whole portfolio to the mock and report "created 0"
    against a real PMS — indistinguishable from an empty PMS, which is exactly the confusion
    `specs/reservations.md` refuses elsewhere. `None` means "let each property decide".
    """
    remaining, provider = pms_sync._extract_provider(["some-uuid", "30"])

    assert provider == pms_sync.MOCK_PROVIDER
    assert pms_sync._forced_provider(provider) is None


@pytest.mark.parametrize(
    ("flag", "expected"),
    [("channex", PMSProvider.CHANNEX), ("beds24", PMSProvider.BEDS24)],
)
def test_an_explicit_flag_becomes_an_override(flag, expected):
    assert pms_sync._forced_provider(flag) is expected


def test_the_flag_vocabulary_comes_from_the_enum():
    """One vocabulary, not two that can drift.

    `PROVIDERS` used to be a hand-written tuple, which is how it ended up missing `beds24` — a
    provider the factory knows and the flag would have refused.
    """
    assert set(pms_sync.PROVIDERS) == {member.value.lower() for member in PMSProvider}


def test_an_unknown_provider_is_refused_without_echoing_it():
    """A rejected value must never be printed: `--provider=<pasted-api-key>` is a plausible
    fumble, and the error message is a plain-text sink."""
    secret_looking = "sk-live-9f8a7b6c5d4e3f2a1b0c"

    with pytest.raises(ValueError) as excinfo:
        pms_sync._forced_provider(secret_looking)

    assert secret_looking not in str(excinfo.value)


# --- The adapters remain interchangeable (design D5, Liskov) ---


def test_the_port_surface_is_read_from_the_port_not_hardcoded():
    """Derive the surface from `PMSAdapter` itself, the idiom of `tests/test_unit_of_work.py`.

    **This idiom only became sound in this change** (design D10). `vars()` returns a class's
    `__dict__`, which holds methods but NOT bare annotations: while the port declared
    `unmappable_rows: list[str]`, that member lived in `__annotations__` and every `vars()`-based
    check silently skipped it — the one member whose absence caused a silent wrong answer was the
    one the idiom could not see.
    """
    port_methods = {name for name in vars(PMSAdapter) if not name.startswith("_")}
    assert port_methods == {"list_reservations", "get_reservation"}
    assert [
        name for name in getattr(PMSAdapter, "__annotations__", {}) if not name.startswith("_")
    ] == []

    for adapter in (MockPMSAdapter(), ChannexAdapter(_A_CLIENT)):
        for name in port_methods:
            assert callable(getattr(adapter, name))


def test_neither_adapter_claims_the_messaging_port():
    """A provider without messaging implements `PMSAdapter` and simply not `PMSMessagingPort`.

    That is ADR 0006 decision 3: most evaluated providers have no messaging API, so a single
    Protocol would force them to implement it by raising, which is the Liskov violation
    `steering/backend-architecture.md:108` forbids. Checked structurally rather than with
    `isinstance` — the ports are plain `Protocol`s and making one `runtime_checkable` to satisfy
    a test would change production code to fit the test.
    """
    assert {name for name in vars(PMSMessagingPort) if not name.startswith("_")} == set(), (
        "PMSMessagingPort is empty in this change on purpose; its methods arrive with "
        "pms-beds24-adapter"
    )

    for adapter in (MockPMSAdapter(), ChannexAdapter(_A_CLIENT)):
        for name in ("get_messages", "send_message"):
            assert not hasattr(adapter, name)


def test_the_factory_conforms_to_its_port():
    """The factory is what the use cases depend on, so its surface is a contract too."""
    port_members = {name for name in vars(PMSAdapterFactory) if not name.startswith("_")}
    assert port_members == {"supports_messaging", "provider_for", "reservations_for", "messaging_for"}

    for name in port_members:
        assert callable(getattr(SqlAlchemyPMSAdapterFactory, name))
