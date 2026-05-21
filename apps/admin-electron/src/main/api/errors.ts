import type { ApiError, Result } from "@shared/types";

/** Map any thrown thing to the canonical envelope.
 *
 *  IMPORTANT: always return a *plain object*, not an Error subclass.
 *  Electron's ipcMain.handle serializes via structured-clone, which drops
 *  custom properties from Error instances (only name/message/stack
 *  survive). Returning HttpError directly would silently strip code,
 *  status, and details by the time the renderer reads it — breaking
 *  status-based UI branches like the 404→null handling in useSubscription
 *  and turning specific conflict messages into generic ones. */
export function asApiError(err: unknown, status = 0): ApiError {
  if (typeof err === "object" && err !== null && "code" in err && "message" in err) {
    const e = err as Partial<ApiError>;
    return {
      code:    typeof e.code    === "string" ? e.code    : "internal_error",
      message: typeof e.message === "string" ? e.message : String(err),
      details: (e.details && typeof e.details === "object" ? e.details : {}) as Record<string, unknown>,
      status:  typeof e.status  === "number" ? e.status  : status,
    };
  }
  const message = err instanceof Error ? err.message : String(err);
  return {
    code:    status === 0 ? "network_error" : "internal_error",
    message,
    details: {},
    status,
  };
}

/** Helper for IPC handlers — wrap a body so it always returns a Result. */
export async function run<T>(fn: () => Promise<T>): Promise<Result<T>> {
  try {
    const data = await fn();
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: asApiError(err) };
  }
}
