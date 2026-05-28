import type { ApiErrorBody } from "./types.js";

export class PlynthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlynthError";
  }
}

export class PlynthApiError extends PlynthError {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(`${body.code}: ${body.message}`);
    this.name = "PlynthApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
  }
}

export class PlynthNetworkError extends PlynthError {
  override readonly cause?: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = "PlynthNetworkError";
    this.cause = cause;
  }
}

export async function parseErrorResponse(r: Response): Promise<PlynthApiError> {
  let body: ApiErrorBody;
  try {
    const parsed = (await r.json()) as Partial<ApiErrorBody>;
    body = {
      code: parsed.code ?? "http_error",
      message: parsed.message ?? r.statusText,
      details: (parsed.details as Record<string, unknown>) ?? {},
    };
  } catch {
    body = { code: "http_error", message: r.statusText, details: {} };
  }
  return new PlynthApiError(r.status, body);
}
