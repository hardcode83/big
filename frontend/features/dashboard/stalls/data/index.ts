/**
 * The single composition point for the dashboard card's blocked-transitions
 * data source (proposal `blocked-transitions-web` D9). UI and hooks resolve
 * their source ONLY through here, so swapping the implementation is a
 * one-line change confined to this file.
 *
 * The client is built from the same factory the rest of the dashboard uses
 * (`createAuthenticatedClients`); it carries the auth headers and the
 * one-shot refresh handshake that lives in `@/lib/api/authenticated-client`.
 */

import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";
import { HttpStallsSource } from "./http/http-stalls-source";

import type { StallsDataSource } from "./stalls-source";

export type { StallsDataSource } from "./stalls-source";
export type { BlockedTransitionSummary, BlockedTransitionPage } from "./dto";

const { apiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const stallsDataSource: StallsDataSource = new HttpStallsSource(apiClient);

export function getStallsDataSource(): StallsDataSource {
  return stallsDataSource;
}

/** Test seam: lets the test suite inject a `MockStallsSource`. */
export function __setStallsDataSourceForTests(source: StallsDataSource): void {
  stallsDataSourceOverride = source;
}

let stallsDataSourceOverride: StallsDataSource | null = null;

export function resolveStallsDataSource(): StallsDataSource {
  return stallsDataSourceOverride ?? stallsDataSource;
}