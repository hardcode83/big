/**
 * Public entry point for the `/statements` screen (task 6.3). Only
 * `StatementsPage` is exposed: hooks, types, and modules are internal — tests
 * reach them by relative path, the same discipline
 * `features/reviews/index.ts` and `features/pricing/index.ts` already follow.
 *
 * The page (`frontend/app/(workspace)/statements/page.tsx`) imports this
 * barrel and nothing else from the feature, so the route file stays a thin
 * server composition (generateMetadata + routeMetadata + the view) and the
 * App Router cannot drag internal modules into the browser bundle by accident.
 */
export { StatementsPage } from "./components/statements-page";
