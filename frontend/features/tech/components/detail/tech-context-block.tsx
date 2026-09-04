"use client";

import { useTranslation } from "react-i18next";

import { Card } from "@/components/ui/card";
import type { IncidentContextDto } from "@/features/incidents";

/**
 * Where the flat is and how to get into it (R2.3), entirely from
 * `GET /incidents/{id}/context`. No route of `/api/v1/properties/…` is called
 * and no storage URL is built here: the `TECHNICIAN` role has no
 * `READ_PROPERTIES`, and this projection exists precisely for that (R2.5).
 *
 * `accessNotes` is rendered **verbatim**, neither masked nor restructured. That
 * is not an oversight: exception 6 of the rule-11 census in
 * `sdd/steering/security.md` authorises it and names the assigned technician as
 * one of its three declared readers.
 */
export function TechContextBlock({ context }: { context: IncidentContextDto }) {
  const { t } = useTranslation("tech");

  const addressLines = [
    context.addressLine1,
    context.addressLine2,
    [context.postalCode, context.city].filter(Boolean).join(" "),
    context.province,
    context.country,
  ].filter((line): line is string => Boolean(line));

  return (
    <section>
      <Card className="flex flex-col gap-2 p-4">
        <h2 className="text-body-lg font-semibold text-foreground">
          {t("context.title")}
        </h2>

        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-body-base">
          <dt className="text-muted-foreground">{t("context.propertyName")}</dt>
          <dd className="text-foreground">{context.propertyName}</dd>
          <dt className="text-muted-foreground">
            {t("context.propertyInternalCode")}
          </dt>
          <dd className="text-foreground">{context.propertyInternalCode}</dd>
          <dt className="text-muted-foreground">{t("context.timezone")}</dt>
          <dd className="text-foreground">{context.timezone}</dd>
        </dl>

        {addressLines.length > 0 ? (
          <div>
            <h3 className="text-body-base text-muted-foreground">
              {t("context.address")}
            </h3>
            <address className="not-italic text-body-base text-foreground">
              {addressLines.map((line) => (
                <span key={line} className="block">
                  {line}
                </span>
              ))}
            </address>
          </div>
        ) : null}

        {context.accessNotes ? (
          <div>
            <h3 className="text-body-base text-muted-foreground">
              {t("context.accessNotes")}
            </h3>
            <p className="whitespace-pre-wrap text-body-base text-foreground">
              {context.accessNotes}
            </p>
          </div>
        ) : null}

        {context.assignmentNote ? (
          <div>
            <h3 className="text-body-base text-muted-foreground">
              {t("context.assignmentNote")}
            </h3>
            <p className="whitespace-pre-wrap text-body-base text-foreground">
              {context.assignmentNote}
            </p>
          </div>
        ) : null}
      </Card>
    </section>
  );
}
