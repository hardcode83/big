"""`mask_access_code` — rule 4 of `sdd/steering/security.md` ("códigos de acceso siempre `****XX`").

The test that carries the weight is the short-code one: that is where a naive
`code[:-2] -> "****"` implementation reveals the whole secret.
"""

import pytest

from app.access.domain.masking import mask_access_code


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("481523", "****23"),
        ("12", "****"),
        ("1", "****"),
        ("", "****"),
        ("   ", "****"),
        ("  481523\n", "****23"),
        ("A1B2C3D4E5F6", "****F6"),
        ("0000", "****00"),
    ],
)
def test_the_mask_is_four_stars_and_at_most_two_characters(code, expected) -> None:
    assert mask_access_code(code) == expected


@pytest.mark.parametrize("code", ["481523", "A1B2C3D4E5F6", "9876543210"])
def test_the_original_never_appears_in_the_mask(code) -> None:
    """The property, not just the examples: whatever the length, the code does not survive."""
    masked = mask_access_code(code)

    assert code not in masked
    assert len(masked) <= 6


def test_a_short_code_is_masked_whole_rather_than_padded() -> None:
    """A two-character code has no two characters to spare.

    `"****" + code[-2:]` would render `"12"` as `"****12"` — the entire secret, wearing a
    mask. This is the case a "same shape for everything" implementation gets wrong.
    """
    assert mask_access_code("12") == "****"
    assert "12" not in mask_access_code("12")
