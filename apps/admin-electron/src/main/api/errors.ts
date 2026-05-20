import type { ApiError, Result } from "@shared/types";

/** Map any thrown thing to the canonical envelope. */
export function asApiError(err: unknown, status = 0): ApiError {
  if (typeof err === "object" && err !== null && "code" in err && "message" in err) {
    return err as ApiError;
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
