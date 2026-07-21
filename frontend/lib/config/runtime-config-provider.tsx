"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { PublicRuntimeConfig } from "./public";

/**
 * Client access to the public configuration snapshot produced on the server and
 * handed down through the provider tree (design D15). Client code reads config
 * through this hook instead of touching `process.env`.
 */
const RuntimeConfigContext = createContext<PublicRuntimeConfig | null>(null);

export function RuntimeConfigProvider({
  config,
  children,
}: {
  config: PublicRuntimeConfig;
  children: ReactNode;
}) {
  return (
    <RuntimeConfigContext.Provider value={config}>
      {children}
    </RuntimeConfigContext.Provider>
  );
}

export function useRuntimeConfig(): PublicRuntimeConfig {
  const config = useContext(RuntimeConfigContext);
  if (config === null) {
    throw new Error(
      "useRuntimeConfig must be used within a RuntimeConfigProvider",
    );
  }
  return config;
}
