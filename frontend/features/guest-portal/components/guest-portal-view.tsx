"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/states";
import { LoadingState } from "@/components/states";
import { ApiError } from "@/lib/api";
import { GuestField } from "./fields/guest-fields";
import { useStayInfo } from "../hooks/use-stay-info";
import { useCheckinStatus, useSubmitCheckin } from "../hooks/use-checkin";
import { useReportIncident } from "../hooks/use-report-incident";
import { useConversation, usePostMessage } from "../hooks/use-conversation";
import type { GuestPortalDTOs } from "../data";

type Translate = (key: string) => string;

function isNotFound(error: unknown) {
  return error instanceof ApiError && error.status === 404;
}

/**
 * The same mapping as `errorText`, minus the one clause that only makes sense after a *send*.
 *
 * `guest:errors.rateLimit` says "we do not know whether what you sent was received", which is the
 * right thing to tell someone whose submission may or may not have landed — and the wrong thing
 * entirely to show for a `429` on a plain `GET`, where the guest has typed nothing. The portal's
 * six routes share one 60/min budget, so a first load can be rate limited on its own; the i18n
 * panel of sections 9-10 found this surviving in the read path after the same defect had been
 * fixed for a failed refresh.
 *
 * Only the `429` differs: `413`, `422` and the generic copy say nothing about sending.
 */
function readErrorText(error: unknown, t: Translate) {
  if (error instanceof ApiError && error.status === 429) {
    return t("guest:conversation.rateLimited");
  }
  return errorText(error, t);
}

function errorText(error: unknown, t: Translate) {
  if (error instanceof ApiError && error.status === 429) return t("guest:errors.rateLimit");
  if (error instanceof ApiError && error.status === 413) return t("guest:errors.tooLarge");
  if (error instanceof ApiError && error.status === 422) return t("guest:errors.validation");
  return t("guest:errors.generic");
}

/**
 * Maps a `422 VALIDATION_ERROR` envelope to per-field errors (R2.3, R3.2, D7).
 * The backend publishes `details.errors: [{ loc, msg, type }]` (PRD §23); we read
 * only the field name from `loc` and render a localized message — never the raw
 * body, trace, backend `msg`, or the rejected value.
 */
function fieldErrorsFrom422(error: unknown, allowed: readonly string[], t: Translate): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  const details = error.details as { errors?: Array<{ loc?: unknown[] }> } | undefined;
  const result: Record<string, string> = {};
  for (const entry of details?.errors ?? []) {
    const loc = Array.isArray(entry.loc) ? entry.loc : [];
    const field = String(loc[loc.length - 1] ?? "");
    if (field && allowed.includes(field)) result[field] = t("guest:errors.invalidField");
  }
  return result;
}

const CHECKIN_FIELDS = [
  "full_name",
  "nationality",
  "date_of_birth",
  "document_type",
  "document_number",
  "document_expiry_date",
] as const satisfies readonly (keyof GuestPortalDTOs.SubmitCheckin)[];

const INCIDENT_FIELDS = ["title", "description"] as const;

function OptionalValue({ value, fallback }: { value: string | null; fallback: string }) {
  return <>{value ?? fallback}</>;
}

function StayInfoSection({ token }: { token: string }) {
  const { t } = useTranslation();
  const query = useStayInfo(token);
  if (query.isPending) return <LoadingState label={t("guest:loading")} />;
  if (query.isError)
    return (
      <ErrorState
        title={t("guest:errors.title")}
        description={errorText(query.error, t)}
        onRetry={() => void query.refetch()}
        retryLabel={t("guest:retry")}
      />
    );
  const stay = query.data;
  const unavailable = t("guest:unavailable");
  const address = [stay.addressLine1, stay.addressLine2, stay.city, stay.province, stay.postalCode]
    .filter(Boolean)
    .join(t("guest:listSeparator"));
  return (
    <section aria-labelledby="stay-title" className="space-y-4">
      <h2 id="stay-title" className="text-xl font-semibold">
        {t("guest:stay.title")}
      </h2>
      <h3 className="text-lg">{stay.propertyName}</h3>
      <dl className="grid gap-2 text-sm">
        <div>
          <dt className="font-medium">{t("guest:stay.dates")}</dt>
          <dd>
            {stay.checkInDate} {stay.checkInTime} – {stay.checkOutDate} {stay.checkOutTime}
          </dd>
        </div>
        <div>
          <dt className="font-medium">{t("guest:stay.address")}</dt>
          <dd>
            <OptionalValue value={address || null} fallback={unavailable} />
          </dd>
        </div>
        <div>
          <dt className="font-medium">{t("guest:stay.wifi")}</dt>
          <dd>
            <OptionalValue value={stay.wifiName} fallback={unavailable} />
          </dd>
        </div>
        <div>
          <dt className="font-medium">{t("guest:stay.instructions")}</dt>
          <dd>
            <OptionalValue value={stay.arrivalNotes} fallback={unavailable} />
          </dd>
        </div>
        <div>
          <dt className="font-medium">{t("guest:stay.accessCode")}</dt>
          <dd>
            <OptionalValue value={stay.accessCodeMasked} fallback={unavailable} />
          </dd>
        </div>
        <div>
          <dt className="font-medium">{t("guest:stay.support")}</dt>
          <dd>
            <OptionalValue value={stay.supportChannel} fallback={unavailable} />
          </dd>
        </div>
      </dl>
    </section>
  );
}

function CheckinSection({ token }: { token: string }) {
  const { t } = useTranslation();
  const status = useCheckinStatus(token);
  const mutation = useSubmitCheckin(token);
  const [values, setValues] = useState<GuestPortalDTOs.SubmitCheckin>({
    full_name: "",
    nationality: "",
    date_of_birth: "",
    document_type: "DNI",
    document_number: "",
    document_expiry_date: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const update =
    (key: keyof GuestPortalDTOs.SubmitCheckin) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setValues((current) => ({ ...current, [key]: event.target.value }));
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const next = Object.fromEntries(
      Object.entries(values)
        .filter(([, value]) => !value.trim())
        .map(([key]) => [key, t("guest:errors.required")]),
    ) as Record<string, string>;
    setErrors(next);
    if (Object.keys(next).length === 0) mutation.mutate(values);
  };
  if (status.isPending) return <LoadingState label={t("guest:loading")} />;
  if (status.isError && isNotFound(status.error))
    return <ErrorState title={t("guest:invalid.title")} description={t("guest:invalid.description")} />;
  if (status.isError)
    return (
      <ErrorState
        title={t("guest:errors.title")}
        description={errorText(status.error, t)}
        onRetry={() => void status.refetch()}
        retryLabel={t("guest:retry")}
      />
    );
  const serverErrors = fieldErrorsFrom422(mutation.error, CHECKIN_FIELDS, t);
  const fieldError = (key: (typeof CHECKIN_FIELDS)[number]) => errors[key] ?? serverErrors[key];
  return (
    <section aria-labelledby="checkin-title" className="space-y-4">
      <h2 id="checkin-title" className="text-xl font-semibold">
        {t("guest:checkin.title")}
      </h2>
      <p>{t("guest:checkin.missing", { fields: status.data.missingFields.join(t("guest:listSeparator")) || t("guest:checkin.none") })}</p>
      <form noValidate onSubmit={submit} className="space-y-4">
        <GuestField id="full_name" label={t("guest:fields.fullName")} value={values.full_name} error={fieldError("full_name")} onChange={update("full_name")} />
        <GuestField id="nationality" label={t("guest:fields.nationality")} value={values.nationality} error={fieldError("nationality")} onChange={update("nationality")} />
        <GuestField id="date_of_birth" type="date" label={t("guest:fields.birthDate")} value={values.date_of_birth} error={fieldError("date_of_birth")} onChange={update("date_of_birth")} />
        <GuestField id="document_type" label={t("guest:fields.documentType")} value={values.document_type} error={fieldError("document_type")} onChange={update("document_type")} as="select">
          <option value="DNI">{t("guest:documentTypes.DNI")}</option>
          <option value="NIE">{t("guest:documentTypes.NIE")}</option>
          <option value="PASSPORT">{t("guest:documentTypes.PASSPORT")}</option>
          <option value="RESIDENCE_CARD">{t("guest:documentTypes.RESIDENCE_CARD")}</option>
          <option value="OTHER">{t("guest:documentTypes.OTHER")}</option>
        </GuestField>
        <GuestField id="document_number" label={t("guest:fields.documentNumber")} value={values.document_number} error={fieldError("document_number")} onChange={update("document_number")} />
        <GuestField id="document_expiry_date" type="date" label={t("guest:fields.expiryDate")} value={values.document_expiry_date} error={fieldError("document_expiry_date")} onChange={update("document_expiry_date")} />
        <div role="alert" aria-live="polite">
          {mutation.isPending
            ? t("guest:checkin.sending")
            : mutation.isError
              ? errorText(mutation.error, t)
              : mutation.isSuccess
                ? `${t("guest:checkin.success")} ${t(`guest:status.${mutation.data.documentStatus}`)} / ${t(`guest:status.${mutation.data.legalRegistrationStatus}`)}`
                : null}
        </div>
        <Button type="submit" disabled={mutation.isPending}>
          {t("guest:checkin.submit")}
        </Button>
      </form>
    </section>
  );
}

function IncidentSection({ token }: { token: string }) {
  const { t } = useTranslation();
  const mutation = useReportIncident(token);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [invalid, setInvalid] = useState(false);
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const bad = !title.trim() || !description.trim();
    setInvalid(bad);
    if (!bad) mutation.mutate({ title: title.trim(), description: description.trim() });
  };
  const serverErrors = fieldErrorsFrom422(mutation.error, INCIDENT_FIELDS, t);
  const titleError = (invalid && !title.trim() ? t("guest:errors.required") : undefined) ?? serverErrors.title;
  const descriptionError =
    (invalid && !description.trim() ? t("guest:errors.required") : undefined) ?? serverErrors.description;
  return (
    <section aria-labelledby="incident-title" className="space-y-4">
      <h2 id="incident-title" className="text-xl font-semibold">
        {t("guest:incident.title")}
      </h2>
      <form noValidate onSubmit={submit} className="space-y-4">
        <GuestField id="title" label={t("guest:incident.titleField")} value={title} error={titleError} onChange={(e) => setTitle(e.target.value)} />
        <GuestField id="description" label={t("guest:incident.description")} value={description} error={descriptionError} onChange={(e) => setDescription(e.target.value)} as="textarea" />
        <div role="alert" aria-live="polite">
          {mutation.isPending
            ? t("guest:incident.sending")
            : mutation.isError
              ? errorText(mutation.error, t)
              : mutation.isSuccess
                ? `${t("guest:incident.success")} ${t(`guest:incident.status.${mutation.data.status}`)}`
                : null}
        </div>
        <Button type="submit" disabled={mutation.isPending}>
          {t("guest:incident.submit")}
        </Button>
      </form>
    </section>
  );
}

/**
 * The guest's thread (R5.1-R5.8, design D10).
 *
 * Its own `useQuery`/`useMutation` and its own states, like its three siblings: R5.1 requires
 * that a failure here does not take the stay, check-in or incident sections down with it, and
 * separate hooks are what make that structural rather than careful. R5.2 comes free from where
 * it is mounted — `GuestPortalView` returns before rendering any section while `info` has not
 * authorised, so a dead link never shows this form.
 *
 * Every message is labelled from the **grouped** sender the API publishes and nothing finer:
 * R5.5 forbids deriving the AI/person distinction here, and there is nothing to derive it from,
 * since `sender` only ever holds `GUEST` or `PROPERTY`.
 */
function ConversationSection({ token }: { token: string }) {
  const { t } = useTranslation();
  const thread = useConversation(token);
  const mutation = usePostMessage(token);
  const [draft, setDraft] = useState("");
  const [invalid, setInvalid] = useState(false);
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const bad = !draft.trim();
    setInvalid(bad);
    if (bad) return;
    mutation.mutate(
      { content: draft.trim() },
      // Cleared only once the send succeeded: on a `429` or a network error the guest keeps
      // what they typed, because R5.8 forbids presenting a retry as proof it was not received —
      // and emptying the box would be exactly that, in the most misleading form.
      { onSuccess: () => setDraft("") },
    );
  };
  return (
    <section aria-labelledby="conversation-title" className="space-y-4">
      <h2 id="conversation-title" className="text-xl font-semibold">
        {t("guest:conversation.title")}
      </h2>

      {thread.isPending ? (
        <LoadingState label={t("guest:conversation.loading")} />
      ) : thread.isError && !thread.data ? (
        // Only when there is nothing to show. A poll that fails **after** the thread loaded must
        // not replace it: TanStack Query flips `status` to `error` on any failed fetch, including
        // a background `refetchInterval` tick, so branching on `isError` alone made a single
        // `429` — plausible precisely because six routes share one budget — blank a conversation
        // the guest was reading, and replace it with copy about a message they never sent. Found
        // and reproduced by the QA panel of sections 9-10.
        <ErrorState
          title={t("guest:conversation.errorTitle")}
          description={readErrorText(thread.error, t)}
          onRetry={() => void thread.refetch()}
          retryLabel={t("guest:retry")}
        />
      ) : (
        <>
          {/* A refresh failed while we still hold a thread: say so, keep the history, and do not
              reuse the send-oriented copy — nothing was sent. */}
          {thread.isError ? (
            <p role="status">{t("guest:conversation.staleNotice")}</p>
          ) : null}
          {thread.data.items.length === 0 ? (
            <p>{t("guest:conversation.empty")}</p>
          ) : (
            <ol className="space-y-3">
              {thread.data.items.map((item) => (
                <li key={item.id} className="space-y-1">
                  <span className="block text-sm font-medium">
                    {item.sender === "GUEST"
                      ? t("guest:conversation.you")
                      : t("guest:conversation.property")}
                  </span>
                  <p className="whitespace-pre-wrap break-words">{item.content}</p>
                </li>
              ))}
            </ol>
          )}
          {/* R5.6: the closed state the API publishes, and never the reason behind it. */}
          {thread.data.state === "AWAITING_HUMAN" ? (
            <p>{t("guest:conversation.awaitingHuman")}</p>
          ) : null}
        </>
      )}

      <form noValidate onSubmit={submit} className="space-y-4">
        <GuestField
          id="content"
          label={t("guest:conversation.field")}
          value={draft}
          error={invalid && !draft.trim() ? t("guest:errors.required") : undefined}
          onChange={(e) => setDraft(e.target.value)}
          as="textarea"
        />
        <div role="alert" aria-live="polite">
          {mutation.isPending
            ? t("guest:conversation.sending")
            : mutation.isError
              ? errorText(mutation.error, t)
              : mutation.isSuccess
                ? t("guest:conversation.sent")
                : null}
        </div>
        <Button type="submit" disabled={mutation.isPending}>
          {t("guest:conversation.send")}
        </Button>
      </form>
    </section>
  );
}

export function GuestPortalView({ token }: { token: string }) {
  const stay = useStayInfo(token);
  const { t } = useTranslation();
  if (stay.isPending)
    return (
      <main className="mx-auto max-w-xl p-4">
        <LoadingState label={t("guest:loading")} />
      </main>
    );
  if (stay.isError && isNotFound(stay.error))
    return (
      <main className="mx-auto max-w-xl p-4">
        <ErrorState title={t("guest:invalid.title")} description={t("guest:invalid.description")} />
      </main>
    );
  if (stay.isError)
    return (
      <main className="mx-auto max-w-xl p-4">
        <ErrorState
          title={t("guest:errors.title")}
          description={errorText(stay.error, t)}
          onRetry={() => void stay.refetch()}
          retryLabel={t("guest:retry")}
        />
      </main>
    );
  return (
    <main className="mx-auto max-w-xl space-y-8 p-4">
      <StayInfoSection token={token} />
      <CheckinSection token={token} />
      <IncidentSection token={token} />
      <ConversationSection token={token} />
    </main>
  );
}
