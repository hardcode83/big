/**
 * Logout pub/sub for `useLogoutMutation`.
 *
 * `useLogoutMutation` lives in `features/auth/hooks/` (a feature module) and
 * therefore cannot directly mutate the React state owned by `AuthProvider`
 * (a `lib/auth` module). The same problem existed for session expiration
 * (`lib/api/authenticated-client.ts:13-26`): a global Set of listeners that
 * both ends reach by convention — the notifier does not import the listener.
 *
 * `AuthProvider` subscribes via `useEffect` and clears `user` / `status` to
 * match the freshly-purged local store. `useLogoutMutation` notifies after its
 * `try/finally` has finished, so the listener never runs before the cache,
 * tokens and presence cookie are gone.
 */
type LogoutListener = () => void;
const logoutListeners = new Set<LogoutListener>();

export function subscribeToLogout(listener: LogoutListener): () => void {
  logoutListeners.add(listener);
  return () => logoutListeners.delete(listener);
}

export function notifyLogout(): void {
  for (const listener of logoutListeners) {
    listener();
  }
}