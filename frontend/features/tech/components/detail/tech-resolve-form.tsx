"use client";

import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

const MAX_FINAL_COST = 99999999.99;
const MAX_MATERIALS = 2000;

/**
 * Which local rule, if any, stops the request. Local validation only **prevents
 * emitting** (R4.5); everything else is the server's call.
 */
export function validateFinalCost(
  raw: string,
): "required" | "negative" | "tooLarge" | "decimals" | "format" | null {
  const trimmed = raw.trim();

  // `required` means nothing was typed, and nothing else. A comma decimal
  // (`"5,00"` — what a Spanish numeric keypad offers) used to land here via
  // `Number()` returning `NaN`, naming a rule the technician had not broken.
  if (!trimmed) return "required";

  // A sign is a value problem, so it keeps its own message.
  if (/^-\d/.test(trimmed)) return "negative";

  // The rule mirrored here is **R4.1** — "número >= 0, <= 99 999 999,99, como
  // mucho dos decimales" — which is also the server's own rule: `final_cost` is
  // `Annotated[Decimal, Field(ge=0, le=MAX_COST, decimal_places=2)]` in
  // `backend/app/maintenance/api/schemas.py`.
  //
  // It is deliberately **not** the `final_cost` string pattern published in
  // `backend/openapi.json`, which is lossier than the schema it describes in
  // both directions: it admits `"5.100"`, which `decimal_places=2` rejects, and
  // it admits a leading `+`, which this form never produces because the control
  // is an `<input type="number">`. Mirroring the pattern instead of the rule
  // would therefore let a value through to a guaranteed 422.
  //
  // What local validation may not do is refuse a value the server would take
  // and call it the technician's mistake (R4.5 — it only prevents emitting).
  // `"5."` and `".5"` are the cases that matters for: an earlier revision
  // rejected them as malformed although `Decimal("5.")` is `5`.
  if (!/^(?!\.?$)\d*\.?\d*$/.test(trimmed)) return "format";

  if (Number(trimmed) > MAX_FINAL_COST) return "tooLarge";

  // Precision gets its own message rather than collapsing into the shape one.
  if (!/^(?!\.?$)\d*\.?\d{0,2}$/.test(trimmed)) return "decimals";
  return null;
}

/**
 * The close form, offered only in `IN_PROGRESS` (R4.1, design D12).
 *
 * Native elements with Tailwind classes, following
 * `features/conversations/components/thread/conversation-reply-form.tsx`:
 * `components/ui/` has no form primitives and adding them is scope nobody asked
 * for. `finalCost` leaves as the **string the technician typed** — a float
 * round-trip of a money value is the corruption its string representation
 * exists to prevent — and empty `materials` is omitted by the data source.
 */
export function TechResolveForm({
  onSubmit,
  isPending,
  serverError,
}: {
  onSubmit: (input: { finalCost: string; materials?: string }) => void;
  isPending: boolean;
  serverError?: string;
}) {
  const { t } = useTranslation("tech");
  const [finalCost, setFinalCost] = useState("");
  const [materials, setMaterials] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const failure = validateFinalCost(finalCost);
    if (failure) {
      setLocalError(t(`resolve.errors.${failure}`));
      return;
    }
    setLocalError(null);
    // The form is NOT cleared here: a `422` must find what was typed still in
    // place (R4.5).
    onSubmit({ finalCost: finalCost.trim(), materials });
  };

  const error = localError ?? serverError;

  return (
    // `noValidate`: the browser's own constraint bubbles are written in the
    // *browser's* language, not the app's, so letting them fire would put a
    // visible string outside `locales/` (R6.1). The attributes below stay —
    // they still give a numeric keypad and a stepper — but what speaks to the
    // technician is `validateFinalCost` and the `tech` catalog.
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-3">
      <h2 className="text-body-lg font-semibold text-foreground">
        {t("resolve.title")}
      </h2>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="tech-final-cost"
          className="mb-1 block text-xs font-medium text-muted-foreground"
        >
          {t("resolve.finalCost")}
        </label>
        <input
          id="tech-final-cost"
          type="number"
          step="0.01"
          min="0"
          max="99999999.99"
          required
          className="tap-target rounded-md border bg-background px-3 py-2 text-sm"
          value={finalCost}
          aria-invalid={error ? true : undefined}
          onChange={(event) => setFinalCost(event.target.value)}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="tech-materials"
          className="mb-1 block text-xs font-medium text-muted-foreground"
        >
          {t("resolve.materials")}
        </label>
        <textarea
          id="tech-materials"
          rows={3}
          maxLength={MAX_MATERIALS}
          className="rounded-md border bg-background px-3 py-2 text-sm"
          value={materials}
          onChange={(event) => setMaterials(event.target.value)}
        />
      </div>

      {error ? (
        <p role="alert" className="text-body-base text-state-error-text">
          {error}
        </p>
      ) : null}

      <Button type="submit" className="tap-target" disabled={isPending}>
        {t("resolve.submit")}
      </Button>
    </form>
  );
}
