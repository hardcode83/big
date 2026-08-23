"""URL signing: HKDF derivation and HMAC verification (task 1.3, design D6, R3.4/R3.5).

Everything under test is a pure function with `now` as a parameter, which is what lets expiry
be exercised without sleeping an hour.
"""

import hashlib
import hmac

import pytest

from app.integrations.domain.storage import (
    SIGNATURE_LENGTH,
    SIGNATURE_VERSION,
    SIGNED_URL_TTL_SECONDS,
    SIGNING_KEY_BYTES,
    SIGNING_KEY_INFO,
    InvalidSignatureError,
    clamp_expires_in,
    derive_signing_key,
    sign_storage_key,
    verify_signed_key,
)

SECRET = "s" * 64
KEY = "tenants/11111111-1111-1111-1111-111111111111/cleaning-tasks/t/p.jpg"
NOW = 1_800_000_000
EXPIRY = NOW + 3600


def _signature(key: str = KEY, expiry: int = EXPIRY) -> str:
    return sign_storage_key(signing_key=derive_signing_key(SECRET), key=key, expiry=expiry)


def _verify(**overrides) -> None:
    arguments = {
        "signing_key": derive_signing_key(SECRET),
        "key": KEY,
        "expiry": EXPIRY,
        "signature": _signature(),
        "now": NOW,
    }
    arguments.update(overrides)
    verify_signed_key(**arguments)


class TestDerivation:
    def test_the_derived_key_is_not_the_jwt_secret(self) -> None:
        """Domain separation is the whole point of D6: signing a photo URL must never be able
        to produce or verify a JWT."""
        derived = derive_signing_key(SECRET)

        assert derived != SECRET.encode("utf-8")
        assert len(derived) == SIGNING_KEY_BYTES

    def test_it_is_deterministic(self) -> None:
        assert derive_signing_key(SECRET) == derive_signing_key(SECRET)

    def test_a_different_secret_gives_a_different_key(self) -> None:
        assert derive_signing_key(SECRET) != derive_signing_key("t" * 64)

    def test_it_is_rfc_5869_hkdf_with_the_declared_info(self) -> None:
        """Recomputed independently, so a refactor of the ten-line HKDF cannot drift.

        One expand round is enough because the output is exactly one SHA-256 block.
        """
        prk = hmac.new(b"", SECRET.encode("utf-8"), hashlib.sha256).digest()
        expected = hmac.new(prk, SIGNING_KEY_INFO + b"\x01", hashlib.sha256).digest()

        assert derive_signing_key(SECRET) == expected[:SIGNING_KEY_BYTES]


class TestSigning:
    def test_the_signature_is_over_the_length_prefixed_versioned_payload(self) -> None:
        """Recomputed independently, so the payload encoding cannot drift unnoticed.

        This is the assertion that fails if anyone goes back to a plain `v|key|expiry` concat:
        the length prefix is the whole of the unambiguity fix, and it is invisible from the
        outside — the signature is opaque, so nothing else would notice its removal.
        """
        signing_key = derive_signing_key(SECRET)
        payload = f"{SIGNATURE_VERSION}|{len(KEY)}|{KEY}|{EXPIRY}".encode("utf-8")

        expected = hmac.new(signing_key, payload, hashlib.sha256).hexdigest()[:SIGNATURE_LENGTH]

        assert sign_storage_key(signing_key=signing_key, key=KEY, expiry=EXPIRY) == expected

    def test_the_payload_format_is_versioned_v2(self) -> None:
        """The encoding changed, so the version inside the signature changed with it — which is
        what the prefix is for (D6). Nothing has reached production, so no live URL dies here;
        the point is that a payload change without a bump is the habit that eventually rotates
        a scheme by accident."""
        assert SIGNATURE_VERSION == "v2"

    def test_a_float_expiry_is_refused(self) -> None:
        """`str(1.8e9)` renders in scientific notation, producing a signature that could never
        verify again — a failure that would only appear once, in production, at one timestamp."""
        with pytest.raises(TypeError):
            sign_storage_key(signing_key=derive_signing_key(SECRET), key=KEY, expiry=float(EXPIRY))


class TestUnambiguousEncoding:
    """The signed payload maps distinct `(key, expiry)` pairs to distinct messages — **by
    construction**, not because the producers of keys happen to be well behaved.

    Both producers — `storage_key_for_photo` and, since `incident-photos`,
    `storage_key_for_incident_photo` — emit only literal segments, UUIDs and allowlisted
    extensions, so no key today contains the `|` delimiter. But that is a property of the
    CALLERS, and `revenue` is still named as a future signer with keys built some other way.
    The length prefix moves the guarantee into the primitive, which is why this class tests the
    primitive against adversarial pairs no current caller can produce.
    """

    #: Pairs chosen to sit on top of each other under any encoding that lets a field boundary
    #: be absorbed into `key`: the delimiter appears inside keys, at the edges, doubled, and
    #: with digits around it that could be mistaken for the length prefix or for the expiry.
    ADVERSARIAL_PAIRS = [
        ("a|b", 1),
        ("a", 1),
        ("a|b|c", 1),
        ("ab", 1),
        ("a|1", 2),
        ("a", 12),
        ("", 1),
        ("|a", 1),
        ("a|", 1),
        ("3|a|b", 1),
        ("a|b", 11),
        ("a|b|1", 1),
    ]

    def test_distinct_pairs_never_share_a_signature(self) -> None:
        signing_key = derive_signing_key(SECRET)

        signatures = {
            sign_storage_key(signing_key=signing_key, key=key, expiry=expiry): (key, expiry)
            for key, expiry in self.ADVERSARIAL_PAIRS
        }

        assert len(signatures) == len(self.ADVERSARIAL_PAIRS)

    def test_a_key_containing_the_delimiter_signs_and_verifies(self) -> None:
        """Not rejected — accepted, unambiguously. A blacklist over caller input was the
        alternative and would have made this a `ValueError`; the length prefix makes it a
        non-event, which is the point of fixing the primitive instead of policing its callers."""
        signing_key = derive_signing_key(SECRET)
        key = "tenants/1|1/maintenance/../weird|key.jpg"

        signature = sign_storage_key(signing_key=signing_key, key=key, expiry=EXPIRY)

        verify_signed_key(
            signing_key=signing_key, key=key, expiry=EXPIRY, signature=signature, now=NOW
        )

    def test_a_delimiter_key_cannot_borrow_another_keys_signature(self) -> None:
        """The concrete pivot the encoding fix exists to make impossible: a key whose text is a
        rearrangement of another key's payload fields must not verify against it."""
        signing_key = derive_signing_key(SECRET)
        signature = sign_storage_key(signing_key=signing_key, key="a|b", expiry=EXPIRY)

        with pytest.raises(InvalidSignatureError):
            verify_signed_key(
                signing_key=signing_key,
                key="a",
                expiry=EXPIRY,
                signature=signature,
                now=NOW,
            )


class TestTtlClamp:
    """`clamp_expires_in`: the signing-time half of the ceiling (R3.1, rule 5)."""

    def test_the_ceiling_is_the_hour_the_security_rule_asks_for(self) -> None:
        assert SIGNED_URL_TTL_SECONDS == 3600

    @pytest.mark.parametrize("requested", [SIGNED_URL_TTL_SECONDS + 1, 86_400, 365 * 24 * 3600])
    def test_more_than_the_ceiling_is_cut_down_to_it(self, requested: int) -> None:
        """Clamped, not refused: an over-long TTL has one right answer and nothing for the
        caller to decide, and raising would turn a policy into a failed photo listing."""
        assert clamp_expires_in(requested) == SIGNED_URL_TTL_SECONDS

    @pytest.mark.parametrize("requested", [1, 60, SIGNED_URL_TTL_SECONDS])
    def test_anything_up_to_the_ceiling_is_honoured_untouched(self, requested: int) -> None:
        assert clamp_expires_in(requested) == requested

    @pytest.mark.parametrize("requested", [0, -1, -3600])
    def test_a_non_positive_ttl_is_refused(self, requested: int) -> None:
        """Refused rather than clamped up, because unlike an over-long TTL there is no right
        answer to invent: it mints a URL that is dead the instant it exists, and it would
        surface as an unexplained 403 at a browser rather than anywhere near the bug."""
        with pytest.raises(ValueError):
            clamp_expires_in(requested)

    def test_a_float_ttl_is_refused(self) -> None:
        """`int(clock()) + 3600.5` is not an int expiry, and `sign_storage_key` type-checks the
        expiry for a reason — this refuses one step earlier, where the caller still is."""
        with pytest.raises(TypeError):
            clamp_expires_in(3600.0)


class TestVerification:
    def test_a_valid_signature_verifies(self) -> None:
        _verify()  # does not raise

    def test_an_expired_signature_is_refused(self) -> None:
        with pytest.raises(InvalidSignatureError):
            _verify(now=EXPIRY + 1)

    def test_it_is_refused_exactly_at_the_expiry_second(self) -> None:
        with pytest.raises(InvalidSignatureError):
            _verify(now=EXPIRY)

    def test_a_signature_for_another_key_is_refused(self) -> None:
        """The signed payload covers the whole storage key, which starts with the tenant id
        (D3) — so a valid signature cannot be pivoted onto another tenant's object."""
        other = KEY.replace("11111111", "22222222")

        with pytest.raises(InvalidSignatureError):
            _verify(key=other)

    def test_a_moved_expiry_is_refused(self) -> None:
        """The deadline is inside the signature, so extending it invalidates it."""
        with pytest.raises(InvalidSignatureError):
            _verify(expiry=EXPIRY + 1, signature=_signature(expiry=EXPIRY))

    def test_a_truncated_signature_is_refused(self) -> None:
        with pytest.raises(InvalidSignatureError):
            _verify(signature=_signature()[:-1])

    def test_an_empty_signature_is_refused(self) -> None:
        with pytest.raises(InvalidSignatureError):
            _verify(signature="")

    def test_a_non_ascii_signature_is_refused_rather_than_crashing(self) -> None:
        """`hmac.compare_digest` raises `TypeError` on a non-ASCII `str`, and the signature
        arrives from a query string — so a request with one accented character would take the
        endpoint down instead of getting its 403 (R3.4)."""
        with pytest.raises(InvalidSignatureError):
            _verify(signature="ñ" * SIGNATURE_LENGTH)

    def test_a_signature_from_another_secret_is_refused(self) -> None:
        with pytest.raises(InvalidSignatureError):
            _verify(signing_key=derive_signing_key("t" * 64))

    def test_a_signature_whose_ttl_exceeds_the_ceiling_is_refused(self) -> None:
        """**The assertion the whole TTL fix rests on** (R3.1, rule 5).

        The signature here is genuine — minted with the real signing key, over exactly the
        `(key, expiry)` presented, not expired. It is refused only because it would grant a
        year of anonymous access to a photo. Clamping at signing time binds the callers that
        come through `clamp_expires_in`; this binds the URL.
        """
        far = NOW + 365 * 24 * 3600

        with pytest.raises(InvalidSignatureError):
            _verify(expiry=far, signature=_signature(expiry=far))

    def test_the_ceiling_is_refused_one_second_past_it_and_allowed_exactly_at_it(self) -> None:
        """The boundary, both sides of it: a URL minted now with the default TTL and verified in
        the same second sits exactly ON the ceiling, so an off-by-one here would break every
        photo URL the moment it was issued."""
        at_ceiling = NOW + SIGNED_URL_TTL_SECONDS
        past_ceiling = at_ceiling + 1

        _verify(expiry=at_ceiling, signature=_signature(expiry=at_ceiling))  # does not raise

        with pytest.raises(InvalidSignatureError):
            _verify(expiry=past_ceiling, signature=_signature(expiry=past_ceiling))

    def test_an_over_long_signature_becomes_acceptable_only_as_its_deadline_nears(self) -> None:
        """The ceiling is on `expiry - now`, not on `expiry`: the same over-long URL is refused
        today and would verify inside the last hour before it dies. That is the honest reading
        of "no URL grants more than an hour of access from the moment it is used", and it is
        why the check subtracts rather than comparing against a stored issue time we do not
        have."""
        far = NOW + 10 * 3600

        with pytest.raises(InvalidSignatureError):
            _verify(expiry=far, signature=_signature(expiry=far))

        _verify(expiry=far, signature=_signature(expiry=far), now=far - 60)  # does not raise

    def test_the_comparison_is_constant_time(self) -> None:
        """R3.5. Asserted on the mechanism, not on wall-clock timings — a timing measurement in
        CI is a flaky test, while `compare_digest` is the property being required."""
        import app.integrations.domain.storage as storage

        source = storage.__file__
        assert source is not None
        with open(source, encoding="utf-8") as handle:
            text = handle.read()

        assert "hmac.compare_digest" in text
