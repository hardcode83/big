"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { ResolvedProvenance } from "./provenance";

/**
 * Provenance panel: pairs what is on screen with the Pull Request that produced it
 * (change app-version-visibility, R4.1-R4.7, R5.3-R5.4).
 *
 * PLACEMENT IS STRUCTURAL, NOT A SECURITY BOUNDARY (R4.6). It is mounted only from
 * `WorkspaceShell`, the operator surface, because the links name the private repository
 * and the Pull Request. But `auth-tenancy` did not touch the frontend: there is no login,
 * no session and no access control in the UI yet, so "workspace only" means "on the
 * operation surface by route registry" and nothing more. NOTHING that requires real
 * protection may be put in here. When the frontend gains authentication (roadmap entry
 * `dashboard-web`), the panel inherits it by sitting on that surface — it must not grow a
 * check of its own (R4.7).
 *
 * A client island receiving props already resolved on the server, the same shape as
 * `Sidebar` and `SkipLink`: the interactivity is the client's concern, resolving the data
 * is the server's.
 */
export interface ProvenancePanelLabels {
  trigger: string;
  title: string;
  closeLabel: string;
  commit: string;
  pullRequest: string;
  /** Notación del número de PR (`#`). En el catálogo por R4.5: es texto visible. */
  prPrefix: string;
  noPullRequest: string;
  builtAt: string;
  runId: string;
  ref: string;
  unknown: string;
  frontendVersion: string;
  backendVersion: string;
  driftWarning: string;
  checking: string;
}

export function ProvenancePanel({
  labels,
  provenance,
  frontendVersion,
}: {
  labels: ProvenancePanelLabels;
  provenance: ResolvedProvenance;
  frontendVersion: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

  async function handleOpenChange(next: boolean) {
    setOpen(next);
    // Fetched on OPEN, never during render: this is what keeps the shell renderable
    // without a backend and `BACKEND_INTERNAL_URL` unread at shell render (design D9).
    if (!next || checked) return;
    try {
      const response = await fetch("/deployment/version", {
        cache: "no-store",
      });
      const body = (await response.json()) as { backend?: unknown };
      setBackendVersion(typeof body.backend === "string" ? body.backend : null);
    } catch {
      // The panel degrades to "unknown"; it never surfaces an error state, because a
      // diagnostics surface that itself breaks is worse than one that admits ignorance.
      setBackendVersion(null);
    } finally {
      setChecked(true);
    }
  }

  // Drift is only claimed when BOTH versions are known and differ. An unknown backend is
  // not drift — asserting it would cry wolf every time the backend is merely unreachable.
  const drifted =
    checked &&
    frontendVersion !== null &&
    backendVersion !== null &&
    frontendVersion !== backendVersion;

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="sm" data-testid="provenance-trigger">
          {labels.trigger}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" closeLabel={labels.closeLabel}>
        <SheetHeader>
          <SheetTitle>{labels.title}</SheetTitle>
        </SheetHeader>

        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <Row label={labels.frontendVersion}>
            <span className="font-mono">
              {frontendVersion ?? labels.unknown}
            </span>
          </Row>
          <Row label={labels.backendVersion}>
            <span className="font-mono" data-testid="backend-version">
              {!checked ? labels.checking : (backendVersion ?? labels.unknown)}
            </span>
          </Row>
          <Row label={labels.pullRequest}>
            {provenance.prHref && provenance.pr ? (
              <a
                className="underline underline-offset-2"
                href={provenance.prHref}
                data-testid="pr-link"
              >
                {labels.prPrefix}
                {provenance.pr}
              </a>
            ) : (
              <span data-testid="no-pr">{labels.noPullRequest}</span>
            )}
          </Row>
          <Row label={labels.commit}>
            {provenance.commitHref && provenance.commitShort ? (
              <a
                className="font-mono underline underline-offset-2"
                href={provenance.commitHref}
                data-testid="commit-link"
              >
                {provenance.commitShort}
              </a>
            ) : (
              <span className="font-mono">
                {provenance.commitShort ?? labels.unknown}
              </span>
            )}
          </Row>
          <Row label={labels.builtAt}>
            <span className="font-mono">
              {provenance.builtAt ?? labels.unknown}
            </span>
          </Row>
          <Row label={labels.runId}>
            {provenance.runHref && provenance.runId ? (
              <a
                className="font-mono underline underline-offset-2"
                href={provenance.runHref}
                data-testid="run-link"
              >
                {provenance.runId}
              </a>
            ) : (
              <span className="font-mono">
                {provenance.runId ?? labels.unknown}
              </span>
            )}
          </Row>
          <Row label={labels.ref}>
            <span className="font-mono">
              {provenance.ref ?? labels.unknown}
            </span>
          </Row>
        </dl>

        {drifted ? (
          <p
            role="alert"
            className="text-sm font-medium"
            data-testid="drift-warning"
          >
            {labels.driftWarning}
          </p>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-all">{children}</dd>
    </>
  );
}
