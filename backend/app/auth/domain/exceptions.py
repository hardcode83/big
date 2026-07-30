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
