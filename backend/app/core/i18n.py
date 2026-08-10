"""The mechanism that renders a message in the reader's language (`dashboard-api` D4).

Mechanism only: this module holds the `Locale` type and a `Catalog` that resolves
key+locale to a template and formats it. **It holds no messages.** The tables live in the
`domain/` of whoever owns the vocabulary — `app/timeline/domain/rendering.py` for the
event types, `app/dashboard/domain/labels.py` for the card labels — because
`steering/architecture.md` reserves `core/` for shared infrastructure and says it "no
aloja entidades de negocio".

Pure Python by obligation, not by taste: `domain/` modules import this, and
`tests/test_layering.py` forbids them any framework.
"""

import enum
import string
from collections.abc import Mapping
from typing import Any

DEFAULT_LOCALE_VALUE = "es"

_FORMATTER = string.Formatter()


class CatalogTemplateError(ValueError):
    """A template a `Catalog` was built with is not one this mechanism can render.

    Raised at **construction**, not at render time, and that placement is the whole point.
    Catalog entries are developer-authored constants, so a stray `{}`, an unbalanced brace
    or a `{0}` is an authoring mistake — and `str.format_map` answers those with a
    `ValueError`, which at render time would be a `500` on a timeline instead of the
    degradation R5.4 promises. Failing when the module is imported turns the same mistake
    into a red test.
    """


class Locale(str, enum.Enum):
    """The languages the product speaks (`User.preferred_language`)."""

    ES = "es"
    EN = "en"

    @classmethod
    def resolve(cls, value: str | None) -> "Locale":
        """The locale for a stored preference, defaulting to `es`.

        `users.preferred_language` is `String(5)` with no check constraint, so a row can
        hold anything — `fr`, `es-ES`, or an empty string. A read path must degrade rather
        than fail: the alternative is a `500` on a dashboard because someone's profile
        carries a language we do not ship.
        """
        if value is None:
            return cls.ES
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.ES


class Catalog:
    """Templates for one vocabulary, in every locale.

    `render` returns `None` — rather than raising or emitting a placeholder — for both ways
    a lookup can come up empty: an unknown key, and a template whose placeholder is absent
    from the values it was given. Both mean "this catalog cannot say it", and the caller is
    the one that knows the fallback (the timeline degrades to the stored `title`, D5). A
    caller that silently rendered `{from_state}` into a user-facing string would be the
    failure this return type exists to prevent.

    The **third** way — a template that is not renderable at all — is rejected here in the
    constructor rather than absorbed by `render`, so it can never be one of the runtime
    cases. See `CatalogTemplateError`.
    """

    def __init__(self, entries: Mapping[str, Mapping[Locale, str]]) -> None:
        for key, templates in entries.items():
            for locale, template in templates.items():
                _validate_template(template, key=key, locale=locale)
        self._entries = {key: dict(templates) for key, templates in entries.items()}

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self._entries)

    def locales_for(self, key: str) -> frozenset[Locale]:
        """Which locales cover `key` — what a coverage test asserts over an enum."""
        return frozenset(self._entries.get(key, {}))

    def render(self, key: str, locale: Locale, values: Mapping[str, Any] | None = None) -> str | None:
        template = self._entries.get(key, {}).get(locale)
        if template is None:
            return None
        try:
            return template.format_map(_Values(values or {}))
        except _MissingValue:
            return None


def _validate_template(template: str, *, key: str, locale: Locale) -> None:
    """Reject anything `format_map` would answer with an exception instead of a string.

    A template here is `{plain_name}` substitution and literal text. Everything else is an
    authoring mistake rather than a runtime condition, and there are four classes:

    * **Positional or malformed fields** — `{}`, `{0}`, `{`. `format_map` takes a mapping,
      so a positional field is a `ValueError` on every render, and an unbalanced brace is
      one at parse time.
    * **Attribute and index traversal** — `{event.__class__}`, `{values[0]}`. No message
      needs them, and forbidding them is what makes a substituted value provably a plain
      value rather than a foothold into whatever object was passed in.
    * **Format specs** — `{name:>10}`, and crucially `{name:{0}}`. The second is why this
      is a ban and not an inspection: `Formatter.parse` hands back a format spec as an
      opaque string without expanding the field nested inside it, so a spec-level check
      that only read `field_name` let `{name:{0}}` through and it raised at render time —
      the very hole this function exists to close, re-opened one level down. The QA panel
      of section 1 found it there after finding `{}` here. Refusing specs outright removes
      the class instead of enumerating its members, and no message needs a width.
    * **Conversions** — `{name!r}`. Same reasoning, and `repr()` of a value is a debugging
      form, not something to put in front of a reader.
    """
    where = f"{key}/{locale.value}"
    try:
        fields = list(_FORMATTER.parse(template))
    except ValueError as error:
        raise CatalogTemplateError(f"{where}: template is malformed ({error})") from error
    for _, field_name, format_spec, conversion in fields:
        if field_name is None:
            continue
        if field_name == "" or field_name.isdigit():
            raise CatalogTemplateError(
                f"{where}: positional field {{{field_name}}}; templates take named fields"
            )
        if "." in field_name or "[" in field_name:
            raise CatalogTemplateError(
                f"{where}: {{{field_name}}} traverses the value; only plain names are allowed"
            )
        if format_spec:
            raise CatalogTemplateError(
                f"{where}: {{{field_name}}} carries a format spec; templates substitute "
                "plain names only"
            )
        if conversion is not None:
            raise CatalogTemplateError(
                f"{where}: {{{field_name}}} carries a !{conversion} conversion; templates "
                "substitute plain names only"
            )


class _MissingValue(LookupError):
    pass


class _Values(dict):
    """Turns a missing placeholder into `_MissingValue` instead of `KeyError`.

    `format_map` raises `KeyError` for an absent key, which a caller could catch by
    accident while meaning to catch something else. A dedicated type keeps the two apart.
    """

    def __missing__(self, key: str) -> Any:
        raise _MissingValue(key)
