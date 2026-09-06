"""`normalize_email` and `normalize_phone_e164` of the guests domain (design D8, D5)."""

from app.guests.domain.value_objects import normalize_email, normalize_phone_e164


def test_it_strips_and_lowercases() -> None:
    assert normalize_email("  John.Smith@Example.COM ") == "john.smith@example.com"


def test_it_is_idempotent() -> None:
    once = normalize_email("John@Example.com")
    assert normalize_email(once) == once


def test_it_agrees_with_the_auth_definition() -> None:
    """The two copies exist for dependency reasons (see the module docstring), not to
    behave differently. If this ever fails, one of them drifted and that is the bug."""
    from app.auth.domain.value_objects import normalize_email as auth_normalize

    for value in ("  A@B.COM ", "already@lower.com", "MiXeD@Case.Org"):
        assert normalize_email(value) == auth_normalize(value)


# --- `normalize_phone_e164` (`whatsapp-cloud-adapter` design D5, R4.2) --------------------


def test_a_bare_9_digit_number_defaults_to_spain() -> None:
    assert normalize_phone_e164("612345678") == "+34612345678"


def test_a_full_es_e164_number_is_returned_unchanged() -> None:
    assert normalize_phone_e164("+34612345678") == "+34612345678"


def test_formatting_characters_are_stripped_before_matching() -> None:
    assert normalize_phone_e164(" +34 612 345 678 ") == "+34612345678"
    assert normalize_phone_e164("612-345-678") == "+34612345678"
    assert normalize_phone_e164("(612) 345 678") == "+34612345678"


def test_another_countrys_full_e164_number_is_accepted() -> None:
    """Not a Spanish default, but already in the recognised E.164 shape."""
    assert normalize_phone_e164("+14155550100") == "+14155550100"


def test_phone_normalisation_is_idempotent() -> None:
    once = normalize_phone_e164("612345678")
    assert once is not None
    assert normalize_phone_e164(once) == once


def test_an_empty_value_fails_closed() -> None:
    assert normalize_phone_e164("") is None


def test_a_bare_number_of_the_wrong_length_fails_closed() -> None:
    """Only a 9-digit bare number is the recognised Spanish shape — no other length guesses."""
    assert normalize_phone_e164("12345678") is None
    assert normalize_phone_e164("6123456789") is None


def test_a_00_prefixed_international_number_fails_closed() -> None:
    """Deliberately unsupported (design D5's risk note): no general international parser."""
    assert normalize_phone_e164("0034612345678") is None


def test_non_numeric_input_fails_closed() -> None:
    assert normalize_phone_e164("not-a-phone") is None


def test_a_lone_plus_sign_fails_closed() -> None:
    assert normalize_phone_e164("+") is None


def test_too_few_digits_after_the_plus_fails_closed() -> None:
    assert normalize_phone_e164("+3461") is None


def test_too_many_digits_after_the_plus_fails_closed() -> None:
    assert normalize_phone_e164("+1234567890123456") is None


def test_distinct_inputs_never_collide_on_the_same_normalized_value() -> None:
    """Design D5's own risk note: a hand-rolled normaliser could collide two different
    numbers onto the same value, which is worse than failing closed (R4.3). Every
    genuinely different input below must map to `None` or to a value no other input
    here also produced."""
    inputs = [
        "",
        "12345678",
        "6123456789",
        "0034612345678",
        "not-a-phone",
        "+",
        "+3461",
        "+1234567890123456",
        "6123456-78x",
        "00000000",
        "+abc123456",
        "612345678",
        "687654321",
        "+14155550100",
        "+442071838750",
    ]

    results = [normalize_phone_e164(value) for value in inputs]
    non_none_results = [r for r in results if r is not None]

    assert len(non_none_results) == len(set(non_none_results))
