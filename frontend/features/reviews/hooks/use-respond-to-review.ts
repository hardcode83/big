"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getReviewsDataSource,
  type CreateReviewInput,
  type RespondInput,
  type Review,
} from "../data";
import { reviewsKeys } from "./query-keys";

/**
 * Approves, ignores, marks-as-posted, or edits a review's draft (design D8).
 *
 * It **invalidates and never patches the cache optimistically** (R3.4), which
 * makes R3.5 and R3.7 free rather than extra work: there is no instant in which
 * a row shows a decision the backend did not confirm — and the `409` that R3.5
 * makes visible is precisely the case where an optimistic patch would have lied.
 *
 * `retry: false`: a rejected write is not retried. Retrying a `409` would re-ask
 * a question already answered, and retrying a `403` would never start succeeding.
 *
 * The invalidation runs in **`onSettled`, so on failure as well as on success**.
 * That is not symmetry for its own sake: after a `409` the row on screen is, by
 * definition, in a state this client no longer believes, so the list has to
 * be refetched precisely when the write failed.
 *
 * It targets the `['tenant', id, 'reviews']` **prefix**, which reaches every
 * filter/page combination without enumerating them. Patching would not be
 * enough either: approving moves a row **out of** the `DRAFTED` filter, and
 * only refetching the page the current parameters describe reflects that — the
 * `PATCH` response is a single review and knows nothing about `total` or the
 * page it was on.
 *
 * **`useCreateReview` invalidates the same prefix** (D11): a successful
 * creation adds a new row whose `status` is `NEW`, and the Borradores list
 * (filtered to `DRAFTED`) does not pick it up — but the Reseñas list does,
 * and the dashboard summary endpoint depends on totals that only a refetch
 * produces.
 *
 * **`EDIT` does not change `status`**, so the row stays in the same filter —
 * but its content on screen has changed, and the only way to reflect that is
 * to invalidating the prefix (the query keys include `id`, not `draft_content`).
 */
export function useRespondToReview(): UseMutationResult<
  Review,
  Error,
  RespondInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: (input: RespondInput) => {
      if (!tenantId) {
        throw new Error("Responding to a review requires a tenant context");
      }
      return getReviewsDataSource().respondToReview(tenantId, input);
    },
    retry: false,
    onSettled: () => {
      if (tenantId) {
        void queryClient.invalidateQueries({
          queryKey: reviewsKeys.listPrefix(tenantId),
        });
      }
    },
  });
}

/**
 * Manual create from the dialog (design D11). Same retry/invalidation
 * discipline as the response mutation.
 */
export function useCreateReview(): UseMutationResult<
  Review,
  Error,
  CreateReviewInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: (input: CreateReviewInput) => {
      if (!tenantId) {
        throw new Error("Creating a review requires a tenant context");
      }
      return getReviewsDataSource().createReview(tenantId, input);
    },
    retry: false,
    onSettled: () => {
      if (tenantId) {
        void queryClient.invalidateQueries({
          queryKey: reviewsKeys.listPrefix(tenantId),
        });
      }
    },
  });
}