import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  OwnerStatement,
  OwnerStatementDetail,
  OwnerStatementExpense,
  OwnerStatementFilters,
  OwnerStatementReservation,
  OwnerStatementsPage,
} from "../dto";
import type { StatementsDataSource } from "../statements-source";

type OwnerStatementResponse =
  components["schemas"]["OwnerStatementResponse"];
type OwnerStatementDetailResponse =
  components["schemas"]["OwnerStatementDetailResponse"];
type OwnerStatementExpenseResponse =
  components["schemas"]["OwnerStatementExpenseBreakdownResponse"];
type OwnerStatementReservationResponse =
  components["schemas"]["OwnerStatementReservationBreakdownResponse"];
type OwnerStatementPageResponse =
  components["schemas"]["OwnerStatementPageResponse"];

const ITEMS_PER_PAGE = 20;

function mapSummary(
  value: OwnerStatementResponse | OwnerStatementDetailResponse,
): OwnerStatement {
  return {
    id: value.id,
    propertyId: value.property_id,
    periodStart: value.period_start,
    periodEnd: value.period_end,
    status: value.status,
    grossRevenue: value.gross_revenue,
    otaCommissions: value.ota_commissions,
    netRevenue: value.net_revenue,
    cleaningCosts: value.cleaning_costs,
    laundryCosts: value.laundry_costs,
    amenitiesCosts: value.amenities_costs,
    maintenanceCosts: value.maintenance_costs,
    specialistCosts: value.specialist_costs,
    otherCosts: value.other_costs,
    platformFee: value.platform_fee,
    netOwnerResult: value.net_owner_result,
    notes: value.notes,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

function mapReservation(
  value: OwnerStatementReservationResponse,
): OwnerStatementReservation {
  return {
    id: value.id,
    checkInDate: value.check_in_date,
    nights: value.nights,
    grossAmount: value.gross_amount,
    otaCommission: value.ota_commission,
    netAmount: value.net_amount,
    currency: value.currency,
  };
}

function mapExpense(
  value: OwnerStatementExpenseResponse,
): OwnerStatementExpense {
  return {
    id: value.id,
    category: value.category,
    description: value.description,
    amount: value.amount,
    currency: value.currency,
    date: value.date,
  };
}

export function mapOwnerStatementResponse(
  value: OwnerStatementResponse,
): OwnerStatement {
  return mapSummary(value);
}

export function mapOwnerStatementDetailResponse(
  value: OwnerStatementDetailResponse,
): OwnerStatementDetail {
  return {
    ...mapSummary(value),
    reservations: value.reservations.map(mapReservation),
    expenses: value.expenses.map(mapExpense),
  };
}

export class HttpStatementsSource implements StatementsDataSource {
  constructor(private readonly client: ApiClient) {}

  async listStatements(
    _tenantId: string,
    filters: OwnerStatementFilters,
    page: number,
  ): Promise<OwnerStatementsPage> {
    const response: OwnerStatementPageResponse = await this.client.request<
      "/api/v1/owner-statements",
      "GET"
    >("/api/v1/owner-statements", {
      query: {
        page,
        per_page: ITEMS_PER_PAGE,
        ...(filters.propertyId !== undefined
          ? { property_id: filters.propertyId }
          : {}),
        ...(filters.periodStartFrom !== undefined
          ? { period_start_from: filters.periodStartFrom }
          : {}),
        ...(filters.periodStartTo !== undefined
          ? { period_start_to: filters.periodStartTo }
          : {}),
        ...(filters.status !== undefined ? { status: filters.status } : {}),
      },
    });

    return {
      items: response.items.map(mapOwnerStatementResponse),
      total: response.total,
      page: response.page,
      perPage: response.per_page,
    };
  }

  async getStatement(
    _tenantId: string,
    statementId: string,
  ): Promise<OwnerStatementDetail> {
    const response: OwnerStatementDetailResponse = await this.client.request(
      "/api/v1/owner-statements/{statement_id}",
      { method: "GET", pathParams: { statement_id: statementId } },
    );
    return mapOwnerStatementDetailResponse(response);
  }

  async exportCsv(_tenantId: string, statementId: string) {
    const response = await this.client.requestBinary(
      "/api/v1/owner-statements/{statement_id}/export.csv",
      { pathParams: { statement_id: statementId } },
    );
    return { bytes: response.bytes, headers: response.headers };
  }

  async exportPdf(_tenantId: string, statementId: string) {
    const response = await this.client.requestBinary(
      "/api/v1/owner-statements/{statement_id}/export.pdf",
      { pathParams: { statement_id: statementId } },
    );
    return { bytes: response.bytes, headers: response.headers };
  }
}
