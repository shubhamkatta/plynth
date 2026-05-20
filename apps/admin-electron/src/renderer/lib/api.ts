// Renderer-side wrapper around the typed `window.api` bridge from the preload.
// Unwraps the Result envelope so React/TanStack-Query code just sees promises
// that resolve to data or throw `ApiError`-shaped exceptions.

import type { ApiError, BridgeApi, Result } from "@shared/types";

function unwrap<T>(p: Promise<Result<T>>): Promise<T> {
  return p.then(r => {
    if (r.ok) return r.data;
    const err: ApiError & Error = Object.assign(
      new Error(r.error.message),
      r.error,
    );
    throw err;
  });
}

// Curry a BridgeApi method so its return is the unwrapped data, not a Result.
type Unwrapped<T extends (...args: any[]) => Promise<Result<any>>> =
  T extends (...args: infer A) => Promise<Result<infer R>>
    ? (...args: A) => Promise<R>
    : never;

type UnwrappedNamespace<N> = {
  [K in keyof N]: N[K] extends (...args: any[]) => Promise<Result<any>>
    ? Unwrapped<N[K]>
    : N[K] extends object
      ? UnwrappedNamespace<N[K]>
      : never;
};

function liftNamespace<T extends object>(ns: T): UnwrappedNamespace<T> {
  const out: any = {};
  for (const k of Object.keys(ns) as (keyof T)[]) {
    const v = ns[k];
    if (typeof v === "function") {
      out[k] = (...args: unknown[]) => unwrap((v as (...a: unknown[]) => Promise<Result<unknown>>)(...args));
    } else if (typeof v === "object" && v !== null) {
      out[k] = liftNamespace(v);
    }
  }
  return out;
}

/** Typed renderer API. Use this — never window.api directly. */
export const api: UnwrappedNamespace<BridgeApi> = liftNamespace(window.api);

/** Type guard: is this thrown thing an ApiError? */
export function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null
    && "code" in e && "message" in e && "status" in e;
}

/** Human-friendly summary of an error for toasts. */
export function describeError(e: unknown): string {
  if (isApiError(e)) {
    if (e.code === "validation_failed" && Array.isArray((e.details as any)?.errors)) {
      const errs = (e.details as any).errors as { loc: string[]; msg: string }[];
      return errs.map(x => `${x.loc.join(".")}: ${x.msg}`).join(" · ");
    }
    return `${e.code}: ${e.message}`;
  }
  return e instanceof Error ? e.message : String(e);
}
