import type {
  OwnerStatementDetail,
  OwnerStatementDownload,
  OwnerStatementFilters,
  OwnerStatementsPage,
} from "./dto";

/** Tenant-scoped statements boundary. `tenantId` is cache identity, never wire data. */
export interface StatementsDataSource {
  listStatements(
    tenantId: string,
    filters: OwnerStatementFilters,
    page: number,
  ): Promise<OwnerStatementsPage>;

  getStatement(
    tenantId: string,
    statementId: string,
  ): Promise<OwnerStatementDetail>;

  exportCsv(
    tenantId: string,
    statementId: string,
  ): Promise<OwnerStatementDownload>;

  exportPdf(
    tenantId: string,
    statementId: string,
  ): Promise<OwnerStatementDownload>;
}
