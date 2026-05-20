// All long-lived secrets (JWT pair, platform admin token) live in the
// OS secure store via `keytar`. We NEVER write them to the userData dir
// or pass them across IPC verbatim — the renderer only knows whether a
// token exists, never its value.

import keytar from "keytar";
import log from "electron-log/main";
import type { UserSession } from "@shared/types";

const SERVICE = "dev.plynth.admin";
const ACCOUNT_SESSION     = "user-session";
const ACCOUNT_ADMIN_TOKEN = "platform-admin-token";

// ---------- user session (JWT pair + identity) -----------------------------

export async function saveSession(s: UserSession): Promise<void> {
  await keytar.setPassword(SERVICE, ACCOUNT_SESSION, JSON.stringify(s));
  log.info("secrets.session_saved", { email: s.email, productSlug: s.productSlug });
}

export async function loadSession(): Promise<UserSession | null> {
  const raw = await keytar.getPassword(SERVICE, ACCOUNT_SESSION);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserSession;
  } catch (err) {
    log.warn("secrets.session_parse_failed", err);
    await keytar.deletePassword(SERVICE, ACCOUNT_SESSION);
    return null;
  }
}

export async function clearSession(): Promise<void> {
  await keytar.deletePassword(SERVICE, ACCOUNT_SESSION);
  log.info("secrets.session_cleared");
}

// ---------- platform admin token -------------------------------------------

export async function saveAdminToken(token: string): Promise<void> {
  if (!token || token.length < 16) throw new Error("platform admin token too short");
  await keytar.setPassword(SERVICE, ACCOUNT_ADMIN_TOKEN, token);
  log.info("secrets.admin_token_saved");
}

export async function loadAdminToken(): Promise<string | null> {
  return keytar.getPassword(SERVICE, ACCOUNT_ADMIN_TOKEN);
}

export async function hasAdminToken(): Promise<boolean> {
  return (await loadAdminToken()) !== null;
}

export async function clearAdminToken(): Promise<void> {
  await keytar.deletePassword(SERVICE, ACCOUNT_ADMIN_TOKEN);
  log.info("secrets.admin_token_cleared");
}
