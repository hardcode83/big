"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { createApiClient } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { getSessionTokens } from "@/lib/auth/session-store";
import { useRuntimeConfig } from "@/lib/config/runtime-config-provider";

type Provenance = {
  repository_url: string;
  pull_request_number: number;
  commit_sha: string;
  actions_run_id: number;
};

type PanelState = "closed" | "loading" | "ready" | "unknown" | "error";

function isComplete(value: Provenance | null | undefined): value is Provenance {
  return Boolean(
    value?.repository_url &&
      Number.isInteger(value.pull_request_number) &&
      value.pull_request_number > 0 &&
      /^[0-9a-f]{40}$/.test(value.commit_sha) &&
      Number.isInteger(value.actions_run_id) &&
      value.actions_run_id > 0,
  );
}

export function ProvenancePanel() {
  const { t } = useTranslation("common");
  const { apiBaseUrl } = useRuntimeConfig();
  const { status } = useAuth();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<PanelState>("closed");
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<Provenance | null>(null);

  async function openPanel() {
    setOpen(true);
    if (state !== "closed") return;
    if (status !== "authenticated" || !getSessionTokens()) {
      setState("unknown");
      return;
    }
    setState("loading");
    try {
      const client = createApiClient({
        baseUrl: apiBaseUrl,
        getHeaders: () => {
          const tokens = getSessionTokens();
          const headers: HeadersInit = {};
          if (tokens) headers.Authorization = `Bearer ${tokens.accessToken}`;
          return headers;
        },
      });
      const response = await client.request("/api/v1/provenance");
      setAppVersion(response.app_version);
      setProvenance(isComplete(response.provenance) ? response.provenance : null);
      setState(isComplete(response.provenance) ? "ready" : "unknown");
    } catch {
      setState("error");
    }
  }

  const links = isComplete(provenance)
    ? [
        { href: provenance.repository_url, label: t("provenance.repository") },
        {
          href: `${provenance.repository_url}/pull/${provenance.pull_request_number}`,
          label: t("provenance.pullRequest"),
        },
        {
          href: `${provenance.repository_url}/commit/${provenance.commit_sha}`,
          label: t("provenance.commit"),
        },
        {
          href: `${provenance.repository_url}/actions/runs/${provenance.actions_run_id}`,
          label: t("provenance.actionsRun"),
        },
      ]
    : [];

  return (
    <div className="relative">
      <button
        type="button"
        className="text-xs text-muted-foreground underline-offset-4 hover:underline"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : void openPanel())}
      >
        {t("provenance.open")}
      </button>
      {open && (
        <div className="absolute bottom-8 right-0 z-10 w-72 rounded-md border bg-background p-3 text-xs shadow-md">
          <p className="font-medium">{t("provenance.title")}</p>
          {state === "loading" && <p>{t("provenance.loading")}</p>}
          {state === "error" && <p>{t("provenance.error")}</p>}
          {state === "unknown" && (
            <>
              {appVersion && <p className="mt-1">{appVersion}</p>}
              <p>{t("provenance.unknown")}</p>
            </>
          )}
          {state === "ready" && (
            <>
              <p className="mt-1">{appVersion}</p>
              <ul className="mt-2 space-y-1">
                {links.map((link) => (
                  <li key={link.href}>
                    <a className="underline" href={link.href} target="_blank" rel="noreferrer">
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
