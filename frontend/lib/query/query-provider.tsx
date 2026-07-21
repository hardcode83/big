"use client";

import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";

import { getQueryClient } from "./query-client";

export function QueryProvider({ children }: { children: ReactNode }) {
  // getQueryClient returns the stable per-browser client (design D11).
  const queryClient = getQueryClient();
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
