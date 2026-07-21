"use client";

import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { buildBreadcrumbs } from "../navigation/breadcrumbs";
import type { ShellProfile } from "../navigation/route-registry";

/** Breadcrumb trail from the registry chain (design D5). No raw path segments. */
export function Breadcrumbs({ profile }: { profile: ShellProfile }) {
  const pathname = usePathname() ?? "/";
  const { t } = useTranslation("navigation");
  const keys = buildBreadcrumbs(pathname, profile);

  if (keys.length === 0) {
    return null;
  }

  return (
    <nav aria-label={t("breadcrumb")}>
      <ol className="flex items-center gap-2 text-sm text-muted-foreground">
        {keys.map((key, index) => {
          const isLast = index === keys.length - 1;
          return (
            <li key={key} className="flex items-center gap-2">
              <span
                aria-current={isLast ? "page" : undefined}
                className={isLast ? "font-medium text-foreground" : undefined}
              >
                {t(key)}
              </span>
              {isLast ? null : (
                <ChevronRight className="size-3.5" aria-hidden="true" />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
