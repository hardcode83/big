"""The `--provider` flag of `pms_sync` (R3, design D3, tasks 5.1-5.4).

No database and no network: these exercise argument parsing and adapter construction, which is
where the flag's whole contract lives.
"""

import pytest

from app.core.config import settings
from app.integrations.cli import pms_sync
from app.integrations.domain.errors import PmsUnavailableError
from app.integrations.infrastructure.channex.adapter import ChannexAdapter
from app.integrations.infrastructure.mock_pms import MockPMSAdapter


# --- Default (R3.1) ---


def test_the_default_is_the_mock_so_nothing_changes_for_anyone():
    """R3.1 is satisfied by construction, not by configuration: no flag, no Channex."""
    remaining, provider = pms_sync._extract_provider(["some-uuid", "30"])

    assert provider == pms_sync.MOCK_PROVIDER
    assert remaining == ["some-uuid", "30"]
    assert isinstance(pms_sync.build_adapter(provider), MockPMSAdapter)


def test_positional_arguments_survive_the_flag_in_any_position():
    for argv in (
        ["uuid", "30", "--provider", "channex"],
        ["--provider", "channex", "uuid", "30"],
        ["uuid", "--provider=channex", "30"],
    ):
        remaining, provider = pms_sync._extract_provider(argv)
        assert remaining == ["uuid", "30"], argv
        assert provider == "channex", argv


# --- Invalid values (R3.3) ---


@pytest.mark.parametrize("argv", [["uuid", "--provider", "beds24"], ["uuid", "--provider=oops"]])
def test_an_unknown_provider_is_refused(argv):
    with pytest.raises(ValueError, match="unknown provider"):
        pms_sync._extract_provider(argv)


def test_a_dangling_provider_flag_is_refused():
    with pytest.raises(ValueError, match="needs a value"):
        pms_sync._extract_provider(["uuid", "--provider"])


@pytest.mark.parametrize(
    "argv",
    [["uuid", "--provider", "beds24"], ["uuid", "--provider"], []],
)
def test_main_exits_non_zero_on_bad_arguments(argv, capsys):
    assert pms_sync.main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_usage_names_both_providers():
    assert "mock" in pms_sync.USAGE and "channex" in pms_sync.USAGE


# --- Missing credentials (R3.2) ---


def test_channex_without_a_key_refuses_instead_of_falling_back_to_the_mock(monkeypatch):
    """The failure that matters. A silent fallback would print "created 0, updated 0" — which
    is indistinguishable from a genuinely empty PMS, so a typo'd credential would look like a
    successful sync forever."""
    monkeypatch.setattr(settings, "channex_api_key", "  ", raising=False)

    with pytest.raises(PmsUnavailableError) as excinfo:
        pms_sync.build_adapter(pms_sync.CHANNEX_PROVIDER)

    assert "CHANNEX_API_KEY" in str(excinfo.value)


def test_channex_with_a_key_builds_the_real_adapter(monkeypatch):
    monkeypatch.setattr(settings, "channex_api_key", "a-real-looking-key", raising=False)

    adapter = pms_sync.build_adapter(pms_sync.CHANNEX_PROVIDER)

    assert isinstance(adapter, ChannexAdapter)


def test_the_mock_needs_no_credentials(monkeypatch):
    monkeypatch.setattr(settings, "channex_api_key", "", raising=False)
    assert isinstance(pms_sync.build_adapter(pms_sync.MOCK_PROVIDER), MockPMSAdapter)


def test_build_adapter_rejects_a_provider_it_does_not_know():
    with pytest.raises(ValueError, match="Unknown PMS provider"):
        pms_sync.build_adapter("beds24")


# --- The adapters are interchangeable (design D5, Liskov) ---


def test_both_adapters_expose_the_same_port_surface(monkeypatch):
    monkeypatch.setattr(settings, "channex_api_key", "a-real-looking-key", raising=False)
    mock = pms_sync.build_adapter(pms_sync.MOCK_PROVIDER)
    channex = pms_sync.build_adapter(pms_sync.CHANNEX_PROVIDER)

    for method in ("list_reservations", "get_reservation"):
        assert callable(getattr(mock, method))
        assert callable(getattr(channex, method))
