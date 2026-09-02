"""JWT issuing and verification (R1.5, R1.6, R2.5, design D3)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.domain.enums import UserRole
from app.auth.domain.exceptions import InvalidTokenError, TokenTypeMismatchError
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.config import JWT_ALGORITHM

SECRET = "s" * 64
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _codec(**overrides) -> JwtTokenCodec:
    values = {"secret": SECRET, "access_minutes": 15, "refresh_days": 7}
    values.update(overrides)
    return JwtTokenCodec(**values)


def _access(codec: JwtTokenCodec, now: datetime | None = None, **overrides) -> str:
    values = {
        "user_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "role": UserRole.PROPERTY_MANAGER,
        "family_id": uuid.uuid4(),
        "now": now or datetime.now(UTC),
    }
    values.update(overrides)
    return codec.issue_access(**values)


def _refresh(codec: JwtTokenCodec, now: datetime | None = None, **overrides) -> str:
    values = {
        "user_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "role": UserRole.CLEANER,
        "session_id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "now": now or datetime.now(UTC),
    }
    values.update(overrides)
    return codec.issue_refresh(**values)


def _raw_claims(token: str) -> dict:
    """Inspect the payload without validating time.

    PyJWT rejects a token whose `iat` is in the future (ImmatureSignatureError),
    and some cases below issue tokens at a fixed instant that may be ahead of the
    wall clock. Temporal validation is exercised through the codec itself, in
    test_an_expired_token_is_rejected.
    """
    return jwt.decode(
        token,
        SECRET,
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": False, "verify_iat": False},
    )


def test_access_token_carries_every_claim_required_by_r1_5() -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    codec = _codec()

    token = _access(codec, user_id=user_id, tenant_id=tenant_id, role=UserRole.TENANT_OWNER)

    claims = _raw_claims(token)
    assert claims["sub"] == str(user_id)
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["role"] == UserRole.TENANT_OWNER.value
    assert claims["type"] == "access"
    assert uuid.UUID(claims["jti"])
    assert claims["iat"] < claims["exp"]
    # design D18: without `fam` on the access token, logout cannot satisfy R2.3.
    assert uuid.UUID(claims["fam"])


def test_the_access_token_names_the_family_it_was_issued_with() -> None:
    codec = _codec()
    family_id = uuid.uuid4()

    claims = codec.decode_access(_access(codec, family_id=family_id))

    assert claims.family_id == family_id


def test_refresh_token_also_carries_the_family() -> None:
    session_id, family_id = uuid.uuid4(), uuid.uuid4()
    codec = _codec()

    token = _refresh(codec, session_id=session_id, family_id=family_id)

    claims = _raw_claims(token)
    assert claims["type"] == "refresh"
    # The jti IS the session row id (design D5), so the token itself never needs storing.
    assert claims["jti"] == str(session_id)
    assert claims["fam"] == str(family_id)


def test_token_lifetimes_come_from_configuration() -> None:
    codec = _codec(access_minutes=15, refresh_days=7)

    access_claims = _raw_claims(_access(codec, now=NOW))
    refresh_claims = _raw_claims(_refresh(codec, now=NOW))

    assert access_claims["exp"] - access_claims["iat"] == int(timedelta(minutes=15).total_seconds())
    assert refresh_claims["exp"] - refresh_claims["iat"] == int(timedelta(days=7).total_seconds())


def test_access_ttl_seconds_matches_the_configured_lifetime() -> None:
    assert _codec(access_minutes=15).access_ttl_seconds == 900


def test_decoding_returns_the_claims_as_domain_types() -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    codec = _codec()

    claims = codec.decode_access(
        _access(codec, user_id=user_id, tenant_id=tenant_id, role=UserRole.TECHNICIAN)
    )

    assert claims.user_id == user_id
    assert claims.tenant_id == tenant_id
    assert claims.role is UserRole.TECHNICIAN
    assert isinstance(claims.token_id, uuid.UUID)


def test_access_token_issued_with_a_null_tenant_round_trips_as_none() -> None:
    """`super-admin-identity` R2.1, design D4: `SUPER_ADMIN` carries no tenant."""
    codec = _codec()

    token = _access(codec, tenant_id=None, role=UserRole.SUPER_ADMIN)

    assert _raw_claims(token)["tenant_id"] is None
    assert codec.decode_access(token).tenant_id is None


def test_refresh_token_issued_with_a_null_tenant_round_trips_as_none() -> None:
    codec = _codec()

    token = _refresh(codec, tenant_id=None, role=UserRole.SUPER_ADMIN)

    assert _raw_claims(token)["tenant_id"] is None
    assert codec.decode_refresh(token).tenant_id is None


def test_a_non_string_non_null_tenant_id_claim_is_still_rejected() -> None:
    """`_optional_uuid_claim` accepts `None`, but nothing else that is not a `str`."""
    codec = _codec()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": 123,
            "role": UserRole.SUPER_ADMIN.value,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "fam": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
        },
        SECRET,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        codec.decode_access(token)


def test_a_refresh_token_is_rejected_where_an_access_token_is_expected() -> None:
    codec = _codec()

    with pytest.raises(TokenTypeMismatchError):
        codec.decode_access(_refresh(codec))


def test_an_access_token_is_rejected_where_a_refresh_token_is_expected() -> None:
    codec = _codec()

    with pytest.raises(TokenTypeMismatchError):
        codec.decode_refresh(_access(codec))


def test_a_token_signed_with_another_key_is_rejected() -> None:
    forged = JwtTokenCodec(secret="d" * 64, access_minutes=15, refresh_days=7)

    with pytest.raises(InvalidTokenError):
        _codec().decode_access(_access(forged))


def test_an_expired_token_is_rejected() -> None:
    codec = _codec()
    long_ago = datetime.now(UTC) - timedelta(hours=2)

    with pytest.raises(InvalidTokenError):
        codec.decode_access(_access(codec, now=long_ago))


def test_a_malformed_token_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        _codec().decode_access("not.a.jwt")


def test_an_unsigned_token_is_rejected() -> None:
    # The classic JWT trap: alg=none. Pinning algorithms=["HS256"] is what stops it.
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "role": UserRole.SUPER_ADMIN.value,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "fam": str(uuid.uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(InvalidTokenError):
        _codec().decode_access(unsigned)


def test_a_token_without_a_type_claim_is_rejected() -> None:
    typeless = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "role": UserRole.CLEANER.value,
            "jti": str(uuid.uuid4()),
            "fam": str(uuid.uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
        },
        SECRET,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        _codec().decode_access(typeless)


def test_a_token_with_an_unknown_role_is_rejected() -> None:
    bogus = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "role": "GOD_MODE",
            "type": "access",
            "jti": str(uuid.uuid4()),
            "fam": str(uuid.uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
        },
        SECRET,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        _codec().decode_access(bogus)


@pytest.mark.parametrize("token_type", ["refresh", "access"])
def test_a_token_without_a_family_is_rejected(token_type: str) -> None:
    # Both kinds carry `fam` now: the refresh needs it to identify its lineage, and
    # the access token needs it so logout can close the session (design D18).
    familyless = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "role": UserRole.CLEANER.value,
            "type": token_type,
            "jti": str(uuid.uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(days=7)).timestamp()),
        },
        SECRET,
        algorithm=JWT_ALGORITHM,
    )

    decode = _codec().decode_refresh if token_type == "refresh" else _codec().decode_access
    with pytest.raises(InvalidTokenError):
        decode(familyless)


@pytest.mark.parametrize("bogus_tenant", [123, {}, [], True])
def test_a_non_string_identifier_claim_is_rejected_as_invalid_not_as_a_crash(
    bogus_tenant: object,
) -> None:
    # uuid.UUID(123) raises AttributeError, which would surface as a 500 instead
    # of the 401 R2.5 requires for a malformed token.
    #
    # `None` is deliberately NOT in this list any more (`super-admin-identity` design D4):
    # it is the legitimate `SUPER_ADMIN` value for this one claim, asserted by
    # `test_access_token_issued_with_a_null_tenant_round_trips_as_none` above. Every other
    # value here is still rejected — `_optional_uuid_claim` only widens what counts as
    # "present", not what counts as "a valid identifier".
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": bogus_tenant,
            "role": UserRole.CLEANER.value,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "fam": str(uuid.uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
        },
        SECRET,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        _codec().decode_access(token)


@pytest.mark.parametrize("claim", ["iat", "exp"])
@pytest.mark.parametrize("bogus", [10**20, -(10**20), "soon", None, True, {}, [], [1, 2]])
def test_an_out_of_range_or_non_numeric_timestamp_is_rejected(claim: str, bogus: object) -> None:
    """R2.5 names malformed tokens as a 401 path, so none of these may reach a 500.

    Two different crash routes: `datetime.fromtimestamp(10**20)` raises OverflowError
    in our own conversion, while a dict or list raises TypeError inside PyJWT's
    validation, which catches only ValueError.
    """
    claims = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": UserRole.CLEANER.value,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "fam": str(uuid.uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
    }
    claims[claim] = bogus
    token = jwt.encode(claims, SECRET, algorithm=JWT_ALGORITHM)

    with pytest.raises(InvalidTokenError):
        _codec().decode_access(token)


def test_two_access_tokens_have_different_ids() -> None:
    codec = _codec()

    first = codec.decode_access(_access(codec))
    second = codec.decode_access(_access(codec))

    assert first.token_id != second.token_id
