"""The i18n mechanism (`dashboard-api` R5, task 1.1)."""

import pytest

from app.core.i18n import Catalog, CatalogTemplateError, Locale

CATALOG = Catalog(
    {
        "greeting": {Locale.ES: "Hola, {name}", Locale.EN: "Hello, {name}"},
        "plain": {Locale.ES: "Sin variables", Locale.EN: "No variables"},
        "spanish_only": {Locale.ES: "Solo español"},
    }
)


def test_renders_in_both_locales() -> None:
    assert CATALOG.render("greeting", Locale.ES, {"name": "Marta"}) == "Hola, Marta"
    assert CATALOG.render("greeting", Locale.EN, {"name": "Marta"}) == "Hello, Marta"


def test_renders_a_template_without_placeholders_without_values() -> None:
    assert CATALOG.render("plain", Locale.EN) == "No variables"


def test_an_unknown_key_yields_none_so_the_caller_can_degrade() -> None:
    assert CATALOG.render("nope", Locale.ES) is None


def test_a_locale_the_key_does_not_cover_yields_none() -> None:
    assert CATALOG.render("spanish_only", Locale.EN) is None


def test_a_missing_placeholder_yields_none_rather_than_a_literal_brace() -> None:
    """D5: a type whose template asks for data its factory never stored degrades."""
    assert CATALOG.render("greeting", Locale.ES, {}) is None


def test_locales_for_reports_coverage() -> None:
    assert CATALOG.locales_for("greeting") == frozenset(Locale)
    assert CATALOG.locales_for("spanish_only") == frozenset({Locale.ES})
    assert CATALOG.locales_for("nope") == frozenset()


def test_keys_lists_the_vocabulary() -> None:
    assert CATALOG.keys == frozenset({"greeting", "plain", "spanish_only"})


def test_the_catalog_copies_its_entries() -> None:
    entries: dict[str, dict[Locale, str]] = {"k": {Locale.ES: "v"}}
    catalog = Catalog(entries)
    entries["k"][Locale.EN] = "mutated"
    assert catalog.locales_for("k") == frozenset({Locale.ES})


# --- a template that cannot render is refused at construction (R5.4) -------------------
#
# The QA panel of section 1 found the hole this closes: `format_map` answers a positional
# field with `ValueError`, so a stray `{}` among the 90 hand-written timeline templates
# would have been a `500` on a timeline instead of the degradation R5.4 promises.


@pytest.mark.parametrize(
    "template",
    ["{}", "{0}", "{1} and {2}"],
    ids=["empty", "indexed", "several-indexed"],
)
def test_a_positional_field_is_refused_when_the_catalog_is_built(template: str) -> None:
    with pytest.raises(CatalogTemplateError):
        Catalog({"k": {Locale.ES: template}})


@pytest.mark.parametrize("template", ["{", "}", "{unclosed"], ids=["open", "close", "partial"])
def test_a_malformed_template_is_refused_when_the_catalog_is_built(template: str) -> None:
    with pytest.raises(CatalogTemplateError):
        Catalog({"k": {Locale.ES: template}})


@pytest.mark.parametrize(
    "template", ["{event.__class__}", "{values[0]}"], ids=["attribute", "index"]
)
def test_a_template_that_traverses_its_value_is_refused(template: str) -> None:
    """No message needs traversal, and forbidding it makes a substituted value provably a
    plain value rather than a foothold into the object it came from."""
    with pytest.raises(CatalogTemplateError):
        Catalog({"k": {Locale.ES: template}})


@pytest.mark.parametrize(
    "template",
    ["{name:>10}", "{name:{0}}", "{name:{width}}", "{name:.2f}"],
    ids=["width", "nested-positional", "nested-named", "precision"],
)
def test_a_format_spec_is_refused(template: str) -> None:
    """`{name:{0}}` is why this is a ban and not an inspection: `Formatter.parse` returns a
    format spec unexpanded, so a check that only read `field_name` let the nested
    positional field through and it raised at render time (QA panel, section 1)."""
    with pytest.raises(CatalogTemplateError):
        Catalog({"k": {Locale.ES: template}})


@pytest.mark.parametrize("template", ["{name!r}", "{name!s}", "{name!a}"])
def test_a_conversion_is_refused(template: str) -> None:
    with pytest.raises(CatalogTemplateError):
        Catalog({"k": {Locale.ES: template}})


def test_no_template_the_constructor_accepts_can_make_render_raise() -> None:
    """The property the two rounds of this finding were really about.

    Enumerating rejected forms proves nothing about the ones that get through, so this
    asserts the positive: every template `Catalog` accepts renders to a `str` or to `None`,
    against values that satisfy the placeholder, that omit it, and that are hostile.
    """
    accepted = [
        "sin variables",
        "{name}",
        "{a} y {b}",
        "100 {{literal}} {name}",
        "{name}{name}",
        "",
    ]
    value_sets: list[dict] = [
        {},
        {"name": "x", "a": "1", "b": "2"},
        {"name": {"nested": "dict"}, "a": ["list"], "b": None},
        {"unused": "key"},
    ]
    for template in accepted:
        catalog = Catalog({"k": {Locale.ES: template}})
        for values in value_sets:
            result = catalog.render("k", Locale.ES, values)
            assert result is None or isinstance(result, str)


def test_the_error_names_the_key_and_the_locale_that_carry_the_bad_template() -> None:
    with pytest.raises(CatalogTemplateError) as raised:
        Catalog({"greeting": {Locale.ES: "Hola, {name}", Locale.EN: "Hello, {0}"}})

    assert "greeting" in str(raised.value)
    assert "en" in str(raised.value)


def test_escaped_braces_are_not_a_field_and_stay_legal() -> None:
    catalog = Catalog({"k": {Locale.ES: "100 {{literal}} {name}"}})

    assert catalog.render("k", Locale.ES, {"name": "x"}) == "100 {literal} x"


@pytest.mark.parametrize("value", ["es", "ES", " es "])
def test_resolve_accepts_the_stored_spanish_forms(value: str) -> None:
    assert Locale.resolve(value) is Locale.ES


def test_resolve_accepts_english() -> None:
    assert Locale.resolve("en") is Locale.EN


@pytest.mark.parametrize("value", [None, "", "fr", "es-ES", "klingon"])
def test_an_unsupported_preferred_language_degrades_to_spanish(value: str | None) -> None:
    """`users.preferred_language` is String(5) with no constraint (design, Risks)."""
    assert Locale.resolve(value) is Locale.ES
