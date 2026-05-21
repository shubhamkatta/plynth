import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type {
  CancelSubscriptionPayload,
  ChangeSubscriptionPayload,
  PurchaseSubscriptionPayload,
  Subscription,
} from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerSubscriptionHandlers(): void {
  ipcMain.handle(IPC.subscriptions.get, () =>
    run<Subscription>(async () =>
      call<Subscription>("GET", "/api/v1/subscription"),
    ),
  );

  ipcMain.handle(IPC.subscriptions.purchase, (_e, payload: PurchaseSubscriptionPayload) =>
    run<Subscription>(async () =>
      call<Subscription>("POST", "/api/v1/subscription/purchase", {
        body:       payload,
        idempotent: true,
      }),
    ),
  );

  ipcMain.handle(IPC.subscriptions.change, (_e, payload: ChangeSubscriptionPayload) =>
    run<Subscription>(async () =>
      call<Subscription>("POST", "/api/v1/subscription/change", {
        body:       payload,
        idempotent: true,
      }),
    ),
  );

  ipcMain.handle(IPC.subscriptions.cancel, (_e, payload: CancelSubscriptionPayload) =>
    run<Subscription>(async () =>
      call<Subscription>("POST", "/api/v1/subscription/cancel", { body: payload }),
    ),
  );
}
