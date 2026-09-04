"""The shape of the ports, asserted rather than described (R1.1, R2.1, R2.2, R6.1, R6.4).

A port's **absences** are as much a decision as its methods, and absences are what rot
silently: nothing goes red when someone adds the speculative sixth method. So each one is
pinned here by name.
"""

import inspect
import uuid
from typing import Protocol

from app.integrations.domain.ports import PMSMessagingPort
from app.maintenance.domain.ports import IncidentClassifier
from app.messaging.domain.ports import (
    AIAdapter,
    IncidentReportingPort,
    OutboundMessagePort,
)
from app.messaging.domain.entities import Conversation
from app.messaging.domain.repositories import (
    ConversationFilters,
    ConversationPage,
    ConversationRepository,
    MessagePage,
    MessageRepository,
)
from app.messaging.domain.value_objects import ChannelSendResult, InboundMessageActor


def declared_methods(protocol: type) -> set[str]:
    """Every method reachable on a `Protocol`, ignoring what `Protocol` itself brings along.

    **`dir()` and not `vars()`**, which is the difference between guarding R2.1 and appearing
    to. `vars(protocol)` sees only what is written in that class body, so a method inherited
    from another `Protocol` base — a plausible refactor, e.g. factoring a shared
    `content`/`language` mixin across two adapter ports — would be invisible here while being
    perfectly callable at runtime. The QA panel of sections 3-4 demonstrated exactly that with
    a `SneakyBase(Protocol)`. `dir()` walks the MRO, so a smuggled method shows up.
    """
    inherited = set(dir(Protocol)) | set(dir(object))
    return {
        name
        for name in dir(protocol)
        if not name.startswith("_")
        and name not in inherited
        and callable(getattr(protocol, name, None))
    }


def test_the_helper_sees_a_method_smuggled_in_through_a_protocol_base() -> None:
    """The guard gets its own guard: without this, `declared_methods` could quietly go back to
    `vars()` and every R2.1 assertion below would keep passing while checking nothing."""

    class SneakyBase(Protocol):
        def leaked_method(self) -> None: ...

    class Smuggled(SneakyBase, Protocol):
        def declared_here(self) -> None: ...

    assert declared_methods(Smuggled) == {"leaked_method", "declared_here"}


# --- AIAdapter (R2.1, R2.2) --------------------------------------------------------------


def test_the_ai_adapter_declares_exactly_two_methods() -> None:
    assert declared_methods(AIAdapter) == {"classify_message", "generate_response"}


def test_the_ai_adapter_declares_none_of_the_other_four_of_the_prd() -> None:
    """R2.1 verbatim: "NEVER SHALL declarar `classify_incident`, `validate_cleaning_photo`,
    `summarize_incident` ni `draft_review_response`".

    Each absent for its own reason (see the port's docstring), and declaring all six with
    four raising `NotImplementedError` was rejected in D6 for breaking Liskov — the case
    `steering/backend-architecture.md` names by name.
    """
    assert declared_methods(AIAdapter).isdisjoint(
        {
            "classify_incident",
            "validate_cleaning_photo",
            "summarize_incident",
            "draft_review_response",
        }
    )


def test_the_incident_classifier_of_maintenance_is_untouched() -> None:
    """R2.2: incident classification does not move here. `sdd/specs/maintenance.md` R2 forbids
    the crossing in the opposite direction, so this is the same prohibition facing this way."""
    assert declared_methods(IncidentClassifier) == {"classify"}
    assert IncidentClassifier.__module__ == "app.maintenance.domain.ports"


def test_the_ai_adapter_methods_are_coroutines_taking_keyword_arguments() -> None:
    """Keyword-only, like every other port in this codebase: a positional `content` and
    `language` are two strings a caller can swap without noticing."""
    for name in ("classify_message", "generate_response"):
        method = getattr(AIAdapter, name)
        assert inspect.iscoroutinefunction(method)
        parameters = inspect.signature(method).parameters
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter_name, parameter in parameters.items()
            if parameter_name != "self"
        )


# --- PMSMessagingPort (R6.4) -------------------------------------------------------------


def test_the_pms_messaging_port_is_still_the_port_with_no_methods() -> None:
    """R6.4 verbatim: "THE SYSTEM SHALL dejar `PMSMessagingPort` exactamente como está —un
    puerto sin métodos— y NEVER SHALL añadirle `get_messages` ni `send_message`".

    Its shape is decided by the first provider that implements it, which is what
    `sdd/specs/pms-provider-resolution.md` fixed. This change is its first *would-be*
    consumer and deliberately is not one: the two OTA channels stay unreachable (R6.3)
    instead of being served by a port invented from this side.
    """
    assert declared_methods(PMSMessagingPort) == set()


# --- OutboundMessagePort (R6.1) ----------------------------------------------------------


def test_the_outbound_port_declares_one_method() -> None:
    assert declared_methods(OutboundMessagePort) == {"send"}


def test_the_outbound_port_returns_the_outcome_rather_than_raising() -> None:
    """R6.5. The return annotation is where that promise is kept — see `ChannelSendResult`."""
    assert (
        inspect.signature(OutboundMessagePort.send).return_annotation
        is ChannelSendResult
    )


# --- IncidentReportingPort (R4.6) --------------------------------------------------------


def test_the_incident_reporting_port_declares_one_method() -> None:
    assert declared_methods(IncidentReportingPort) == {"report"}


def test_reporting_an_incident_requires_an_actor_of_either_kind() -> None:
    """`guest-portal-messaging` R4.1, D8. Until that change this asserted a required
    `actor_user_id: uuid.UUID`, on the reasoning that a guest's message always arrives with an
    authenticated user at the keyboard. `POST /api/v1/guest/messages/{token}` is the second
    door and there is no user behind it, so the parameter became an `InboundMessageActor` —
    still required, and still exactly one actor, because the value object refuses the other
    two shapes."""
    parameters = inspect.signature(IncidentReportingPort.report).parameters

    assert parameters["actor"].annotation is InboundMessageActor
    assert parameters["actor"].default is inspect.Parameter.empty
    # The unpacked pair is gone: leaving either behind would be a second way to name an actor.
    assert "actor_user_id" not in parameters
    assert "ip" not in parameters
    # `reservation_id` is the optional one: a conversation need not have a booking (R5.6).
    assert parameters["reservation_id"].annotation == uuid.UUID | None


# --- The repository ports (R1.1) ---------------------------------------------------------


def test_the_conversation_repository_declares_only_what_this_change_consumes() -> None:
    """R1.1: "con **solo los métodos que este change consume**, y NEVER SHALL declarar métodos
    especulativos". The discipline `domain-foundation-ops` records as a bet that paid off.

    `ensure_portal` and `find_portal` are `guest-portal-messaging`'s widening (R2.5, R3.4, D6),
    and they arrive with their consumers in the same change — which is the condition D2 sets
    for widening a port at all. They are **two** methods and not one with a flag because R2.5
    turns on the difference: reading a thread must create nothing.

    `ensure_whatsapp` is `whatsapp-cloud-adapter`'s widening (R4.5, D4): the inbound webhook
    path needs a thread per guest **and property** rather than per stay, because on that path
    the reservation is frequently unknown while the thread must exist anyway (R4.3, R4.4).
    Not a flag on `ensure_portal` for the same reason those two are separate methods — the
    key differs, and a flag would hide which unique index the `ON CONFLICT` infers.
    """
    assert declared_methods(ConversationRepository) == {
        "add",
        "get",
        "save",
        "list",
        "ensure_portal",
        "find_portal",
        "ensure_whatsapp",
    }


def test_the_message_repository_declares_only_what_this_change_consumes() -> None:
    """Five methods, and each has its consumer in this same change (R1.1).

    `count_guest_messages` was not in the design's D2 list: it arrived while implementing
    section 6 as the only way to fill `ConversationContext.guest_message_count`, which R2.1
    and D6 declare as part of what an `AIAdapter` is told. R1.1 forbids a **speculative**
    method, not a fourth one — and D2 blesses exactly this shape of widening.

    `last_guest_message_at` is `whatsapp-cloud-adapter` R2.4's widening, resolved with the
    user 2026-09-02 (design D2): `Conversation.last_message_at` cannot answer "since the
    guest's last message" because every sender touches it, so `DelegatingOutboundAdapter`
    needs this fifth, guest-only method instead.

    No `save` in particular: `messages` is append-only and D14 was amended so the pipeline
    builds each row once, with its delivery outcome already in it.
    """
    assert declared_methods(MessageRepository) == {
        "add",
        "list_for_conversation",
        "count_guest_messages",
        "count_unresolved_guest_messages_with_intent",
        "last_guest_message_at",
    }


def test_every_message_repository_method_has_a_consumer_in_this_change() -> None:
    """The property R1.1 actually asks for, checked rather than asserted in prose.

    A method nobody calls is the speculation the requirement forbids, and it is the failure
    this test would catch — including for the one added after the design was written.

    Two source files, not one: `last_guest_message_at`'s consumer is
    `DelegatingOutboundAdapter` in `infrastructure/channels.py` (`whatsapp-cloud-adapter`
    R2.4, D2) — the window is resolved at the channel boundary, not inside a use case — while
    the other four still call through `self._messages.<method>(` inside
    `ProcessInboundGuestMessageUseCase`.
    """
    import inspect as _inspect

    from app.messaging.application import use_cases as messaging_use_cases
    from app.messaging.infrastructure import channels as messaging_channels

    source = _inspect.getsource(messaging_use_cases) + _inspect.getsource(messaging_channels)
    for method in declared_methods(MessageRepository):
        assert f"._messages.{method}(" in source, (
            f"MessageRepository.{method} has no consumer in messaging/"
        )


def test_neither_repository_declares_a_speculative_method() -> None:
    for port in (ConversationRepository, MessageRepository):
        assert declared_methods(port).isdisjoint(
            {"delete", "search", "find", "get_all", "update", "upsert"}
        )


def test_the_page_and_filter_types_are_frozen_value_objects() -> None:
    for value_object in (ConversationFilters, ConversationPage, MessagePage):
        assert value_object.__dataclass_params__.frozen


def test_the_conversation_filters_are_the_three_of_the_requirement() -> None:
    """R7.3: "filtrar por `status`, `escalation_status` y `property_id`"."""
    assert set(ConversationFilters.__dataclass_fields__) == {
        "status",
        "escalation_status",
        "property_id",
    }


def test_a_page_carries_its_total_for_the_client_to_paginate() -> None:
    """PRD §23 wants `total_pages`, which the client cannot compute without the total."""
    for page in (ConversationPage, MessagePage):
        assert set(page.__dataclass_fields__) == {"items", "total"}


def test_neither_portal_method_is_optional_about_the_stay() -> None:
    """D6, after the security panel of section 1: the partial unique index behind `ensure_portal`
    cannot enforce R3.4 for a row whose `reservation_id` is NULL, because PostgreSQL treats
    NULLs as distinct in a unique index. Typing the parameter is what closes that, so the type
    is the guarantee and belongs in a test rather than in a comment."""
    for method in (
        ConversationRepository.ensure_portal,
        ConversationRepository.find_portal,
    ):
        annotation = inspect.signature(method).parameters["reservation_id"].annotation
        assert annotation is uuid.UUID, method.__name__


def test_find_portal_may_answer_that_there_is_no_thread() -> None:
    """R2.5: an empty thread is a `200`, so "no conversation yet" has to be expressible as a
    value. `ensure_portal`, by contrast, always returns one."""
    assert (
        inspect.signature(ConversationRepository.find_portal).return_annotation
        == Conversation | None
    )
    assert (
        inspect.signature(ConversationRepository.ensure_portal).return_annotation
        is Conversation
    )
