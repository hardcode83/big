"""Provider vocabulary for per-property PMS resolution (ADR 0006 decision 7, R2).

`str, enum.Enum` with the value identical to the name, which is this repo's shape for a domain
enum (`app/properties/domain/enums.py`). Native Postgres types back them; there is no
`String` + `CheckConstraint` anywhere in this schema.
"""

import enum


class PMSProvider(str, enum.Enum):
    """Which PMS a property talks to.

    Replaces PRD §22's single `PMS_PROVIDER` environment variable, which ADR 0006 retired
    before any code read it: a global selector cannot express two providers coexisting, and
    that happens in both futures the ADR names — the migration window to Channex, where some
    properties have moved and others have not, and the SaaS phase, where each client arrives
    with the PMS they already pay for.

    `MOCK` is a first-class member, not a testing hack: it is the MVP's default and what the
    suite and local startup run against, so a property with no provider resolves to it.

    Deliberately NOT the full list of the eleven providers ADR 0006 evaluated: `OCTORATE` joins
    the day it is worth storing a credential for one.

    A member is **not** a promise that an adapter exists. `BEDS24` is here before its adapter
    (which arrives with `pms-beds24-adapter`) precisely so its account credential can be
    provisioned and rotated first — the credential is the long-lived thing, the adapter is code.
    Resolving such a property fails with `PmsUnavailableError` naming the gap, never by silently
    falling back to the mock.
    """

    MOCK = "MOCK"
    CHANNEX = "CHANNEX"
    BEDS24 = "BEDS24"


class PmsCredentialScope(str, enum.Enum):
    """What a stored credential grants access to.

    The three granularities rule 3 of `steering/security.md` names after ADR 0006 widened it,
    and the reason the credentials live in their own table rather than in columns on
    `Property`: ADR 0006's own text says "`Property` guarda su proveedor y sus credenciales"
    and then, two paragraphs later, that not all credentials are per-property. The measurement
    settles it — Beds24's real credential is an **account** refresh token
    (`docs/beds24-spike.md`), and Channex's is an account API key.

    **`ACCOUNT` is the dangerous one, not the mild one.** A property credential grants access
    to one flat; an account credential grants **write** access to every property of that
    account — calendar, pricing and messaging alike. `ORGANIZATION` is wider still: Beds24's
    partner model issues one token for N client accounts. Anything that ranks these by blast
    radius must rank them in this order and not by how specific the name sounds.
    """

    PROPERTY = "PROPERTY"
    ACCOUNT = "ACCOUNT"
    ORGANIZATION = "ORGANIZATION"


# Which providers have a messaging API at all. A fact about the PROVIDER, not about a property
# or a credential, which is what lets `supports_messaging` be pure.
#
# ADR 0006 measured this across eleven providers: Avantio and ICNEA have none, Smoobu's
# Booking.com half is broken. None of those has an adapter yet, so this map looks unanimous
# today and will not stay that way — which is the entire reason the capability is a lookup
# rather than an assumption.
_MESSAGING_SUPPORT: dict[PMSProvider, bool] = {
    PMSProvider.MOCK: False,
    PMSProvider.CHANNEX: False,
    PMSProvider.BEDS24: True,
}

# Which scope each provider's credential lives at — measured, not assumed. Beds24's real
# credential is an ACCOUNT refresh token (`docs/beds24-spike.md`); Channex authenticates with an
# account API key that lives in the ENVIRONMENT, so it needs no stored credential at all.
_CREDENTIAL_SCOPE: dict[PMSProvider, PmsCredentialScope | None] = {
    PMSProvider.MOCK: None,
    PMSProvider.CHANNEX: None,
    PMSProvider.BEDS24: PmsCredentialScope.ACCOUNT,
}


def supports_messaging(provider: PMSProvider) -> bool:
    """Whether the provider has a messaging API at all. A fact about the PROVIDER."""
    return _MESSAGING_SUPPORT.get(provider, False)


def credential_scope_for(provider: PMSProvider) -> PmsCredentialScope | None:
    """At which granularity this provider's credential lives, or `None` if it needs none.

    **In `domain/` and not beside the factory**, which is where both maps were first written.
    They are facts about a provider, not infrastructure, and three callers outside that module
    need them: the factory, the grouped sync (which may only group a provider whose credential is
    account-wide) and the credentials command (which must refuse coordinates the resolver will
    never read). `application/` cannot import `infrastructure/`, so leaving them there would have
    forced either a layering violation or a duplicated map that drifts.
    """
    return _CREDENTIAL_SCOPE.get(provider)

