/**
 * HttpOnly cookie session helpers.
 *
 * Why cookies (not localStorage)?
 *   The platform issues refresh tokens with 30-day lifetimes. Putting
 *   them in localStorage exposes them to any XSS. We instead persist
 *   both tokens in HttpOnly + SameSite=Lax cookies, set by server
 *   actions / route handlers. The browser never sees the values.
 *
 * This file is server-only (uses `next/headers`). Don't import from
 * client components.
 */
import { cookies } from "next/headers";

export type PlynthTokens = {
  access_token: string;
  refresh_token: string;
  expires_at: string; // ISO timestamp from the platform
};

const ACCESS_COOKIE = "plynth_access";
const REFRESH_COOKIE = "plynth_refresh";
const EXPIRES_COOKIE = "plynth_expires";

const ONE_DAY = 60 * 60 * 24;

function baseCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
  };
}

export function saveSession(tokens: PlynthTokens): void {
  const store = cookies();
  // Refresh-token cookie outlives the access-token cookie. We don't
  // need to match the exact 30-day server TTL — just be safely shorter.
  store.set(ACCESS_COOKIE, tokens.access_token, {
    ...baseCookieOptions(),
    maxAge: ONE_DAY, // a day is plenty; refresh covers the rest
  });
  store.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...baseCookieOptions(),
    maxAge: ONE_DAY * 29,
  });
  store.set(EXPIRES_COOKIE, tokens.expires_at, {
    ...baseCookieOptions(),
    maxAge: ONE_DAY * 29,
  });
}

export function readSession(): PlynthTokens | null {
  const store = cookies();
  const access = store.get(ACCESS_COOKIE)?.value;
  const refresh = store.get(REFRESH_COOKIE)?.value;
  const expires = store.get(EXPIRES_COOKIE)?.value;
  if (!access || !refresh || !expires) return null;
  return {
    access_token: access,
    refresh_token: refresh,
    expires_at: expires,
  };
}

export function clearSession(): void {
  const store = cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
  store.delete(EXPIRES_COOKIE);
}
