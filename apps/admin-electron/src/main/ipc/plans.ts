import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type { CreatePlanPayload, Plan, UpdatePlanPayload } from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerPlanHandlers(): void {
  ipcMain.handle(IPC.plans.list, () =>
    run<Plan[]>(async () => call<Plan[]>("GET", "/api/v1/plans")),
  );

  ipcMain.handle(IPC.plans.create, (_e, payload: CreatePlanPayload) =>
    run<Plan>(async () =>
      call<Plan>("POST", "/api/v1/plans", { body: payload, idempotent: true }),
    ),
  );

  ipcMain.handle(IPC.plans.update, (_e, code: string, payload: UpdatePlanPayload) =>
    run<Plan>(async () =>
      call<Plan>("PATCH", `/api/v1/plans/${code}`, { body: payload }),
    ),
  );
}
