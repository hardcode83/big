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

  // The shape the published contract accepts, minus the sign: see the
  // `final_cost` pattern of `ResolveIncidentRequest` in `backend/openapi.json`.
  // Mirrored rather than tightened. An earlier revision of this function
  // rejected `"5."` and `".5"`, which that pattern accepts and R4.1 permits —
  // refusing locally what the server would take is the one thing D12 says local
  // validation must not do.
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
      <h2 className="text-base font-semibold text-foreground">
        {t("resolve.title")}
      </h2>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="tech-final-cost"
          className="text-sm text-muted-foreground"
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
          className="min-h-11 rounded-md border bg-background px-3 py-2 text-sm"
          value={finalCost}
          aria-invalid={error ? true : undefined}
          onChange={(event) => setFinalCost(event.target.value)}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="tech-materials"
          className="text-sm text-muted-foreground"
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
        <p role="alert" className="text-sm text-state-error-text">
          {error}
        </p>
      ) : null}

      <Button type="submit" className="min-h-11" disabled={isPending}>
        {t("resolve.submit")}
      </Button>
    </form>
  );
}
