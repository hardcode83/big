"""The storable-text guard, in the home `cleaner-incident-report` D7 gave it.

Promoted out of `guests/api/portal_schemas.py` so that more than one `api/` layer can share it
instead of copying a guard whose reasoning was won two security panels at a time.

The behavioural tests of the guest portal stay where they are: they exercise the guard through
a request, which is what pins the endpoint. What belongs here is the guard itself, so that
whoever edits `app/core/storable_text.py` sees a red test in the same package rather than in a
module about somebody else's portal.
"""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.storable_text import MultiLineText, SingleLineText, storable_text


@pytest.mark.parametrize("annotation", [SingleLineText, MultiLineText])
def test_a_nul_is_refused_because_postgres_cannot_store_it(annotation) -> None:
    """`U+0000` in a `text` value raises `CharacterNotInRepertoireError` inside asyncpg, which
    is an undeclared `500` and not the `422` the boundary promises."""
    with pytest.raises(ValidationError) as refusal:
        TypeAdapter(annotation).validate_python("boiler\x00")

    assert "control characters" in str(refusal.value)
    assert "U+0000" in str(refusal.value)


@pytest.mark.parametrize("annotation", [SingleLineText, MultiLineText])
def test_a_lone_surrogate_is_refused_because_it_does_not_survive_utf8(annotation) -> None:
    """Category `Cs`, not `Cc`: the case a character denylist waved through, and the reason the
    guard is written on "the value survives UTF-8" instead of on a class enumeration."""
    with pytest.raises(ValidationError) as refusal:
        TypeAdapter(annotation).validate_python("boiler" + chr(0xD800))

    assert "unpaired surrogate" in str(refusal.value)


def test_the_refusal_message_never_echoes_the_value() -> None:
    """One of the guarded fields is an identity document, so a `422` body is one more place it
    must not appear. This module's own message is what it controls — Pydantic's
    `str(ValidationError)` appends `input_value=...` on its own, and what stops *that* reaching
    a response is the application's replacement validation handler, pinned in
    `tests/guests/test_portal_incident_api.py`."""
    with pytest.raises(ValidationError) as refusal:
        TypeAdapter(SingleLineText).validate_python("12345678Z" + chr(0xD800))

    assert "12345678Z" not in refusal.value.errors()[0]["msg"]


def test_the_two_aliases_differ_only_in_the_whitespace_they_allow() -> None:
    """A single line an operator reads in a list versus free prose somebody writes. The
    asymmetry is the whole reason there are two aliases, so it is asserted rather than assumed:
    a newline in a title is the line-forging class, and a newline in a description is a
    paragraph."""
    prose = "The boiler is broken.\n\tWater under the sink.\r\n"

    assert TypeAdapter(MultiLineText).validate_python(prose) == prose
    with pytest.raises(ValidationError):
        TypeAdapter(SingleLineText).validate_python(prose)


@pytest.mark.parametrize("value", ["Caldera rota", "Se rompió la ducha — sale agua ⚠️"])
def test_ordinary_text_accents_and_emoji_pass_untouched(value: str) -> None:
    """`Cc` is exactly C0 and C1. The guard refuses rather than strips, so a value it accepts
    comes back bit-for-bit: silently editing what somebody wrote into a column an operator acts
    on is worse than refusing it."""
    for annotation in (SingleLineText, MultiLineText):
        assert TypeAdapter(annotation).validate_python(value) == value


def test_multiple_control_characters_are_reported_in_a_stable_order() -> None:
    """The `sorted()` in the offender set, which is otherwise unobservable.

    Raised by the QA panel of section 2: with the sort removed the guard still refuses, still
    names the right codepoints, and every other test here stays green — only the **order** of
    the `422` body changes, and it changes per run because the offenders are collected in a
    `set`. That is a guest-facing response whose shape would differ between two identical
    requests, which is the kind of thing nobody notices until a client diffs it.
    """
    check = storable_text("").func

    with pytest.raises(ValueError) as refusal:
        check("a\x01\x02\x03\x04\x05b")

    assert "U+0001, U+0002, U+0003, U+0004, U+0005" in str(refusal.value)


def test_the_surrogate_refusal_is_not_chained_to_the_error_carrying_the_value() -> None:
    """`raise … from None`, pinned where it can be seen.

    `UnicodeEncodeError`'s message names the offending character and its **position** in the
    value, so a chained refusal leaks the shape of what somebody typed into every traceback and
    log that renders the cause. Measured rather than assumed while writing this test: the
    context reads *"can't encode character '\\ud800' in position 9"* — it does not quote the
    surrounding text, so the leak is the position and the codepoint, not the whole field. That
    is smaller than "carries a fragment of the value" suggests, and still worth suppressing on
    a field that may hold an identity document.

    Without this test, deleting `from None` leaves the whole suite green — measured by the QA
    panel of section 2. Note `__cause__` stays `None` either way, because a bare `raise` inside
    an `except` sets `__context__`; `__suppress_context__` is the half that actually moves.

    Driven against the validator directly: Pydantic does not surface either attribute through
    `ValidationError`, so this property is invisible from the schema level.
    """
    check = storable_text("").func

    with pytest.raises(ValueError) as refusal:
        check("12345678Z" + chr(0xD800))

    assert refusal.value.__cause__ is None
    assert refusal.value.__suppress_context__ is True
