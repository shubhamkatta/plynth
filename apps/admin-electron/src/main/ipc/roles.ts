import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type {
  AssignRolePayload,
  CreateRolePayload,
  Role,
  UpdateRolePayload,
} from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerRoleHandlers(): void {
  ipcMain.handle(IPC.roles.list, () =>
    run<Role[]>(async () => call<Role[]>("GET", "/api/v1/roles")),
  );

  ipcMain.handle(IPC.roles.create, (_e, payload: CreateRolePayload) =>
    run<Role>(async () =>
      call<Role>("POST", "/api/v1/roles", { body: payload, idempotent: true }),
    ),
  );

  ipcMain.handle(IPC.roles.update, (_e, id: string, payload: UpdateRolePayload) =>
    run<Role>(async () =>
      call<Role>("PATCH", `/api/v1/roles/${id}`, { body: payload }),
    ),
  );

  ipcMain.handle(IPC.roles.assign, (_e, payload: AssignRolePayload) =>
    run<null>(async () => {
      await call("POST", "/api/v1/roles/assign", { body: payload });
      return null;
    }),
  );

  ipcMain.handle(IPC.roles.permissions, () =>
    run<string[]>(async () => call<string[]>("GET", "/api/v1/roles/permissions")),
  );
}
