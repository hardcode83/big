import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpReviewsSource } from "./http/http-reviews-source";
import type { ReviewsDataSource } from "./reviews-source";

export type { ReviewsDataSource } from "./reviews-source";
export type * from "./dto";

/**
 * The single composition point for the reviews view's data source (design D1).
 * Components and hooks resolve their source ONLY through here, which is what
 * lets the component tests inject a double.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory.
 */
const { apiClient: reviewsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const reviewsDataSource: ReviewsDataSource = new HttpReviewsSource(
  reviewsApiClient,
);

export function getReviewsDataSource(): ReviewsDataSource {
  return reviewsDataSource;
}