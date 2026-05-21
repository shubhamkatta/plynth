import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type {
  InviteUserPayload,
  InviteUserResponse,
  PlatformUser,
  UpdateUserPayload,
} from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerUserHandlers(): void {
  ipcMain.handle(IPC.users.list, () =>
    run<PlatformUser[]>(async () => call<PlatformUser[]>("GET", "/api/v1/users")),
  );

  ipcMain.handle(IPC.users.invite, (_e, payload: InviteUserPayload) =>
    run<InviteUserResponse>(async () =>
      call<InviteUserResponse>("POST", "/api/v1/users", { body: payload, idempotent: true }),
    ),
  );

  ipcMain.handle(IPC.users.update, (_e, id: string, payload: UpdateUserPayload) =>
    run<PlatformUser>(async () =>
      call<PlatformUser>("PATCH", `/api/v1/users/${id}`, { body: payload }),
    ),
  );

  ipcMain.handle(IPC.users.activate, (_e, id: string) =>
    run<PlatformUser>(async () => call<PlatformUser>("POST", `/api/v1/users/${id}/activate`)),
  );

  ipcMain.handle(IPC.users.deactivate, (_e, id: string) =>
    run<PlatformUser>(async () => call<PlatformUser>("POST", `/api/v1/users/${id}/deactivate`)),
  );

  ipcMain.handle(IPC.users.remove, (_e, id: string) =>
    run<null>(async () => {
      await call("DELETE", `/api/v1/users/${id}`);
      return null;
    }),
  );
}
