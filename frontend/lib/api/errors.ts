/**
 * API error handling compatible ONLY with the common envelope defined by
 * PRD §23: `{ error: { code, message, details } }` (design D12). No endpoints,
 * DTOs, or business error codes are introduced here.
 */
export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;

  constructor(params: {
    code: string;
    message: string;
    status: number;
    details?: unknown;
  }) {
    super(params.message);
    this.name = "ApiError";
    this.code = params.code;
    this.status = params.status;
    this.details = params.details;
  }
}

export function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const { error } = value as { error: unknown };
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    "message" in error &&
    typeof (error as { code: unknown }).code === "string" &&
    typeof (error as { message: unknown }).message === "string"
  );
}

/**
 * Turns a non-ok Response into an ApiError. If the body matches the PRD §23
 * envelope, its code/message/details are used; otherwise a generic technical
 * error is produced. Messages are technical (English) — the UI maps them to
 * localized copy at the feature layer.
 */
export async function parseApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  if (isApiErrorEnvelope(body)) {
    return new ApiError({
      code: body.error.code,
      message: body.error.message,
      status: response.status,
      details: body.error.details,
    });
  }
  return new ApiError({
    code: "UNKNOWN_ERROR",
    message: `Request failed with status ${response.status}`,
    status: response.status,
  });
}
