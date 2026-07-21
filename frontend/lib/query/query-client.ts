import { isServer, QueryClient } from "@tanstack/react-query";

/**
 * TanStack Query setup (design D11). The shell creates a stable QueryClient per
 * browser session but declares and runs no queries itself — features define
 * their own query options and stale times. Mutations do not retry by default.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

/**
 * A fresh client on the server (never shared between requests) and a single
 * stable client in the browser (stable across re-renders of the provider).
 */
export function getQueryClient(): QueryClient {
  if (isServer) {
    return makeQueryClient();
  }
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}
