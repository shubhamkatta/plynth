// Registers every IPC handler. Called once from main process startup.

import { ipcMain, shell } from "electron";
import log from "electron-log/main";

import { IPC } from "@shared/ipc-channels";
import { run } from "@main/api/errors";
import { getConfig, setConfig } from "@main/config";

import { registerAuthHandlers } from "@main/ipc/auth";
import { registerProductHandlers } from "@main/ipc/products";
import { registerTenantHandlers } from "@main/ipc/tenants";
import { registerUserHandlers } from "@main/ipc/users";
import { registerPlanHandlers } from "@main/ipc/plans";
import { registerRoleHandlers } from "@main/ipc/roles";
import { registerSubscriptionHandlers } from "@main/ipc/subscriptions";
import { registerCreditHandlers } from "@main/ipc/credits";
import { registerAuditHandlers } from "@main/ipc/audit";

export function registerIpcHandlers(): void {
  registerAuthHandlers();
  registerProductHandlers();
  registerTenantHandlers();
  registerUserHandlers();
  registerPlanHandlers();
  registerRoleHandlers();
  registerSubscriptionHandlers();
  registerCreditHandlers();
  registerAuditHandlers();

  ipcMain.handle(IPC.system.baseUrl, () =>
    run(async () => getConfig().baseUrl),
  );

  ipcMain.handle(IPC.system.setBaseUrl, (_e, url: string) =>
    run(async () => { setConfig({ baseUrl: url }); return null; }),
  );

  ipcMain.handle(IPC.system.openExternal, (_e, url: string) =>
    run(async () => {
      // Only allow http(s) to prevent shell-protocol abuse.
      const parsed = new URL(url);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        throw new Error("only http(s) URLs may be opened externally");
      }
      await shell.openExternal(url);
      return null;
    }),
  );

  ipcMain.handle(IPC.system.adminProductSlug, () =>
    run<string | null>(async () => getConfig().adminProductSlug),
  );

  ipcMain.handle(IPC.system.setAdminProductSlug, (_e, slug: string | null) =>
    run<null>(async () => {
      // Switching products invalidates any acting-tenant pick (the tenant
      // slug doesn't exist in the new product). Clear both atomically.
      setConfig({
        adminProductSlug: slug && slug.trim() ? slug.trim() : null,
        actingTenantSlug: null,
      });
      return null;
    }),
  );

  ipcMain.handle(IPC.system.actingTenantSlug, () =>
    run<string | null>(async () => getConfig().actingTenantSlug),
  );

  ipcMain.handle(IPC.system.setActingTenantSlug, (_e, slug: string | null) =>
    run<null>(async () => {
      setConfig({ actingTenantSlug: slug && slug.trim() ? slug.trim() : null });
      return null;
    }),
  );

  log.info("ipc.registered");
}
