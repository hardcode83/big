class AuthDomainError(Exception):
    """Base error for the auth domain."""


class InvalidCredentialsError(AuthDomainError):
    """Raised for every failed authentication, whatever the underlying reason.

    R1.4 requires the caller cannot tell an unknown email from a wrong password
    from a disabled account, so this error must stay deliberately undifferentiated.

    ASSUMPTION: the PRD does not say how to answer an INACTIVE or SUSPENDED
    account. It is unified with a wrong password so the response cannot be used to
    enumerate users or probe account state.
    """


class InvalidTokenError(AuthDomainError):
    pass


class TokenTypeMismatchError(InvalidTokenError):
    """A refresh token presented where an access token is expected, or vice versa (R2.5)."""


class SessionReuseDetectedError(AuthDomainError):
    """An already-used refresh token was presented again (R2.2).

    ASSUMPTION: PRD §22 requires refresh token rotation without defining the
    response to reuse. Reuse is treated as evidence of theft, so the whole token
    family is revoked rather than just the token presented.
    """


class TooManyAttemptsError(AuthDomainError):
    """Per-IP login attempt limit exceeded (R5.1)."""


class PasswordTooLongError(AuthDomainError):
    """Longer than bcrypt's 72-byte input limit; refused instead of truncated (R1.3)."""


# --- self-service password and recovery (`auth-account-recovery`) -------------------


class PasswordPolicyError(AuthDomainError):
    """The chosen password is under the minimum length (R1.5, design D4).

    The over-72-bytes half of the policy raises `PasswordTooLongError` instead, which
    already existed and already answers `422`: two errors for one rule would be two
    mappings to keep in step for no gain.

    Its message names the rule that was broken and never echoes the password.
    """


class PasswordUnchangedError(AuthDomainError):
    """The new password is byte-identical to the current one (R1.7).

    Refused because a successful change revokes every session of the user: accepting it
    would drop all their sessions without rotating any credential.
    """


class InvalidRecoveryTokenError(AuthDomainError):
    """The recovery token cannot be spent, whatever the reason (R3.3).

    Deliberately undifferentiated: unknown, already used, expired, revoked, and an account
    or tenant that stopped being ACTIVE all answer the same, so the endpoint cannot be used
    to probe which tokens exist.

    **Takes no argument, and that is the enforcement.** The API handler renders
    `str(exc)` into the response body, so a message chosen per raise site would be a
    per-cause channel in the one response R3.3 requires to be identical — and this error
    will have about six raise sites. `InvalidCredentialsError` keeps the same property by
    repeating one string at five call sites; that is convention, and convention is what a
    sixth call site breaks. A constructor that accepts nothing cannot be handed
    `f"token {token} not found"`, which also closes the R4.3 route by which a live token
    could reach a `401` body. Same reasoning as `recovery_messages.STORED_RECOVERY_BODY`,
    which takes no argument for exactly this reason.

    Not a subclass of `InvalidTokenError`, which is about the JWTs of `auth-tenancy`: a
    caller catching that one should not silently start catching this.
    """

    MESSAGE = "Invalid or expired recovery token"

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)


class PasswordChangeRequiredError(AuthDomainError):
    """The account still carries a temporary password and must change it first (R5.4).

    Answers `403 PASSWORD_CHANGE_REQUIRED` on every authenticated route but the three
    that let the holder get out of the state (design D6).
    """


# --- user administration (`user-management`) ---------------------------------------


class UserNotFoundError(AuthDomainError):
    """No such user IN THE ACTING TENANT (user-management R7.1).

    Deliberately does not distinguish "does not exist anywhere" from "exists in another
    tenant": both answer `404`, so the response never reveals that a resource exists.
    That is the R4.3 criterion `auth-tenancy` declared out of its own scope because all
    four of its endpoints were self-referential.
    """


class EmailAlreadyExistsError(AuthDomainError):
    """The normalised address is taken somewhere in the installation (R1.4).

    Answers `409`. That this leaks "the address exists somewhere" is inherent to the
    global uniqueness of ADR 0005; the message must not say under WHICH tenant.
    """


class SelfRoleChangeError(AuthDomainError):
    """An actor tried to change their own role or status (R3.5, design D5, D19).

    A self-demotion leaves the tenant with nobody who can administer it and there is no
    endpoint back. Covers `DELETE` too, which is a status change (design D19).
    """


class LastOwnerError(AuthDomainError):
    """The operation would leave the tenant without an ACTIVE `TENANT_OWNER` (R3.6)."""


class UnassignableRoleError(AuthDomainError):
    """`SUPER_ADMIN` cannot be granted through the API (R1.6).

    Its powers in PRD §6 are global, not the operation of one tenant, and cross-tenant
    visibility is deferred to `saas-cross-tenant`. Granting it from inside a tenant would
    pre-empt that decision with a role whose scope this capability cannot bound.
    """
