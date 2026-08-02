"""The temporary password generator (R1.2, R4.1, design D9/D20).

Asserts shape and properties, never a fixed value: the point of the thing is that it is
unpredictable, so a test pinning an output would be testing a mock of it.
"""

import re

import pytest

from app.auth.domain.passwords import (
    ALPHABET,
    TEMPORARY_PASSWORD_LENGTH,
    DIGITS,
    LOWERCASE,
    UPPERCASE,
    generate_temporary_password,
)

AMBIGUOUS = "0O1lI"


def test_it_has_the_documented_length() -> None:
    assert len(generate_temporary_password()) == TEMPORARY_PASSWORD_LENGTH


def test_it_uses_only_the_declared_alphabet() -> None:
    for _ in range(200):
        assert set(generate_temporary_password()) <= set(ALPHABET)


def test_the_alphabet_excludes_every_ambiguous_glyph() -> None:
    """`0`/`O` and `1`/`l`/`I` are read aloud and typed by a person (design D9)."""
    assert not set(ALPHABET) & set(AMBIGUOUS)


def test_it_never_emits_an_ambiguous_glyph() -> None:
    """Checked on the output as well as on the alphabet: two independent ways to fail."""
    for _ in range(200):
        assert not set(generate_temporary_password()) & set(AMBIGUOUS)


def test_it_always_contains_each_character_class() -> None:
    """So a future strength policy cannot reject a password this system generated."""
    for _ in range(200):
        password = generate_temporary_password()
        assert any(glyph in DIGITS for glyph in password)
        assert any(glyph in UPPERCASE for glyph in password)
        assert any(glyph in LOWERCASE for glyph in password)


def test_two_calls_do_not_coincide() -> None:
    assert len({generate_temporary_password() for _ in range(200)}) == 200


def test_it_fits_under_the_bcrypt_input_limit() -> None:
    """`auth-tenancy` refuses a password over 72 BYTES rather than truncating it (its R1.3).

    A generator that could exceed it would make the create-user path fail on its own output.
    """
    for _ in range(50):
        assert len(generate_temporary_password().encode("utf-8")) <= 72


def test_it_is_ascii_so_length_equals_byte_count() -> None:
    assert re.fullmatch(r"[\x21-\x7e]+", generate_temporary_password())


def test_it_does_not_use_the_random_module() -> None:
    """`random` is a predictable PRNG; a credential needs `secrets` (design D9)."""
    import app.auth.domain.passwords as module

    source = (
        __import__("pathlib").Path(module.__file__).read_text(encoding="utf-8")
    )
    assert "import secrets" in source
    assert not re.search(r"^import random|^from random", source, re.MULTILINE)


def test_the_alphabet_is_large_enough_to_be_worth_the_length() -> None:
    """A regression guard: shrinking the alphabet silently weakens every temporary password."""
    assert len(ALPHABET) >= 50


@pytest.mark.parametrize("klass", ["DIGITS", "UPPERCASE", "LOWERCASE"])
def test_each_class_is_non_empty(klass: str) -> None:
    """An empty class would make the class guarantee unsatisfiable and hit the attempt cap."""
    assert len({"DIGITS": DIGITS, "UPPERCASE": UPPERCASE, "LOWERCASE": LOWERCASE}[klass]) > 0
