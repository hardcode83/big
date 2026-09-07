"""The composition root of the inbound receiver (`whatsapp-cloud-adapter` task 7.1, D9).

Its own file, and small on purpose: what it asserts is a *choice made by configuration*, so
every test here moves `settings` and none of them touches HTTP or the database. The receiver's
behaviour lives in `test_whatsapp_webhook.py`.
"""

import pytest

from app.core.config import settings
from app.messaging.api.dependencies import (
    get_whatsapp_inbound_provider,
    whatsapp_signing_secret,
)
from app.messaging.infrastructure.whatsapp_providers import MetaInboundAdapter


@pytest.fixture
def whatsapp_settings(monkeypatch: pytest.MonkeyPatch):
    """Move `whatsapp_provider`/`whatsapp_app_secret` without rebuilding `Settings`.

    `Settings` validates at construction, so building a second instance would need every
    other required variable present too. These two attributes are what the wiring reads, and
    `monkeypatch` restores them however the test ends.
    """

    def _set(*, provider: str, secret: str | None) -> None:
        monkeypatch.setattr(settings, "whatsapp_provider", provider)
        monkeypatch.setattr(settings, "whatsapp_app_secret", secret)

    return _set


def test_the_inbound_provider_is_metas_adapter() -> None:
    """Section 4's adapter, and it is the only implementer this change ships (D9)."""
    assert isinstance(get_whatsapp_inbound_provider(), MetaInboundAdapter)


def test_the_adapter_is_stateless_so_a_second_call_is_a_second_object() -> None:
    """Built per request, like `get_webhook_throttle`. Nothing is cached across requests."""
    first = get_whatsapp_inbound_provider()
    second = get_whatsapp_inbound_provider()

    assert first is not second


def test_meta_mode_verifies_against_the_configured_app_secret(whatsapp_settings) -> None:
    whatsapp_settings(provider="meta", secret="the-app-secret")

    assert whatsapp_signing_secret() == "the-app-secret"


def test_surrounding_whitespace_in_the_secret_is_stripped(whatsapp_settings) -> None:
    """A hand-edited `.env` must not produce a key nobody can reproduce."""
    whatsapp_settings(provider="meta", secret="  the-app-secret\n")

    assert whatsapp_signing_secret() == "the-app-secret"


@pytest.mark.parametrize("secret", [None, "", "   "])
def test_meta_mode_without_a_secret_fails_closed(whatsapp_settings, secret) -> None:
    """The second net behind `Settings`' own refusal to boot in this state.

    A blank secret is what section 4's `verify_signature` answers `False` to, so a
    half-configured deployment refuses every delivery instead of authenticating anyone who
    can compute an HMAC under an empty key.
    """
    whatsapp_settings(provider="meta", secret=secret)

    assert whatsapp_signing_secret() == ""


def test_mock_mode_has_no_inbound_door_even_if_a_secret_is_present(whatsapp_settings) -> None:
    """`settings.whatsapp_provider` is what selects, and this is the selection (task 7.1).

    A deployment in `mock` mode has no WhatsApp number of its own, so a signature it could
    verify would be one it has no business accepting: the reply would go to
    `MockWhatsAppAdapter` and never reach the guest, leaving a thread nobody answers.
    """
    whatsapp_settings(provider="mock", secret="the-app-secret")

    assert whatsapp_signing_secret() == ""


def test_the_provider_name_this_wiring_selects_on_is_metas(whatsapp_settings) -> None:
    """Pinned by value: the literal has to be the one `Settings` accepts, not a near-miss.

    `"Meta"`, `"whatsapp"` or `"meta_cloud"` would all typecheck and all silently close the
    door on a correctly configured deployment — a failure that looks like a broken signature.
    """
    from app.messaging.api.dependencies import WHATSAPP_META_PROVIDER

    assert WHATSAPP_META_PROVIDER == "meta"

    whatsapp_settings(provider=WHATSAPP_META_PROVIDER, secret="s")
    assert whatsapp_signing_secret() == "s"
