"""Resolves the PMS adapter for a property (ADR 0006 decision 7, design D1/D2).

**Why `infrastructure/`**: this is the only layer allowed to import a concrete adapter.
`tests/test_layering.py` fails an `app.integrations.infrastructure.*` import from `domain/` or
`application/`, so the port lives in `domain/ports.py` and the implementation here — the same
split `ReservationCsvParser` already uses. That is what lets a use case receive the factory by
constructor and stay free of `ChannexAdapter`, which is exactly what ADR 0006 asks for when it
says the use cases must never get an adapter injected as a singleton.

**Holds no session and caches no adapter.** A factory that kept a session would become the
object that carries one tenant's session into another tenant's resolution, which is the failure
`bind_session_to_tenant`'s guard exists to catch; a factory that cached adapters would keep a
decrypted credential alive past its use. Both are pinned by tests.
"""

from app.core.crypto import decrypt
from app.integrations.domain.entities import CredentialReadLog, PmsCredential
from app.integrations.domain.enums import (
    PMSProvider,
    PmsCredentialScope,
    credential_scope_for,
    supports_messaging,
)
from app.integrations.domain.errors import (
    MissingPmsCredentialError,
    PmsUnavailableError,
    PMSMessagingUnsupportedError,
)
from app.integrations.domain.ports import PMSAdapter, PMSMessagingPort
from app.integrations.infrastructure.channex.adapter import ChannexAdapter
from app.integrations.infrastructure.channex.client import ChannexClient
from app.integrations.infrastructure.mock_pms import MockPMSAdapter
from app.properties.domain.entities import Property
from app.integrations.domain.repositories import PmsCredentialRepository

DEFAULT_PROVIDER = PMSProvider.MOCK
"""What a property with no `pms_provider` resolves to.

The mock, so that the command, the suite and local startup keep depending on no configuration —
the property `specs/reservations.md` protects when it explains why the provider is a flag and
not a global setting.
"""


class SqlAlchemyPMSAdapterFactory:
    """Implements `PMSAdapterFactory`, resolving from a property's stored provider."""

    def __init__(
        self,
        *,
        credentials: PmsCredentialRepository,
        forced_provider: PMSProvider | None = None,
    ) -> None:
        self._credentials = credentials
        # The operator override of `pms_sync --provider`. Explicit, loud and per run — never a
        # value read from configuration, which is the shape ADR 0006 retired.
        self._forced_provider = forced_provider

    def supports_messaging(self, provider: PMSProvider) -> bool:
        """Pure: reads the provider and nothing else.

        No credential, no decryption, no audit row — which is the point. Resolving an adapter is
        an audited act (R4.2), so if the only way to ask "does this property have messaging?"
        were to resolve one, planning work would leave an audit trail of reads that never
        happened. `messaging-ai` needs to filter properties without paying that.
        """
        return supports_messaging(provider)

    def provider_for(self, property: Property) -> PMSProvider:
        """The provider that will actually be used, override included."""
        if self._forced_provider is not None:
            return self._forced_provider
        return property.pms_provider or DEFAULT_PROVIDER

    async def reservations_for(
        self, property: Property, *, read_log: CredentialReadLog | None = None
    ) -> PMSAdapter:
        return await self._build(property, self.provider_for(property), read_log)

    async def messaging_for(self, property: Property) -> PMSMessagingPort:
        provider = self.provider_for(property)
        if not self.supports_messaging(provider):
            raise PMSMessagingUnsupportedError(
                f"provider {provider.value} has no messaging API; "
                f"ask supports_messaging() before resolving"
            )
        # `PmsUnavailableError`, NOT `PMSMessagingUnsupportedError` — and the distinction is the
        # whole reason that error exists. Its docstring says it means a capability that
        # permanently does not exist, which is never retried; this branch is a capability that
        # DOES exist and simply has no adapter yet, which will be retried the day one lands.
        # Collapsing the two would make `supports_messaging() is True` and
        # `PMSMessagingUnsupportedError` coexist, which is a contradiction a caller cannot act on.
        #
        # The architecture panel of sections 4-5 caught this, and it is literally the same
        # mistake already fixed one method down in `_build`: "no adapter yet" is unavailability,
        # not absence of the feature.
        raise PmsUnavailableError(
            f"provider {provider.value} has a messaging API but no adapter implements "
            f"PMSMessagingPort yet (arrives with pms-beds24-adapter)"
        )

    async def _build(
        self, property: Property, provider: PMSProvider, read_log: CredentialReadLog | None
    ) -> PMSAdapter:
        if provider is PMSProvider.MOCK:
            return MockPMSAdapter()

        if provider is PMSProvider.CHANNEX:
            # Its key lives in the environment, which is the case rule 3 excludes from the
            # encryption obligation and rule 8 governs instead. So there is nothing to decrypt
            # and nothing to audit.
            from app.core.config import settings

            if not settings.channex_api_key.strip():
                raise MissingPmsCredentialError(
                    property_id=property.id,
                    provider=provider.value,
                    scope="environment",
                )
            return ChannexAdapter(
                ChannexClient(
                    api_key=settings.channex_api_key,
                    base_url=settings.channex_base_url,
                    max_pages=settings.channex_max_pages,
                    page_limit=settings.channex_page_limit,
                    timeout=settings.channex_timeout_seconds,
                )
            )

        # Beds24 and anything else whose credential is stored. The credential is resolved and
        # DECRYPTED before failing, deliberately: it makes the whole chain — lookup, scope,
        # decryption, audit — real and testable now instead of arriving untested with the
        # adapter, and it means a credential stored under a key that has since changed surfaces
        # here rather than on the day the adapter lands.
        credential = await self._require_credential(property, provider, read_log)
        decrypt(credential.secret)

        # `PmsUnavailableError`, not `MissingPmsCredentialError`: nothing is missing — the
        # credential is present and valid. What does not exist yet is the adapter, and this is
        # the error whose meaning is "this sync did not happen", which the CLI already maps to
        # exit code 3. Saying "missing credential" here would send an operator hunting for a
        # credential that is sitting right there.
        raise PmsUnavailableError(
            f"no adapter implements provider {provider.value} yet "
            f"(arrives with pms-beds24-adapter)"
        )

    async def _require_credential(
        self, property: Property, provider: PMSProvider, read_log: CredentialReadLog | None
    ) -> PmsCredential:
        scope = credential_scope_for(provider)
        if scope is None:
            raise MissingPmsCredentialError(
                property_id=property.id, provider=provider.value, scope="unknown"
            )

        credential = await self._credentials.get_for(
            property.tenant_id,
            provider,
            scope,
            property_id=property.id if scope is PmsCredentialScope.PROPERTY else None,
        )
        if credential is None:
            # Loud, never a fall back to the mock: that would report "created 0", which is
            # indistinguishable from a PMS that genuinely had nothing
            # (`specs/reservations.md` fixes this reasoning for `CHANNEX_API_KEY`).
            raise MissingPmsCredentialError(
                property_id=property.id, provider=provider.value, scope=scope.value
            )

        if read_log is not None:
            read_log.record(credential)
        return credential
