# BLOCKED — human-reply-outbound-delivery

One entry per pending item (shared rule 5): `decision` needs a human
before the change can move; `deferred` and `assumed` travel with the
PR and are acknowledged by deleting them; `/sdd:archive` refuses to
close while any entry remains.


## `tasks.md:96` Implementation Note claims inverted precedence (architect finding, low)

- **phase**: review
- **type**: deferred
- **what & why**: `sdd/changes/human-reply-outbound-delivery/tasks.md:96` says `_recipient_contact` "keeps the same precedence as the original method (D14)" (kind-first then guest_id) — but the moved function at `backend/app/messaging/application/use_cases.py:125-129` checks `conversation.guest_id is None` *before* `contact_kind_for(conversation.channel)`, the opposite order. The implementation is intentional; fix the prose so it no longer claims "same precedence" for an ordering that was inverted.
- **exact resume command**: `/sdd:archive human-reply-outbound-delivery` (acknowledged by deleting this entry before archive)


## `tasks.md:46` task 1.6(c) wording contradicts the implementation (qa finding, low)

- **phase**: review
- **type**: deferred
- **what & why**: `sdd/changes/human-reply-outbound-delivery/tasks.md:46` R1.2 task 1.6(c) says "(c) `AIRBNB_MSG` (sin adapter) → `delivery_status=FAILED`, `delivery_error_code=ADAPTER_UNAVAILABLE`, sin `HUMAN_RESPONSE_SENT` levantado" — but the implementation (lines 101-102 of the same file, design D3) and the test at `backend/tests/messaging/test_use_cases.py:1061` assert `HUMAN_RESPONSE_SENT` **is** emitted. The test asserts the opposite of the task wording, and the implementation matches design D3. Code is correct; remove the "sin `HUMAN_RESPONSE_SENT` levantado" clause from task 1.6(c) so the wording matches the test and the implementation note.
- **exact resume command**: `/sdd:archive human-reply-outbound-delivery` (acknowledged by deleting this entry before archive)


## Missing positive SMTP-branch test for `EMAIL` channel (qa finding, R2.1 coverage gap)

- **phase**: review
- **type**: deferred
- **what & why**: No unit test in `backend/tests/messaging/` that mocks `smtp_host=True` and asserts `SMTPEmailAdapter` is the `EMAIL` delegate in `outbound_registry`. The selection logic lives in `_email_adapter` (`backend/app/notifications/infrastructure/adapters.py:410-423`) and is covered by notifications-module tests, but the messaging-side wiring change has no positive SMTP test of its own. Add a test in `backend/tests/messaging/test_channels.py` that mocks `smtp_host=True` and asserts the EMAIL delegate is `SMTPEmailAdapter`.
- **exact resume command**: `/sdd:archive human-reply-outbound-delivery` (acknowledged by deleting this entry before archive)