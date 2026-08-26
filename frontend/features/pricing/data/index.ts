import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import type { PricingDataSource } from "./pricing-source";
import { HttpPricingSource } from "./http/http-pricing-source";

export type { PricingDataSource } from "./pricing-source";
export type * from "./dto";

/**
 * The single composition point for the pricing screen's data source (design D1).
 * Components and hooks resolve their source ONLY through here, which is what lets
 * the component tests inject a double.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory.
 */
const { apiClient: pricingApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const pricingDataSource: PricingDataSource = new HttpPricingSource(
  pricingApiClient,
);

export function getPricingDataSource(): PricingDataSource {
  return pricingDataSource;
}
