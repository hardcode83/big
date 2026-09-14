import type { components } from "@/lib/api/generated/openapi";

export type OwnerStatementStatus =
  components["schemas"]["OwnerStatementStatus"];
export type StatementExpenseCategory =
  components["schemas"]["ExpenseCategory"];

/** Fields shared by the list and detail DTOs; the API keeps them flat. */
interface OwnerStatementSummaryFields {
  id: string;
  propertyId: string;
  periodStart: string;
  periodEnd: string;
  status: OwnerStatementStatus;
  grossRevenue: string;
  otaCommissions: string;
  netRevenue: string;
  cleaningCosts: string;
  laundryCosts: string;
  amenitiesCosts: string;
  maintenanceCosts: string;
  specialistCosts: string;
  otherCosts: string;
  platformFee: string;
  netOwnerResult: string;
  notes: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Camel-case DTO mapped from the list's `OwnerStatementResponse`. */
export interface OwnerStatement extends OwnerStatementSummaryFields {}

export interface OwnerStatementReservation {
  id: string;
  checkInDate: string;
  nights: number;
  grossAmount: string | null;
  otaCommission: string | null;
  netAmount: string | null;
  currency: string;
}

export interface OwnerStatementExpense {
  id: string;
  category: StatementExpenseCategory;
  description: string;
  amount: string;
  currency: string;
  date: string;
}

/** Separate additive DTO mapped from `OwnerStatementDetailResponse`. */
export interface OwnerStatementDetail extends OwnerStatementSummaryFields {
  reservations: OwnerStatementReservation[];
  expenses: OwnerStatementExpense[];
}

export interface OwnerStatementsPage {
  items: OwnerStatement[];
  total: number;
  page: number;
  perPage: number;
}

/** Only filters published by `GET /owner-statements`; tenant comes from auth. */
export interface OwnerStatementFilters {
  propertyId?: string;
  periodStartFrom?: string;
  periodStartTo?: string;
  status?: OwnerStatementStatus;
}

export interface OwnerStatementDownload {
  bytes: Uint8Array;
  headers: Headers;
}
