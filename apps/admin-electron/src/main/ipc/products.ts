import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type { CreateProductPayload, Product } from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerProductHandlers(): void {
  ipcMain.handle(IPC.products.list, () =>
    run<Product[]>(async () =>
      call<Product[]>("GET", "/api/v1/admin/products", { asPlatformAdmin: true }),
    ),
  );

  ipcMain.handle(IPC.products.create, (_e, payload: CreateProductPayload) =>
    run<Product>(async () =>
      call<Product>("POST", "/api/v1/admin/products", {
        asPlatformAdmin: true,
        idempotent:      true,
        body:            payload,
      }),
    ),
  );
}
