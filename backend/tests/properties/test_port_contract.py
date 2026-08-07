"""The property port's writers stay narrow (`properties-crud` R4.2, design D3).

This is a structural test on purpose. The rule it protects — only `PropertyStateMachine` writes
`current_operational_state` (`steering/backend.md`, and `celery-jobs` R3.6: "no SHALL escribir
`current_operational_state` por ninguna otra vía") — is the kind that survives as long as
somebody remembers it during review. Asserting it here means a future widening fails in the
suite instead of depending on a reviewer noticing, which is the same reason
`tests/test_route_authorization.py` snapshots the protected paths.
"""

import inspect

from app.properties.domain.repositories import (
    PATCHABLE_PROPERTY_FIELDS,
    PropertyRepository,
)

def _port_methods() -> dict[str, object]:
    return {
        name: member
        for name, member in inspect.getmembers(PropertyRepository, inspect.isfunction)
        if not name.startswith("_")
    }


def test_the_port_exposes_the_methods_this_change_relies_on() -> None:
    """Guards against vacuity: the assertions below prove nothing on an empty port."""
    assert {
        "get",
        "find_by_internal_code",
        "find_by_pms_external_id",
        "list_by_state",
        "list_all",
        "save",
        "set_pms_provider",
        "add",
        "update_details",
        "set_wifi_password",
        "list",
    } <= set(_port_methods())


def test_only_the_known_methods_take_an_operational_state_directly() -> None:
    """A snapshot, on purpose: a new method taking a state has to show up in this diff.

    **What this measures, precisely.** It scans parameter annotations for the state enum, so it
    catches the realistic widening — somebody adding `set_operational_state(tenant_id, id,
    state)` — and it does NOT catch `save`/`add`, which receive the state inside a `Property`.
    Those two are the sanctioned pair and are pinned by name in the sibling tests instead:
    `save` writes the column after `PropertyStateMachine` approved the destination, and an
    insert has no source state to transition *from*, so its column takes the DDL default while
    R4 keeps the API from offering a choice.

    `list_by_state` is a READ that filters. Filtering is not writing, so it is allowed — but it
    is listed explicitly rather than exempted by a pattern, so the set cannot grow unnoticed.

    Checked on annotations rather than bodies because the port has no bodies: the signature is
    the whole contract, and the signature is what a future change would widen.
    """
    accepting = {
        name
        for name, method in _port_methods().items()
        for parameter, annotation in inspect.get_annotations(method, eval_str=False).items()
        if parameter != "return" and "PropertyOperationalState" in str(annotation)
    }
    assert accepting == {"list_by_state"}, (
        "the set of port methods taking an operational state directly changed; if the new one "
        f"writes it, it is a route around PropertyStateMachine: {sorted(accepting)}"
    )


def test_the_paginated_listing_takes_its_state_as_a_read_filter() -> None:
    """`list` carries a state inside `PropertyFilters`, and returns a page — a read, not a write."""
    from app.properties.domain.repositories import PropertyFilters

    assert "current_operational_state" in PropertyFilters.__dataclass_fields__
    list_annotations = inspect.get_annotations(_port_methods()["list"], eval_str=False)
    assert "PropertyFilters" in str(list_annotations["filters"])
    assert "Page" in str(list_annotations["return"])


def test_current_operational_state_is_not_patchable() -> None:
    """The `PATCH` allowlist is the other half of the same guarantee (design D3)."""
    assert "current_operational_state" not in PATCHABLE_PROPERTY_FIELDS


def test_the_wifi_password_is_not_patchable_as_a_plain_column() -> None:
    """It goes through `set_wifi_password`, which encrypts; a plain key would not (R5.2)."""
    assert "wifi_password" not in PATCHABLE_PROPERTY_FIELDS
    assert "wifi_password_encrypted" not in PATCHABLE_PROPERTY_FIELDS


def test_the_entity_carries_no_wifi_password_field() -> None:
    """Design D2: keeping the secret off the entity keeps it off every serialisation path."""
    from app.properties.domain.entities import Property

    assert "wifi_password_encrypted" not in Property.__dataclass_fields__
    assert "wifi_password" not in Property.__dataclass_fields__
