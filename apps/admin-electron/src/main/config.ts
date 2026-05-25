import { app } from "electron";
import { join } from "node:path";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import log from "electron-log/main";

interface AppConfig {
  baseUrl:          string;
  /** Product slug the platform-admin token operates against. Only used when
   *  no user JWT session exists — pure admin mode needs to know which product
   *  to scope tenant/user/plan/etc calls into. */
  adminProductSlug: string | null;
  /** Direct-child tenant slug to scope every call into via the
   *  `X-Acting-Tenant-Slug` header. When null, calls operate on the
   *  product's root tenant (admin) or the user's home tenant. */
  actingTenantSlug: string | null;
}

// Local dev API by default — change in Settings on first launch if you've
// deployed elsewhere.
const DEFAULTS: AppConfig = {
  baseUrl:          "http://localhost:8000",
  adminProductSlug: null,
  actingTenantSlug: null,
};

const FILE = () => join(app.getPath("userData"), "config.json");

let cached: AppConfig | null = null;

export function getConfig(): AppConfig {
  if (cached) return cached;
  try {
    if (existsSync(FILE())) {
      const raw = readFileSync(FILE(), "utf-8");
      cached = { ...DEFAULTS, ...JSON.parse(raw) };
    } else {
      cached = { ...DEFAULTS };
    }
  } catch (err) {
    log.warn("config.read_failed", err);
    cached = { ...DEFAULTS };
  }
  return cached!;
}

export function setConfig(patch: Partial<AppConfig>): AppConfig {
  const merged = { ...getConfig(), ...patch };
  try {
    mkdirSync(app.getPath("userData"), { recursive: true });
    writeFileSync(FILE(), JSON.stringify(merged, null, 2), "utf-8");
    cached = merged;
    log.info("config.saved", merged);
  } catch (err) {
    log.error("config.write_failed", err);
    throw err;
  }
  return merged;
}
