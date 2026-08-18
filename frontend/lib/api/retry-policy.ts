import { ApiError } from "./errors";

/** Shared transient retry policy. Keep this behavior identical to dashboard's original policy. */
export function retryPolicy(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < 2;
}
