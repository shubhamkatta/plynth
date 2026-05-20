import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type { CreateChildTenantPayload, Tenant, UpdateTenantPayload } from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerTenantHandlers(): void {
  ipcMain.handle(IPC.tenants.list, () =>
    run<Tenant[]>(async () => call<Tenant[]>("GET", "/api/v1/tenants")),
  );

  ipcMain.handle(IPC.tenants.createChild, (_e, payload: CreateChildTenantPayload) =>
    run<Tenant>(async () =>
      call<Tenant>("POST", "/api/v1/tenants", { body: payload, idempotent: true }),
    ),
  );

  ipcMain.handle(IPC.tenants.update, (_e, id: string, payload: UpdateTenantPayload) =>
    run<Tenant>(async () =>
      call<Tenant>("PATCH", `/api/v1/tenants/${id}`, { body: payload }),
    ),
  );

  ipcMain.handle(IPC.tenants.activate, (_e, id: string) =>
    run<Tenant>(async () =>
      call<Tenant>("POST", `/api/v1/tenants/${id}/activate`),
    ),
  );

  ipcMain.handle(IPC.tenants.deactivate, (_e, id: string) =>
    run<Tenant>(async () =>
      call<Tenant>("POST", `/api/v1/tenants/${id}/deactivate`),
    ),
  );
}
